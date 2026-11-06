"""HTTP-level checks for the explicitly synthetic contract fixture service."""

import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

spec = importlib.util.spec_from_file_location("arena_fixture_server", Path(__file__).with_name("server.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

SOURCE = {"kind": "fixture", "room_id": None, "message_id": None, "note": "Automated fixture test"}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = fixture.create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body=None, token="fixture-operator"):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(self.base + path, json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            content = response.read().decode()
            result = json.loads(content) if response.headers.get_content_type() == "application/json" else content
            self.assertEqual(response.headers["X-Arena-Mode"], "fixture")
            return response.status, result, response.headers

    def mutate(self, path, token="fixture-operator", **body):
        return self.request(path, {"request_id": str(uuid4()), "source": SOURCE, **body}, token)

    def test_health_auth_errors_and_modes_keep_contract_bodies(self):
        status, health, _ = self.request("/health", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(health["api_version"], "1.1")
        status, error, _ = self.request("/matches/fixture-building", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(set(error), {"error"})
        status, assignment, _ = self.request("/matches/fixture-building/assignments/a", token="fixture-a")
        self.assertEqual(status, 200)
        self.assertNotIn("mode", assignment)
        self.assertEqual(assignment["provider_labels"], {"a": None, "b": None})
        self.assertIsNone(assignment["review_path"])
        self.assertEqual(self.request("/matches/fixture-building/assignments/b", token="fixture-a")[0], 403)

    def test_before_reveal_projects_matches_events_jobs_and_artifacts(self):
        status, own, _ = self.mutate("/matches/fixture-building/submissions", "fixture-a", slot="a", commit_sha="a" * 40)
        self.assertEqual(status, 202)
        self.assertEqual(set(own), {"candidate_id", "job_id", "tree_digest"})
        status, rival, _ = self.mutate("/matches/fixture-building/submissions", "fixture-b", slot="b", commit_sha="b" * 40)
        self.assertEqual(status, 202)
        status, view, _ = self.request("/matches/fixture-building", token="fixture-a")
        self.assertIsNone(view["slots"]["b"]["candidate"])
        self.assertEqual([job["job_id"] for job in view["jobs"]], [own["job_id"]])
        self.assertEqual(self.request("/jobs/" + rival["job_id"], token="fixture-a")[0], 403)
        _, job, _ = self.request("/jobs/" + rival["job_id"])
        log = job["result"]["log_artifact_id"]
        self.assertEqual(self.request("/artifacts/" + log, token="fixture-a")[0], 403)
        _, events, _ = self.request("/matches/fixture-building/events?after=0", token="fixture-a")
        self.assertNotIn(rival["candidate_id"], json.dumps(events))
        self.assertEqual(self.mutate("/matches/fixture-building/actions", action="reveal", reason="Fixture reveal")[0], 200)
        self.assertEqual(self.request("/jobs/" + rival["job_id"], token="fixture-a")[0], 200)
        status, content, headers = self.request("/artifacts/" + log, token="fixture-a")
        self.assertEqual(status, 200)
        self.assertIn("FIXTURE REPLAY", content)
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_request_id_replay_and_conflict_even_after_transition(self):
        body = {"request_id": str(uuid4()), "source": SOURCE, "selection": "neither", "candidate_id": None, "expected_evidence_key": None, "reason": "Both fixture candidates fail"}
        first = self.request("/matches/fixture-neither/selection", body)
        self.assertEqual(first[0], 200)
        self.assertEqual(self.request("/matches/fixture-neither/selection", body)[:2], first[:2])
        body["reason"] = "Changed text"
        status, error, _ = self.request("/matches/fixture-neither/selection", body)
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_selection_rejects_stale_pending_and_ineligible_then_allows_current(self):
        for ident, slot in (("fixture-stale", "a"), ("fixture-neither", "a"), ("fixture-error", "a")):
            _, match, _ = self.request("/matches/" + ident)
            candidate = match["slots"][slot]["candidate"]
            status, error, _ = self.mutate(f"/matches/{ident}/selection", selection=slot, candidate_id=candidate["candidate_id"], expected_evidence_key=candidate["verification"]["evidence_key"], reason="Fixture selection attempt")
            self.assertEqual(status, 409)
            self.assertEqual(error["error"]["code"], "STALE_SNAPSHOT")
            if ident == "fixture-stale":
                _, refreshed, _ = self.request("/matches/fixture-stale")
                self.assertEqual(refreshed["slots"]["a"]["candidate"]["verification"]["status"], "stale")
                self.assertEqual(refreshed["slots"]["a"]["candidate"]["eligibility"], "pending")
        self.assertEqual(self.mutate("/matches/fixture-pending/selection", selection="neither", candidate_id=None, expected_evidence_key=None, reason="Cannot finish review yet")[0], 409)
        _, match, _ = self.request("/matches/fixture-decision")
        candidate = match["slots"]["a"]["candidate"]
        status, selected, _ = self.mutate("/matches/fixture-decision/selection", selection="a", candidate_id=candidate["candidate_id"], expected_evidence_key=candidate["verification"]["evidence_key"], reason="Fixture acceptance")
        self.assertEqual(status, 200)
        self.assertEqual(selected["phase"], "complete")
        self.assertEqual(selected["outcome"]["selected_candidate_id"], candidate["candidate_id"])
        status, evidence, _ = self.request("/artifacts/" + selected["outcome"]["evidence_artifact_id"])
        self.assertEqual(status, 200)
        self.assertEqual(evidence["kind"], "fixture_replay")
        self.assertNotIn("mode", evidence)
        status, patch, _ = self.request("/artifacts/" + selected["outcome"]["patch_artifact_id"])
        self.assertEqual(status, 200)
        self.assertIn("no executable selected patch", patch)

    def test_neither_keeps_patch_absent(self):
        status, match, _ = self.mutate("/matches/fixture-neither/selection", selection="neither", candidate_id=None, expected_evidence_key=None, reason="Neither passes the fixture checks")
        self.assertEqual(status, 200)
        self.assertIsNone(match["outcome"]["patch_artifact_id"])
        self.assertIsNone(match["outcome"]["selected_candidate_id"])

    def test_acceptance_invalidates_both_and_full_repair_refreshes(self):
        _, match, _ = self.request("/matches/fixture-pending")
        challenge = match["challenges"][0]
        status, match, _ = self.mutate(f"/matches/fixture-pending/challenges/{challenge['challenge_id']}/decision", disposition="accepted", reason="BOOK-04 accepted fixture replay")
        self.assertEqual(status, 200)
        self.assertTrue(all(state["candidate"]["verification"]["status"] == "stale" for state in match["slots"].values()))
        self.assertEqual(self.mutate("/matches/fixture-pending/actions", action="start_repair", reason="Reviews are not complete yet")[0], 409)
        for slot, other in (("a", "b"), ("b", "a")):
            self.assertEqual(self.mutate(f"/matches/fixture-pending/reviews/{slot}/complete", "fixture-" + slot, target_candidate_id=match["slots"][other]["candidate"]["candidate_id"])[0], 200)
        self.assertEqual(self.mutate("/matches/fixture-pending/actions", action="start_repair", reason="Repair accepted fixture regression")[0], 200)
        for slot in ("a", "b"):
            self.assertEqual(self.mutate("/matches/fixture-pending/submissions", "fixture-" + slot, slot=slot, commit_sha=slot * 40)[0], 202)
        _, repaired, _ = self.request("/matches/fixture-pending")
        self.assertEqual(repaired["phase"], "decision")
        self.assertTrue(all(state["candidate"]["eligibility"] == "eligible" for state in repaired["slots"].values()))

    def test_practice_is_not_candidate_verification(self):
        _, before, _ = self.request("/matches/fixture-repair")
        status, response, _ = self.mutate("/matches/fixture-repair/practice", "fixture-a", slot="a", commit_sha="c" * 40)
        self.assertEqual(status, 202)
        _, job, _ = self.request("/jobs/" + response["job_id"], token="fixture-a")
        self.assertEqual(job["kind"], "practice")
        _, after, _ = self.request("/matches/fixture-repair")
        self.assertEqual(before["slots"]["a"]["candidate"], after["slots"]["a"]["candidate"])
        self.assertNotEqual(job["result"]["evidence_key"]["suite_digest"], after["suite_digest"])

    def test_challenge_is_bounded_and_only_replays_recorded_scenario(self):
        _, match, _ = self.request("/matches/fixture-reviewing")
        target = match["slots"]["a"]["candidate"]["candidate_id"]
        body = {"target_candidate_id": target, "title": "Recorded cancellation scenario", "requirement_ids": ["BOOK-04"], "scenario": fixture.SPEC["challenge_example"]}
        status, response, _ = self.mutate("/matches/fixture-reviewing/challenges", "fixture-b", **body)
        self.assertEqual(status, 202)
        _, job, _ = self.request("/jobs/" + response["job_id"])
        self.assertEqual(job["result"]["status"], "reproduced")
        self.assertIn("FIXTURE REPLAY", job["result"]["actual_summary"])
        self.assertEqual(self.mutate("/matches/fixture-reviewing/challenges", "fixture-b", **body)[1], response)
        body["scenario"] = {"capacity": 2, "steps": [{"op": "book", "args": [None, False], "expected": False}, {"op": "available", "args": [], "expected": 2}]}
        status, response, _ = self.mutate("/matches/fixture-reviewing/challenges", "fixture-b", **body)
        self.assertEqual(status, 202)
        self.assertEqual(self.request("/jobs/" + response["job_id"])[1]["result"]["status"], "inconclusive")
        body["scenario"]["capacity"] = True
        self.assertEqual(self.mutate("/matches/fixture-reviewing/challenges", "fixture-b", **body)[0], 422)

    def test_created_match_labels_and_single_created_active_match(self):
        body = {"task_id": "booking-v1", "provider_labels": {"a": "Known demo setting", "b": None}, "max_repair_rounds": 1, "candidate_budget_minutes": 10}
        status, match, _ = self.mutate("/matches", **body)
        self.assertEqual(status, 201)
        self.assertEqual(match["provider_labels"], body["provider_labels"])
        self.assertEqual(self.request(f"/matches/{match['match_id']}/assignments/a", token="fixture-a")[1]["provider_labels"], body["provider_labels"])
        self.assertEqual(self.mutate("/matches", **body)[0], 409)
        self.assertEqual(self.mutate("/matches", "fixture-a", **body)[0], 403)


class PersistenceTests(unittest.TestCase):
    def test_optional_fixture_journal_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture-state.json"
            store = fixture.FixtureStore(path)
            request = {"request_id": str(uuid4()), "source": SOURCE, "selection": "neither", "candidate_id": None, "expected_evidence_key": None, "reason": "Neither fixture passes"}
            first = store.dispatch("POST", "/api/v1/matches/fixture-neither/selection", {}, "operator", request)
            reopened = fixture.FixtureStore(path)
            self.assertEqual(reopened.dispatch("POST", "/api/v1/matches/fixture-neither/selection", {}, "operator", request), first)


if __name__ == "__main__":
    unittest.main()
