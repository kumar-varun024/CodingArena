"""Human operator HTTP client with a persistent, non-secret retry journal."""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from .contract import canonical_bytes


def parser(commands):
    operator = commands.add_parser("operator", help="human operator HTTP commands")
    operator.add_argument("--api-url", default=os.environ.get("ARENA_API_URL", "http://127.0.0.1:8765"))
    operations = operator.add_subparsers(dest="operation", required=True)
    create = operations.add_parser("create")
    create.add_argument("--label-a", default="Unavailable")
    create.add_argument("--label-b", default="Unavailable")
    create.add_argument("--budget-minutes", type=int, default=10)
    create.add_argument("--max-repair-rounds", type=int, default=2)
    action = operations.add_parser("action")
    action.add_argument("--match", required=True)
    action.add_argument("--action", choices=["reveal", "cancel", "start_repair", "finalize"], required=True)
    action.add_argument("--reason", required=True)
    decision = operations.add_parser("decision")
    decision.add_argument("--match", required=True)
    decision.add_argument("--challenge", required=True)
    decision.add_argument("--disposition", choices=["accepted", "rejected"], required=True)
    decision.add_argument("--reason", required=True)
    select = operations.add_parser("select")
    select.add_argument("--match", required=True)
    select.add_argument("--selection", choices=["a", "b", "neither"], required=True)
    select.add_argument("--candidate")
    select.add_argument("--evidence-key", help="JSON file containing the exact EvidenceKey")
    select.add_argument("--reason", required=True)
    for mutation in (create, action, decision, select):
        mutation.add_argument("--request-id", type=UUID)
        mutation.add_argument("--room-id")
        mutation.add_argument("--message-id")
        mutation.add_argument("--note")
        mutation.add_argument("--source-kind", choices=["operator_recorded", "fixture"], default="operator_recorded")
    retry = operations.add_parser("retry", help="resend an exact journalled operation")
    retry.add_argument("--request-id", type=UUID, required=True)
    match = operations.add_parser("match")
    match.add_argument("--match", required=True)
    job = operations.add_parser("job")
    job.add_argument("--id", required=True)
    export = operations.add_parser("export")
    export.add_argument("--match", required=True)
    export.add_argument("--output", type=Path)


def run(args, settings):
    method, body = "POST", None
    journal_root = settings.state_dir / "operator-requests"
    if args.operation == "retry":
        record = json.loads((journal_root / (str(args.request_id) + ".json")).read_text())
        endpoint, body = record["endpoint"], record["body"]
    elif args.operation in ("match", "job"):
        method = "GET"
        endpoint = "/matches/" + args.match if args.operation == "match" else "/jobs/" + args.id
    elif args.operation != "export":
        request_id = str(args.request_id or uuid4())
        source = {"kind": args.source_kind, "room_id": args.room_id,
                  "message_id": args.message_id, "note": args.note}
        body = {"request_id": request_id, "source": source}
        if args.operation == "create":
            endpoint = "/matches"
            body.update(task_id="booking-v1", candidate_budget_minutes=args.budget_minutes,
                        max_repair_rounds=args.max_repair_rounds,
                        provider_labels={"a": args.label_a, "b": args.label_b})
        elif args.operation == "action":
            endpoint = "/matches/" + args.match + "/actions"
            body.update(action=args.action, reason=args.reason)
        elif args.operation == "decision":
            endpoint = f"/matches/{args.match}/challenges/{args.challenge}/decision"
            body.update(disposition=args.disposition, reason=args.reason)
        else:
            endpoint = "/matches/" + args.match + "/selection"
            if args.selection == "neither":
                candidate_id, evidence_key = None, None
            else:
                if not args.candidate or not args.evidence_key:
                    raise ValueError("selection a/b requires --candidate and --evidence-key")
                candidate_id = args.candidate
                evidence_key = json.loads(Path(args.evidence_key).read_text(encoding="utf-8"))
                expected_keys = {"candidate_digest", "runner_digest", "spec_digest", "suite_digest"}
                if type(evidence_key) is not dict or set(evidence_key) != expected_keys:
                    raise ValueError("--evidence-key must contain all four EvidenceKey fields")
            if args.selection == "neither" and (args.candidate or args.evidence_key):
                raise ValueError("selection neither does not accept --candidate or --evidence-key")
            body.update(selection=args.selection, candidate_id=candidate_id,
                        expected_evidence_key=evidence_key, reason=args.reason)
        record = {"endpoint": endpoint, "body": body}
        journal_root.mkdir(mode=0o700, exist_ok=True)
        destination = journal_root / (request_id + ".json")
        if destination.exists():
            if canonical_bytes(json.loads(destination.read_text())) != canonical_bytes(record):
                raise ValueError("Request ID already journalled with a different operation/body")
        else:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical_bytes(record))
                stream.flush()
                os.fsync(stream.fileno())
    if body is not None:
        print("request_id=" + body["request_id"], file=sys.stderr)
    token = (settings.state_dir / "auth/operator.token").read_text().strip()
    api_root = args.api_url.rstrip("/") + "/api/v1"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    try:
        if args.operation == "export":
            _export(args, settings, api_root, headers)
        else:
            request = Request(api_root + endpoint, method=method,
                              data=canonical_bytes(body) if body is not None else None, headers=headers)
            with urlopen(request, timeout=15) as response:
                print(response.read().decode("utf-8"))
        return 0
    except HTTPError as exc:
        print(exc.read().decode("utf-8"))
        return 1
    except (URLError, TimeoutError):
        print("Transport failed; outcome is unknown. Retry the same request ID using operator retry.", file=sys.stderr)
        return 1


def _export(args, settings, api_root, headers):
    if not args.match or args.match in {".", ".."} or "/" in args.match or "\\" in args.match:
        raise ValueError("match ID must be a single path component")
    def get(path):
        with urlopen(Request(api_root + path, headers=headers), timeout=15) as response:
            return response.read()

    match = json.loads(get("/matches/" + quote(args.match, safe="")))
    if type(match) is not dict or match.get("phase") != "complete" or type(match.get("outcome")) is not dict:
        raise ValueError("match must be complete before export")
    events = json.loads(get("/matches/" + quote(args.match, safe="") + "/events?after=0"))
    if type(events) is dict:
        events = events.get("events")
    if type(events) is not list:
        raise ValueError("match events response is invalid")
    selected = next((event for event in reversed(events)
                     if type(event) is dict and event.get("type") == "match.selected"), None)
    data = selected.get("data") if type(selected) is dict else None
    artifact_ids = data.get("artifacts") if type(data) is dict else None
    if type(artifact_ids) is not dict:
        raise ValueError("selection event has no artifact IDs")
    expected = {"evidence.json": match["outcome"].get("evidence_artifact_id"),
                "summary.md": artifact_ids.get("summary.md")}
    if match["outcome"].get("selection") in {"a", "b"}:
        expected["candidate.patch"] = match["outcome"].get("patch_artifact_id")
    if any(type(value) is not str or not value for value in expected.values()):
        raise ValueError("selection is missing a required artifact ID")
    contents = {name: get("/artifacts/" + quote(artifact_id, safe=""))
                for name, artifact_id in expected.items()}
    destination = args.output or settings.state_dir / "exports" / args.match
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in contents.items():
        path = destination / name
        if path.exists() and (not path.is_file() or path.read_bytes() != content):
            raise FileExistsError(f"refusing to overwrite different export file: {path}")
    paths = []
    for name, content in contents.items():
        path = destination / name
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(content)
        paths.append(str(path))
    print(json.dumps({"files": paths}, separators=(",", ":")))
