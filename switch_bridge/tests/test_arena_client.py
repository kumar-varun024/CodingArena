"""Contract-focused CLI checks against actual local HTTP, without an engine."""

from __future__ import annotations

from contextlib import contextmanager
import copy
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arena_client as client


TOKEN = "fixture-slot-secret-for-tests"


@contextmanager
def server(responder):
    calls = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length else None
            body = json.loads(data) if data else None
            with lock:
                calls.append({"method": self.command, "path": self.path, "body": body,
                              "authorization": self.headers.get("Authorization")})
                number = len(calls)
            status, payload, headers = responder(self.command, self.path, body, number)
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Deliberately timed-out requests are part of these tests.

        do_GET = handle_request
        do_POST = handle_request

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", calls
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def fixture(payload, status=200):
    return status, payload, {"X-Arena-Mode": "fixture"}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.token_file = self.root / "slot.token"
        self.token_file.write_text(TOKEN)
        self.state = self.root / "journal"

    def run_cli(self, url, *arguments):
        output, diagnostic = io.StringIO(), io.StringIO()
        code = client.main(["--api-url", url, "--token-file", str(self.token_file),
                            "--state-dir", str(self.state), *arguments],
                           stdout=output, stderr=diagnostic)
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertNotIn(TOKEN, diagnostic.getvalue())
        return code, output.getvalue(), diagnostic.getvalue()

    def challenge_file(self, value=None):
        challenge = value if value is not None else {
            "title": "A second cancellation changes nothing",
            "requirement_ids": ["BOOK-03", "BOOK-04"],
            "scenario": {"capacity": 3, "steps": [
                {"op": "book", "args": ["family", 2], "expected": True},
                {"op": "cancel", "args": ["family"], "expected": True},
                {"op": "cancel", "args": ["family"], "expected": False},
                {"op": "available", "args": [], "expected": 3},
                {"op": "reservations", "args": [], "expected": {}},
            ]}}
        path = self.root / "challenge.json"
        path.write_text(json.dumps(challenge))
        return path

    def test_read_commands_and_assignment_paths_are_server_owned(self):
        assignment = {"workspace_path": "/fixture/workers/a/worktree", "review_path": None}
        with server(lambda *_: fixture(assignment)) as (url, calls):
            code, output, diagnostic = self.run_cli(url + "/api/v1/", "assignment", "--match", "m/1", "--slot", "a")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), assignment)
            self.assertEqual(calls[0]["path"], "/api/v1/matches/m%2F1/assignments/a")
            self.assertEqual(calls[0]["authorization"], "Bearer " + TOKEN)
            self.assertIn("mode=fixture", diagnostic)
            self.assertEqual(self.run_cli(url, "match", "--id", "m1")[0], 0)
            self.assertEqual(calls[-1]["path"], "/api/v1/matches/m1")
            self.assertEqual(self.run_cli(url, "job", "--id", "j1")[0], 0)
            self.assertEqual(calls[-1]["path"], "/api/v1/jobs/j1")
            self.assertEqual(self.run_cli(url, "assignment", "--match", "m", "--slot", "a", "--workspace", "/tmp")[0], 1)

    def test_check_and_submit_send_only_commit_slot_and_metadata(self):
        with server(lambda *_: fixture({"job_id": "j1"}, 202)) as (url, calls):
            for command, ending in [("check", "/practice"), ("submit", "/submissions")]:
                with self.subTest(command=command):
                    code, output, diagnostic = self.run_cli(url, command, "--match", "m1", "--slot", "b", "--commit", "abc123")
                    self.assertEqual(code, 0)
                    self.assertEqual(json.loads(output), {"job_id": "j1"})
                    self.assertTrue(calls[-1]["path"].endswith(ending))
                    body = calls[-1]["body"]
                    self.assertEqual(set(body), {"commit_sha", "slot", "source", "request_id"})
                    self.assertEqual(body["slot"], "b")
                    self.assertEqual(body["source"], {"kind": "unverified_context", "room_id": None,
                                                       "message_id": None, "note": client.DEFAULT_SOURCE_NOTE})
                    self.assertIn(body["request_id"], diagnostic)

    def test_journal_is_durable_before_write_and_contains_no_token(self):
        operation = str(uuid.uuid4())

        def responder(method, path, body, count):
            records = list(self.state.glob("*/*.json"))
            self.assertEqual(len(records), 1)
            saved = json.loads(records[0].read_text())
            self.assertEqual(saved["body"], body)
            self.assertEqual(saved["request_id"], operation)
            self.assertEqual(records[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn(TOKEN, records[0].read_text())
            return fixture({"job_id": "j"}, 202)

        with server(responder) as (url, _):
            self.assertEqual(self.run_cli(url, "submit", "--match", "m", "--slot", "a", "--commit", "sha", "--request-id", operation)[0], 0)

    def test_timeout_then_new_invocation_reuses_exact_request(self):
        operation = str(uuid.uuid4())

        def responder(method, path, body, count):
            if count == 1:
                time.sleep(0.12)
            return fixture({"job_id": "same-job"}, 202)

        with server(responder) as (url, calls):
            arguments = ["submit", "--match", "m", "--slot", "a", "--commit", "same-sha", "--request-id", operation]
            code, output, diagnostic = self.run_cli(url, *arguments, "--http-timeout", "0.025")
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn(operation, diagnostic)
            self.assertEqual(self.run_cli(url, *arguments, "--http-timeout", "1")[0], 0)
            self.assertEqual(calls[0]["body"], calls[1]["body"])
            self.assertEqual(len(list(self.state.glob("*/*.json"))), 1)

    def test_changed_body_rejected_before_network_write(self):
        operation = str(uuid.uuid4())
        with server(lambda *_: fixture({"job_id": "j"}, 202)) as (url, calls):
            arguments = ["submit", "--match", "m", "--slot", "a", "--request-id", operation]
            self.assertEqual(self.run_cli(url, *arguments, "--commit", "first")[0], 0)
            code, output, diagnostic = self.run_cli(url, *arguments, "--commit", "different")
            self.assertEqual(code, 1)
            self.assertIn("conflicts", diagnostic)
            self.assertEqual(output, "")
            self.assertEqual(len(calls), 1)

    def test_request_id_scope_separates_actor_and_endpoint(self):
        operation = str(uuid.uuid4())
        with server(lambda *_: fixture({"job_id": "j"}, 202)) as (url, calls):
            arguments = ["--match", "m", "--slot", "a", "--commit", "sha", "--request-id", operation]
            self.assertEqual(self.run_cli(url, "check", *arguments)[0], 0)
            self.assertEqual(self.run_cli(url, "submit", *arguments)[0], 0)
            self.token_file.write_text("other-fixture-slot-secret")
            self.assertEqual(self.run_cli(url, "submit", *arguments)[0], 0)
            self.assertEqual(len(list(self.state.glob("*/*.json"))), 3)
            self.assertEqual(len(calls), 3)

    def test_challenge_envelope_and_source_flags(self):
        path = self.challenge_file()
        with server(lambda *_: fixture({"challenge_id": "c", "job_id": "j"}, 202)) as (url, calls):
            code, _, _ = self.run_cli(url, "--source-kind", "switch_context", "challenge", "--match", "m", "--target", "frozen-b", "--file", str(path), "--room-id", "actual-room", "--message-id", "actual-message")
            self.assertEqual(code, 0)
            body = calls[0]["body"]
            self.assertEqual(body["scenario"], json.loads(path.read_text())["scenario"])
            self.assertEqual(body["target_candidate_id"], "frozen-b")
            self.assertEqual(body["source"]["kind"], "switch_context")
            self.assertEqual(body["source"]["room_id"], "actual-room")
            self.assertEqual(body["source"]["message_id"], "actual-message")

    def test_review_done_targets_frozen_opponent(self):
        with server(lambda *_: fixture({"mode": "fixture", "phase": "reviewing"})) as (url, calls):
            self.assertEqual(self.run_cli(url, "review-done", "--match", "m", "--slot", "a", "--target", "frozen-b")[0], 0)
            self.assertEqual(calls[0]["path"], "/api/v1/matches/m/reviews/a/complete")
            self.assertEqual(calls[0]["body"]["target_candidate_id"], "frozen-b")

    def test_business_invalid_json_arguments_are_preserved(self):
        for seats in (True, 0, -1, 1.5, None, "two"):
            with self.subTest(seats=seats):
                value = {"title": "Reject invalid seats", "requirement_ids": ["BOOK-06"],
                         "scenario": {"capacity": 2, "steps": [
                             {"op": "book", "args": [[], seats], "expected": False},
                             {"op": "available", "args": [], "expected": 2}]}}
                checked = client.validate_challenge(value)
                self.assertIs(checked["scenario"]["steps"][0]["args"][1], seats)
        self.assertNotEqual(client.canonical({"expected": True}), client.canonical({"expected": 1}))

    def test_invalid_challenge_file_is_rejected_before_network(self):
        valid = json.loads(self.challenge_file().read_text())
        invalid = [valid["scenario"], {**valid, "request_id": str(uuid.uuid4())},
                   {**valid, "title": ""}, {**valid, "requirement_ids": ["BOOK-99"]},
                   {**valid, "requirement_ids": ["BOOK-01", "BOOK-01"]},
                   {**valid, "requirement_ids": [True]},
                   {**valid, "scenario": {"capacity": True, "steps": valid["scenario"]["steps"]}}]
        for expected in (None, 1.5, []):
            value = copy.deepcopy(valid)
            value["scenario"]["steps"][0]["expected"] = expected
            invalid.append(value)
        with server(lambda *_: fixture({})) as (url, calls):
            for value in invalid:
                with self.subTest(value=value):
                    self.assertEqual(self.run_cli(url, "challenge", "--match", "m", "--target", "b", "--file", str(self.challenge_file(value)))[0], 1)
            self.assertEqual(calls, [])

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        with self.assertRaises(ValueError):
            client.load_json('{"title":"first","title":"second"}')
        with self.assertRaises(ValueError):
            client.load_json('{"seats":NaN}')

    def test_http_errors_are_errors_and_tokens_are_redacted(self):
        for status, code in [(401, "UNAUTHORIZED"), (403, "FORBIDDEN"), (409, "STALE_SNAPSHOT"), (503, "RUNNER_UNAVAILABLE")]:
            with self.subTest(status=status):
                with server(lambda *_: fixture({"error": {"code": code, "message": "echo " + TOKEN, "details": {}}}, status)) as (url, _):
                    result, output, diagnostic = self.run_cli(url, "match", "--id", "m")
                    self.assertEqual(result, 1)
                    self.assertEqual(output, "")
                    self.assertIn(f"HTTP {status} {code}", diagnostic)
                    self.assertIn("[redacted]", diagnostic)

    def test_header_is_required_and_body_mode_must_agree(self):
        responses = [(200, {}, {}), (200, {}, {"X-Arena-Mode": "unknown"}),
                     (200, {"mode": "live"}, {"X-Arena-Mode": "fixture"}),
                     (401, {"error": {"code": "UNAUTHORIZED"}}, {})]
        for response in responses:
            with self.subTest(response=response):
                with server(lambda *_: response) as (url, _):
                    code, output, diagnostic = self.run_cli(url, "match", "--id", "m")
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertIn("protocol error", diagnostic)
                    self.assertIn("unknown", diagnostic)

    def test_failed_verification_is_a_valid_terminal_job_response(self):
        job = {"status": "completed", "kind": "verification", "result": {"status": "failed", "failed_check_ids": ["BOOK-04"]}}
        with server(lambda *_: fixture(job)) as (url, _):
            code, output, _ = self.run_cli(url, "job", "--id", "j", "--wait")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), job)

    def test_wait_polls_actual_job_and_stops_on_error(self):
        def responder(method, path, body, count):
            return fixture({"job_id": "j", "status": "running" if count == 1 else "error", "error": {"code": "RUNNER_UNAVAILABLE"}})

        with server(responder) as (url, calls):
            code, output, _ = self.run_cli(url, "job", "--id", "j", "--wait", "--poll-interval", "0.001", "--timeout", "1")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["status"], "error")
            self.assertEqual(len(calls), 2)

    def test_total_job_timeout_has_distinct_exit_and_never_claims_success(self):
        with server(lambda *_: fixture({"status": "running"})) as (url, _):
            start = time.monotonic()
            code, output, diagnostic = self.run_cli(url, "job", "--id", "j", "--wait", "--poll-interval", "0.005", "--timeout", "0.04")
            elapsed = time.monotonic() - start
            self.assertEqual(code, 2)
            self.assertEqual(output, "")
            self.assertIn("outcome remains unknown", diagnostic)
            self.assertLess(elapsed, 0.3)

    def test_wait_deadline_bounds_an_individual_http_request(self):
        def responder(*args):
            time.sleep(0.15)
            return fixture({"status": "running"})

        with server(responder) as (url, _):
            start = time.monotonic()
            self.assertEqual(self.run_cli(url, "job", "--id", "j", "--wait", "--timeout", "0.025")[0], 2)
            self.assertLess(time.monotonic() - start, 0.2)

    def test_journal_failure_sends_nothing(self):
        self.state.write_text("not a directory")
        with server(lambda *_: fixture({})) as (url, calls):
            code, _, diagnostic = self.run_cli(url, "submit", "--match", "m", "--slot", "a", "--commit", "sha")
            self.assertEqual(code, 1)
            self.assertIn("no mutation was sent", diagnostic)
            self.assertEqual(calls, [])

    def test_invalid_uuid_and_operator_source_are_rejected(self):
        with server(lambda *_: fixture({})) as (url, calls):
            arguments = ["submit", "--match", "m", "--slot", "a", "--commit", "sha"]
            self.assertEqual(self.run_cli(url, *arguments, "--request-id", "not-a-uuid")[0], 1)
            self.assertEqual(self.run_cli(url, *arguments, "--source-kind", "operator_recorded")[0], 1)
            self.assertEqual(calls, [])

    def test_accidental_token_in_source_note_is_not_journaled_or_sent(self):
        with server(lambda *_: fixture({})) as (url, calls):
            code, _, diagnostic = self.run_cli(url, "submit", "--match", "m", "--slot", "a", "--commit", "sha", "--source-note", TOKEN)
            self.assertEqual(code, 1)
            self.assertIn("refusing to persist", diagnostic)
            self.assertEqual(calls, [])
            self.assertEqual(list(self.state.glob("*/*.json")), [])

    def test_reflected_token_with_json_escapes_is_redacted_as_valid_json(self):
        escaped_token = 'fixture-quote"and-backslash\\token'
        self.token_file.write_text(escaped_token)
        with server(lambda *_: fixture({"reflected": escaped_token})) as (url, _):
            code, output, _ = self.run_cli(url, "match", "--id", "m")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), {"reflected": "[redacted]"})
            self.assertEqual(self.run_cli(url, "submit", "--match", "m", "--slot", "a", "--commit", "sha", "--source-note", escaped_token)[0], 1)
            self.assertEqual(list(self.state.glob("*/*.json")), [])

    def test_malformed_or_truncated_json_response_is_an_error(self):
        responses = [(200, b"not json", {"X-Arena-Mode": "fixture"}),
                     (200, b"{}", {"X-Arena-Mode": "fixture", "Content-Length": "100"})]
        for response in responses:
            with self.subTest(response=response):
                with server(lambda *_: response) as (url, _):
                    code, output, diagnostic = self.run_cli(url, "match", "--id", "m")
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertTrue("protocol error" in diagnostic or "transport error" in diagnostic)

    def test_redirect_does_not_forward_the_credential(self):
        with server(lambda *_: (302, {"error": {"code": "REDIRECT", "message": "unexpected redirect"}},
                               {"X-Arena-Mode": "fixture", "Location": "/api/v1/credential-leak"})) as (url, calls):
            self.assertEqual(self.run_cli(url, "match", "--id", "m")[0], 1)
            self.assertEqual(len(calls), 1)

    def test_api_url_refuses_embedded_credentials_and_unrelated_paths(self):
        for url in ("https://user:secret@example.com", "file:///tmp/foo", "https://example.com/admin", "https://example.com/?secret=x"):
            with self.subTest(url=url):
                with self.assertRaises(client.ClientError):
                    client.normalize_api_url(url)


if __name__ == "__main__":
    unittest.main()
