"""Executable CLI + shared fixture HTTP integration; never a live agent match."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("arena_shared_fixture", ROOT / "web/mock/server.py")
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


class FixtureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.token_file = self.directory / "slot.token"
        self.token_file.write_text("fixture-a")
        self.server = FIXTURE.create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def invoke(self, *arguments, expected_exit=0):
        completed = subprocess.run([
            sys.executable, str(ROOT / "switch_bridge/arena_client.py"),
            "--api-url", f"http://127.0.0.1:{self.server.server_address[1]}",
            "--token-file", str(self.token_file),
            "--state-dir", str(self.directory / "journal"),
            "--source-kind", "fixture", *arguments,
        ], capture_output=True, text=True, timeout=5)
        self.assertEqual(completed.returncode, expected_exit, completed.stderr)
        self.assertIn("mode=fixture", completed.stderr)
        if expected_exit == 0:
            return json.loads(completed.stdout)
        self.assertEqual(completed.stdout, "")
        return completed.stderr

    def test_assignment_practice_submission_and_job_obey_scoped_visibility(self):
        assignment = self.invoke("assignment", "--match", "fixture-building", "--slot", "a")
        self.assertTrue(assignment["workspace_path"].endswith("/a/worktree"))
        self.assertIsNone(assignment["review_path"])
        self.assertIsNone(assignment["target_candidate_id"])
        self.assertEqual(assignment["allowed_files"], ["src/booking.py"])
        self.assertEqual(assignment["provider_labels"], {"a": None, "b": None})

        practice = self.invoke("check", "--match", "fixture-building", "--slot", "a", "--commit", "a" * 40)
        job = self.invoke("job", "--id", practice["job_id"], "--wait", "--timeout", "2")
        self.assertEqual(job["kind"], "practice")
        self.assertEqual(job["status"], "completed")
        before = self.invoke("match", "--id", "fixture-building")
        self.assertIsNone(before["slots"]["a"]["candidate"], "Practice must not create an eligible candidate")

        submission = self.invoke("submit", "--match", "fixture-building", "--slot", "a", "--commit", "a" * 40)
        official = self.invoke("job", "--id", submission["job_id"], "--wait", "--timeout", "2")
        self.assertEqual(official["kind"], "verification")
        after = self.invoke("match", "--id", "fixture-building")
        self.assertEqual(after["slots"]["a"]["candidate"]["candidate_id"], submission["candidate_id"])
        self.assertIsNone(after["slots"]["b"]["candidate"])
        self.assertNotEqual(job["result"]["evidence_key"]["suite_digest"], official["result"]["evidence_key"]["suite_digest"])

    def test_exact_challenge_file_reproduction_and_review_completion(self):
        self.token_file.write_text("fixture-b")
        assignment = self.invoke("assignment", "--match", "fixture-reviewing", "--slot", "b")
        self.assertIsNotNone(assignment["review_path"])
        target = assignment["target_candidate_id"]
        challenge_file = self.directory / "challenge.json"
        challenge_file.write_text(json.dumps({
            "title": "Fixture: repeated cancellation preserves state",
            "requirement_ids": ["BOOK-03", "BOOK-04"],
            "scenario": FIXTURE.SPEC["challenge_example"],
        }))
        challenge = self.invoke("challenge", "--match", "fixture-reviewing", "--target", target, "--file", str(challenge_file))
        job = self.invoke("job", "--id", challenge["job_id"], "--wait", "--timeout", "2")
        self.assertEqual(job["kind"], "challenge")
        self.assertEqual(job["result"]["status"], "reproduced")
        self.assertTrue(job["result"]["reference_passed"])
        self.assertTrue(job["result"]["target_failed_twice"])
        self.assertIn("FIXTURE REPLAY", job["result"]["actual_summary"])
        reviewed = self.invoke("review-done", "--match", "fixture-reviewing", "--slot", "b", "--target", target)
        self.assertTrue(reviewed["slots"]["b"]["review_complete"])
        self.assertEqual(reviewed["challenges"][0]["disposition"], "pending", "Agent completion must not adjudicate the human decision")

    def test_scoped_forbidden_and_server_validation_keep_fixture_error_mode(self):
        diagnostic = self.invoke("assignment", "--match", "fixture-building", "--slot", "b", expected_exit=1)
        self.assertIn("HTTP 403 FORBIDDEN", diagnostic)
        diagnostic = self.invoke("check", "--match", "fixture-building", "--slot", "a", "--commit", "short-sha", expected_exit=1)
        self.assertIn("HTTP 422 INVALID_INPUT", diagnostic)

    def test_stale_review_is_a_real_http_conflict(self):
        diagnostic = self.invoke("review-done", "--match", "fixture-reviewing", "--slot", "a", "--target", "old-snapshot", expected_exit=1)
        self.assertIn("HTTP 409 STALE_SNAPSHOT", diagnostic)

    def test_runner_error_job_is_valid_response_with_unknown_eligibility(self):
        match = self.invoke("match", "--id", "fixture-error")
        self.assertEqual(match["slots"]["a"]["candidate"]["eligibility"], "unknown")
        job_id = match["slots"]["a"]["candidate"]["verification"]["job_id"]
        job = self.invoke("job", "--id", job_id, "--wait", "--timeout", "2")
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["error"]["code"], "RUNNER_UNAVAILABLE")
        self.assertEqual(job["result"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
