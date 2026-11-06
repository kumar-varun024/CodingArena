#!/usr/bin/env python3
"""Slot-scoped Coding Arena client, interface 1.1; Python standard library only.

The engine chooses workspaces and computes evidence. This client never runs Git,
executes submitted code, accepts a workspace override, or acts as an operator.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from typing import Any, Callable, TextIO
from urllib import error, parse, request
import uuid


API_VERSION = "1.1"
DEFAULT_API_URL = "http://127.0.0.1:8765"
REQUIREMENT_IDS = frozenset(f"BOOK-{number:02d}" for number in range(1, 8))
DEFAULT_SOURCE_NOTE = "Switch origin is not automatically verified."


class ClientError(Exception):
    """A configuration, journal, protocol, transport, or API error."""


class WaitTimeout(ClientError):
    """The entire bounded job wait elapsed; the job outcome is still unknown."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ClientError(f"argument error: {message}")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def redact_payload(value: Any, token: str) -> Any:
    """Remove reflected credentials before JSON encoding, including escaped text."""
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [redact_payload(item, token) for item in value]
    if isinstance(value, dict):
        return {key.replace(token, "[redacted]"): redact_payload(item, token) for key, item in value.items()}
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def load_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_number)


def normalize_api_url(value: str) -> str:
    parts = parse.urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.path.rstrip("/") not in {"", "/api/v1"}):
        raise ClientError("--api-url must be an HTTP(S) origin, optionally ending in /api/v1; no credentials, query, or fragment")
    try:
        parts.port
    except ValueError as exc:
        raise ClientError("--api-url has an invalid port") from exc
    return parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "/api/v1", "", ""))


def _positive(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def build_parser() -> Parser:
    common = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--api-url", help="engine origin or /api/v1 URL; defaults to ARENA_API_URL or localhost:8765")
    common.add_argument("--token-file", help="slot token file; defaults to ARENA_TOKEN_FILE (never pass a token value)")
    common.add_argument("--state-dir", help="non-secret retry journal directory; defaults to ARENA_CLIENT_STATE_DIR")
    common.add_argument("--http-timeout", type=_positive, help="per-request timeout in seconds (default 10)")
    common.add_argument("--poll-interval", type=_positive, help="job poll interval in seconds (default 2)")
    common.add_argument("--request-id", help="UUID for a mutation; reuse exactly the same operation/body after an ambiguous outcome")
    common.add_argument("--source-kind", choices=("switch_context", "unverified_context", "fixture"))
    common.add_argument("--room-id")
    common.add_argument("--message-id")
    common.add_argument("--source-note")
    parser = Parser(description=__doc__, parents=[common])
    parser.add_argument("--version", action="version", version=f"arena-client {API_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("assignment", "check", "submit", "challenge", "review-done", "job", "match"):
        command = commands.add_parser(name, parents=[common])
        if name in {"assignment", "check", "submit", "challenge", "review-done"}:
            command.add_argument("--match", required=True, help="assigned match ID")
        if name in {"assignment", "check", "submit", "review-done"}:
            command.add_argument("--slot", required=True, choices=("a", "b"))
        if name in {"check", "submit"}:
            command.add_argument("--commit", required=True, help="clean commit SHA in the engine-assigned checkout")
        if name in {"challenge", "review-done"}:
            command.add_argument("--target", required=True, help="exact frozen opponent candidate ID")
        if name == "challenge":
            command.add_argument("--file", required=True, help="UTF-8 ChallengeFile: title, requirement_ids, scenario")
        if name in {"job", "match"}:
            command.add_argument("--id", required=True)
        if name == "job":
            command.add_argument("--wait", action="store_true")
            command.add_argument("--timeout", type=_positive, default=120.0, help="total wait deadline in seconds (default 120)")
    return parser


def _valid_expected(value: Any) -> bool:
    if type(value) in {bool, int}:
        return True
    if isinstance(value, dict):
        return all(isinstance(key, str) and _valid_expected(item) for key, item in value.items())
    return False


def validate_challenge(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"title", "requirement_ids", "scenario"}:
        raise ClientError("challenge file must contain exactly title, requirement_ids and scenario; a bare Scenario is not valid")
    if not isinstance(value["title"], str) or not value["title"].strip():
        raise ClientError("challenge title must be a non-empty string")
    ids = value["requirement_ids"]
    if (not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids) or not set(ids) <= REQUIREMENT_IDS):
        raise ClientError("requirement_ids must be non-empty, unique BOOK-01 through BOOK-07 strings")
    scenario = value["scenario"]
    if not isinstance(scenario, dict) or set(scenario) != {"capacity", "steps"}:
        raise ClientError("scenario must contain exactly capacity and steps")
    if type(scenario["capacity"]) is not int or not 1 <= scenario["capacity"] <= 20:
        raise ClientError("scenario capacity must be an integer from 1 through 20 (not bool)")
    steps = scenario["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ClientError("scenario must contain 1 through 30 steps")
    arities = {"book": 2, "cancel": 1, "available": 0, "reservations": 0}
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) != {"op", "args", "expected"}:
            raise ClientError(f"step {index} must contain exactly op, args and expected")
        op = step["op"]
        if not isinstance(op, str) or op not in arities:
            raise ClientError(f"step {index} has an unsupported operation")
        if not isinstance(step["args"], list) or len(step["args"]) != arities[op]:
            raise ClientError(f"step {index}: {op} requires {arities[op]} positional arguments")
        # Business-invalid JSON argument values are deliberately allowed for BOOK-06.
        # The trusted reference, not this client, judges their expected behavior.
        if not _valid_expected(step["expected"]):
            raise ClientError(f"step {index}: expected must use booleans, integers or objects; no null/floats")
    return value


class Journal:
    """Persist a canonical, non-secret request before the first network write."""

    def __init__(self, root: Path, api_url: str, token: str):
        token_fingerprint = hashlib.sha256(token.encode()).hexdigest()
        scope = hashlib.sha256((api_url + "\n" + token_fingerprint).encode()).hexdigest()
        self.directory = root / scope
        self.api_url = api_url

    def prepare(self, endpoint: str, body: dict[str, Any], request_id: str) -> None:
        endpoint_key = hashlib.sha256(endpoint.encode()).hexdigest()[:24]
        destination = self.directory / f"{endpoint_key}-{request_id}.json"
        record = {"api_url": self.api_url, "method": "POST", "endpoint": endpoint,
                  "request_id": request_id, "body": body}
        encoded = canonical(record).encode("utf-8")
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".pending-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                try:
                    os.link(temporary, destination)  # atomic create; never overwrite another operation
                except FileExistsError:
                    saved = load_json(destination.read_text(encoding="utf-8"))
                    if canonical(saved) != canonical(record):
                        raise ClientError(f"request_id {request_id} conflicts with its persisted request; retry the original body or choose a new ID for a new operation")
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                temporary.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            raise ClientError("could not durably save/read retry journal; no mutation was sent") from exc


class NoRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req: request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None  # Never forward a slot credential to a redirected origin/path.


class ArenaClient:
    def __init__(self, api_url: str, token: str, *, http_timeout: float = 10,
                 diagnostics: Callable[[str], None] | None = None):
        self.api_url = normalize_api_url(api_url)
        self._token = token
        self.http_timeout = http_timeout
        self.mode: str | None = None
        self._diagnostics = diagnostics or (lambda _: None)
        self._opener = request.build_opener(NoRedirects())

    def call(self, method: str, endpoint: str, body: dict[str, Any] | None = None,
             timeout: float | None = None) -> dict[str, Any]:
        data = None if body is None else canonical(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        outgoing = request.Request(self.api_url + endpoint, data=data, headers=headers, method=method)
        try:
            try:
                response = self._opener.open(outgoing, timeout=timeout or self.http_timeout)
            except error.HTTPError as http_error:
                response = http_error
            with response:
                mode = response.headers.get("X-Arena-Mode")
                self.mode = mode if mode in {"live", "fixture"} else None
                if self.mode is None:
                    raise ClientError("protocol error: missing/invalid X-Arena-Mode; response mode is unknown")
                self._diagnostics(f"mode={self.mode}")
                try:
                    payload = load_json(response.read().decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ClientError("protocol error: response is not valid UTF-8 JSON") from exc
                if not isinstance(payload, dict):
                    raise ClientError("protocol error: response must be a JSON object")
                if "mode" in payload and payload["mode"] != self.mode:
                    self.mode = None
                    raise ClientError("protocol error: body mode conflicts with X-Arena-Mode; response mode is unknown")
                if not 200 <= response.status < 300:
                    detail = payload.get("error", {})
                    if not isinstance(detail, dict):
                        detail = {}
                    raise ClientError(f"HTTP {response.status} {detail.get('code', 'API_ERROR')}: {detail.get('message', 'request rejected')}")
                return payload
        except (error.URLError, TimeoutError, socket.timeout, OSError, HTTPException) as exc:
            raise ClientError("transport error: request failed or timed out; mutation outcome may be unknown; retry the same persisted request ID and body") from exc

    def wait_job(self, job_id: str, *, timeout: float = 120, interval: float = 2) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeout("job wait timed out; job outcome remains unknown; poll the same job ID again")
            try:
                job = self.call("GET", "/jobs/" + parse.quote(job_id, safe=""),
                                timeout=min(self.http_timeout, remaining))
            except ClientError as exc:
                if time.monotonic() >= deadline:
                    raise WaitTimeout("job wait timed out; job outcome remains unknown; poll the same job ID again") from exc
                raise
            if job.get("status") in {"completed", "error"}:
                return job
            if job.get("status") not in {"queued", "running"}:
                raise ClientError("protocol error: job has an unknown status")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeout("job wait timed out; job outcome remains unknown; poll the same job ID again")
            time.sleep(min(interval, remaining))


def _source(args: argparse.Namespace) -> dict[str, Any]:
    return {"kind": getattr(args, "source_kind", "unverified_context"),
            "room_id": getattr(args, "room_id", None),
            "message_id": getattr(args, "message_id", None),
            "note": getattr(args, "source_note", DEFAULT_SOURCE_NOTE)}


def _mutation(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    match_path = "/matches/" + parse.quote(args.match, safe="")
    if args.command in {"check", "submit"}:
        endpoint = match_path + ("/practice" if args.command == "check" else "/submissions")
        body = {"slot": args.slot, "commit_sha": args.commit}
    elif args.command == "challenge":
        try:
            challenge = validate_challenge(load_json(Path(args.file).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ClientError("could not read challenge file as valid UTF-8 JSON") from exc
        endpoint = match_path + "/challenges"
        body = {**challenge, "target_candidate_id": args.target}
    else:
        endpoint = match_path + f"/reviews/{args.slot}/complete"
        body = {"target_candidate_id": args.target}
    return endpoint, {**body, "source": _source(args)}


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    token = ""

    def diagnostic(message: str) -> None:
        # A broken server must not echo a credential through diagnostics.
        print(message.replace(token, "[redacted]") if token else message, file=stderr)

    try:
        args = build_parser().parse_args(argv)
        token_file = getattr(args, "token_file", os.environ.get("ARENA_TOKEN_FILE"))
        if not token_file:
            raise ClientError("--token-file or ARENA_TOKEN_FILE is required; use your slot-scoped token file")
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ClientError("could not read slot token file") from exc
        if not token or any(character.isspace() for character in token):
            raise ClientError("slot token file must contain one non-empty token")
        client = ArenaClient(getattr(args, "api_url", os.environ.get("ARENA_API_URL", DEFAULT_API_URL)), token,
                             http_timeout=getattr(args, "http_timeout", 10), diagnostics=diagnostic)
        if args.command == "assignment":
            result = client.call("GET", f"/matches/{parse.quote(args.match, safe='')}/assignments/{args.slot}")
        elif args.command == "match":
            result = client.call("GET", "/matches/" + parse.quote(args.id, safe=""))
        elif args.command == "job":
            result = (client.wait_job(args.id, timeout=args.timeout, interval=getattr(args, "poll_interval", 2))
                      if args.wait else client.call("GET", "/jobs/" + parse.quote(args.id, safe="")))
        else:
            endpoint, body = _mutation(args)
            try:
                request_id = str(uuid.UUID(args.request_id)) if hasattr(args, "request_id") else str(uuid.uuid4())
            except (ValueError, AttributeError) as exc:
                raise ClientError("--request-id must be a UUID") from exc
            body["request_id"] = request_id
            diagnostic(f"request_id={request_id}; retry this ID with the same command/body after an ambiguous outcome")
            encoded_body = canonical(body)
            if token in encoded_body or canonical(token)[1:-1] in encoded_body:
                raise ClientError("refusing to persist or send the slot credential in a mutation body")
            state_dir = Path(getattr(args, "state_dir", os.environ.get("ARENA_CLIENT_STATE_DIR", str(Path.home() / ".local/state/coding-arena-client"))))
            Journal(state_dir, client.api_url, token).prepare(endpoint, body, request_id)
            result = client.call("POST", endpoint, body)
        print(canonical(redact_payload(result, token)), file=stdout)
        return 0
    except WaitTimeout as exc:
        diagnostic(str(exc))
        return 2
    except (ClientError, ValueError, RecursionError) as exc:
        diagnostic(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
