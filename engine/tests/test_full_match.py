"""Sprint 3 end-to-end protocol tests using a deterministic, non-executing runner."""

import json
import subprocess
import uuid

from test_protocol import (
    FakeRunner, commit_candidate, create_match, get, post, rid, setup, source, submit,
)


API = "/api/v1"


class MatchRunner(FakeRunner):
    """Fake verifier keyed by submitted source bytes and scenario data."""

    digest = "b" * 64

    def verify(self, candidate, scenarios, include_isolation, cancel_event=None):
        self.calls.append((candidate, scenarios, include_isolation))
        if getattr(self, "fail_next", False):
            self.fail_next = False
            raise RuntimeError("synthetic transient transport failure")
        if hasattr(candidate, "read_bytes"):
            source_bytes = candidate.read_bytes()
        else:
            source_bytes = candidate if isinstance(candidate, bytes) else str(candidate).encode()
        marker = b"ARENA_BROKEN"
        failing = marker in source_bytes
        # The fake models a semantically impossible claimed outcome: available()
        # returns an integer, so bool is not a valid expected value here.
        challenge_case = (not include_isolation and len(scenarios) == 1
                          and scenarios[0].get("check_id") == "CHALLENGE")
        invalid_claim = any(
            step.get("op") == "available" and type(step.get("expected")) is bool
            for case in scenarios
            for step in case.get("scenario", case).get("steps", [])
        )
        failures = []
        if failing or invalid_claim:
            failures = ["CHALLENGE" if challenge_case else "BOOK-01"]
        count = len(scenarios) + int(include_isolation)
        return {"check_count": count, "passed_count": count - int(bool(failures)),
                "failed_check_ids": failures, "log": "deterministic fake result"}


def req(body):
    return {"request_id": rid(), "source": source(), **body}


def action(client, match_id, token, name, reason="protocol test"):
    return post(client, f"{API}/matches/{match_id}/actions",
                req({"action": name, "reason": reason}), token)


def decision(client, match_id, challenge_id, token, disposition, reason="meets cited requirement"):
    return post(client, f"{API}/matches/{match_id}/challenges/{challenge_id}/decision",
                req({"disposition": disposition, "reason": reason}), token)


def make_reviewing(tmp_path, *, broken_a=False, broken_b=False, rounds=1):
    client, app, settings, runner, tokens = setup(tmp_path, MatchRunner())
    match_id = create_match(client, tokens["operator"], max_repair_rounds=rounds)["match_id"]
    clean = "class BookingSystem:\n    def __init__(self, capacity): self.capacity=capacity\n"
    bad = clean + "    # ARENA_BROKEN\n"
    sha_a = commit_candidate(settings, "a", bad if broken_a else clean)
    sha_b = commit_candidate(settings, "b", bad if broken_b else clean)
    submit(client, match_id, "a", tokens["a"], sha_a)
    submit(client, match_id, "b", tokens["b"], sha_b)
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    assert action(client, match_id, tokens["operator"], "reveal").status_code == 200
    state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    return client, app, settings, runner, tokens, match_id, state


def report_challenge(client, match_id, slot, token, target, scenario=None):
    scenario = scenario or {"capacity": 3, "steps": [
        {"op": "book", "args": ["family", 2], "expected": True},
        {"op": "available", "args": [], "expected": 1},
    ]}
    response = post(client, f"{API}/matches/{match_id}/challenges", req({
        "target_candidate_id": target, "requirement_ids": ["BOOK-01"],
        "scenario": scenario, "title": "Capacity invariant",
    }), token)
    return response


def complete_reviews(client, match_id, state, tokens):
    for slot in ("a", "b"):
        target = state["slots"]["b" if slot == "a" else "a"]["candidate"]["candidate_id"]
        response = post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
                        req({"target_candidate_id": target}), tokens[slot])
        assert response.status_code == 200, response.text


def test_accepted_regression_changes_suite_and_stales_both_verifications(tmp_path):
    client, app, settings, runner, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    regression = {"capacity": 3, "steps": [
        {"op": "book", "args": ["family", 2], "expected": True},
        {"op": "available", "args": [], "expected": 1},
    ]}
    challenge = report_challenge(client, match_id, "b", tokens["b"],
                                 state["slots"]["a"]["candidate"]["candidate_id"], regression)
    assert challenge.status_code == 202, challenge.text
    assert app.state.engine.worker_once()
    challenge_id = challenge.json()["challenge_id"]
    assert decision(client, match_id, challenge_id, tokens["operator"], "accepted").status_code == 200
    changed = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert changed["suite_digest"] != state["suite_digest"]
    assert all(slot["candidate"]["verification"]["status"] == "stale"
               for slot in changed["slots"].values())
    assert all(slot["candidate"]["eligibility"] == "pending"
               for slot in changed["slots"].values())

    complete_reviews(client, match_id, changed, tokens)
    assert action(client, match_id, tokens["operator"], "start_repair").status_code == 200
    # Practice in repair runs the accepted regression but never changes candidate eligibility.
    initial_sha = state["slots"]["a"]["candidate"]["commit_sha"]
    practice = post(client, f"{API}/matches/{match_id}/practice", req({
        "slot": "a", "commit_sha": initial_sha,
    }), tokens["a"])
    assert practice.status_code == 202, practice.text
    assert app.state.engine.worker_once()
    practice_job = get(client, f"{API}/jobs/{practice.json()['job_id']}", tokens["a"]).json()
    assert practice_job["status"] == "completed"
    assert practice_job["result"]["check_count"] == len(app.state.engine.public) + 1
    assert any(case.get("scenario") == regression
               for candidate_path, checks, isolation in runner.calls
               if not isolation for case in checks)
    after_practice = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert all(slot["candidate"]["eligibility"] == "pending"
               for slot in after_practice["slots"].values())

    # The first repair verification stays queued until both current candidates exist.
    for slot in ("a", "b"):
        root = settings.state_dir / "workers" / slot / "worktree"
        subprocess.run(["git", "commit", "--allow-empty", "-m", "repair"], cwd=root,
                       check=True, capture_output=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                             capture_output=True, text=True).stdout.strip()
        submitted = submit(client, match_id, slot, tokens[slot], sha)
        assert submitted.status_code == 202
        if slot == "a":
            assert app.state.engine.worker_once() is False
            queued = get(client, f"{API}/jobs/{submitted.json()['job_id']}", tokens["operator"]).json()
            assert queued["status"] == "queued"
    assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    final_state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert final_state["phase"] == "decision"
    verify_calls = [(checks, include_isolation) for _, checks, include_isolation in runner.calls
                    if include_isolation and any(case.get("scenario") == regression for case in checks)]
    assert len(verify_calls) == 2
    assert all(len(checks) == len(app.state.engine.full) + 1 for checks, _ in verify_calls)
    assert all(any(case.get("scenario") == regression for case in checks) for checks, _ in verify_calls)


def test_pending_and_inconclusive_challenges_cannot_be_accepted_or_advanced(tmp_path):
    client, _, _, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    challenge = report_challenge(client, match_id, "b", tokens["b"],
                                 state["slots"]["a"]["candidate"]["candidate_id"])
    assert challenge.status_code == 202
    cid = challenge.json()["challenge_id"]
    assert decision(client, match_id, cid, tokens["operator"], "accepted").status_code == 409
    complete_reviews(client, match_id, state, tokens)
    assert action(client, match_id, tokens["operator"], "start_repair").status_code == 409
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 409


def test_wrong_expected_types_are_invalid_or_autorejected_and_boolean_fields_are_strict(tmp_path):
    client, app, _, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    malformed = {"capacity": 3, "steps": [
        {"op": "available", "args": [], "expected": True},
    ]}
    response = report_challenge(client, match_id, "b", tokens["b"], target, malformed)
    assert response.status_code in (202, 422)
    if response.status_code == 202:
        assert app.state.engine.worker_once()
        item = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()["challenges"][-1]
        assert item["disposition"] == "rejected"
    for selection in ("a", "neither"):
        bad = req({"selection": selection, "candidate_id": None,
                   "expected_evidence_key": None, "reason": "strict schema"})
        bad["request_id"] = str(uuid.uuid4())
        bad["selection"] = True
        response = post(client, f"{API}/matches/{match_id}/selection", bad, tokens["operator"])
        assert response.status_code == 422


def test_terminal_duplicate_reuses_challenge_but_inconclusive_retry_is_new_job(tmp_path):
    client, app, _, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    first = report_challenge(client, match_id, "b", tokens["b"], target)
    assert first.status_code == 202
    assert app.state.engine.worker_once()
    duplicate = report_challenge(client, match_id, "b", tokens["b"], target)
    assert duplicate.status_code == 202
    assert duplicate.json()["challenge_id"] == first.json()["challenge_id"]


def test_inconclusive_reproduction_can_be_retried_with_a_new_job(tmp_path):
    client, app, _, runner, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    runner.fail_next = True
    first = report_challenge(client, match_id, "b", tokens["b"], target)
    assert first.status_code == 202
    assert app.state.engine.worker_once()
    first_job = get(client, f"{API}/jobs/{first.json()['job_id']}", tokens["operator"]).json()
    assert first_job["status"] == "error"
    retry = report_challenge(client, match_id, "b", tokens["b"], target)
    assert retry.status_code == 202
    assert retry.json()["job_id"] != first.json()["job_id"]


def test_inconclusive_challenge_cannot_be_accepted_or_advanced(tmp_path):
    client, app, _, runner, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    runner.fail_next = True
    report = report_challenge(client, match_id, "b", tokens["b"], target)
    assert report.status_code == 202
    assert app.state.engine.worker_once()
    cid = report.json()["challenge_id"]
    challenge = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()["challenges"][0]
    assert challenge["reproduction"]["status"] == "inconclusive"
    assert decision(client, match_id, cid, tokens["operator"], "accepted").status_code == 409
    for slot in ("a", "b"):
        reviewed = post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
                        req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                             ["candidate"]["candidate_id"]}), tokens[slot])
        assert reviewed.status_code == 200
    assert action(client, match_id, tokens["operator"], "start_repair").status_code == 409
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 409
    rejected = decision(client, match_id, cid, tokens["operator"], "rejected",
                        reason="Unable to establish the claim because reproduction was inconclusive")
    assert rejected.status_code == 200
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200


def test_challenge_response_and_job_match_frozen_manifest_fields(tmp_path):
    client, app, _, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    response = report_challenge(client, match_id, "b", tokens["b"], target)
    assert response.status_code == 202
    assert set(response.json()) == {"challenge_id", "job_id"}
    assert app.state.engine.worker_once()
    match = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    challenge = match["challenges"][0]
    assert set(challenge) == set(app.state.engine.contract["types"]["Challenge"])
    assert set(challenge["reproduction"]) == set(app.state.engine.contract["types"]["Challenge"]["reproduction"])
    assert challenge["reproduction"]["reference_passed"] is True
    assert challenge["reproduction"]["target_failed_twice"] is True


def test_no_finding_reviews_finalize_to_decision_then_neither_is_honest(tmp_path):
    client, app, _, _, tokens, match_id, state = make_reviewing(tmp_path)
    for slot in ("a", "b"):
        result = post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
                      req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                           ["candidate"]["candidate_id"]}), tokens[slot])
        assert result.status_code == 200, result.text
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert state["phase"] == "decision"
    selected = post(client, f"{API}/matches/{match_id}/selection", req({
        "selection": "neither", "candidate_id": None, "expected_evidence_key": None,
        "reason": "Neither candidate is eligible",
    }), tokens["operator"])
    assert selected.status_code == 200
    outcome = selected.json()["outcome"]
    assert outcome["selection"] == "neither" and outcome["selected_candidate_id"] is None
    assert outcome["patch_artifact_id"] is None


def test_repairs_are_one_per_slot_and_auto_verify_current_full_suite(tmp_path):
    client, app, settings, _, tokens, match_id, state = make_reviewing(tmp_path, rounds=1)
    for slot in ("a", "b"):
        result = post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
                      req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                           ["candidate"]["candidate_id"]}), tokens[slot])
        assert result.status_code == 200
    assert action(client, match_id, tokens["operator"], "start_repair").status_code == 200
    # An unchanged, committed candidate is still a valid repair submission.
    for slot in ("a", "b"):
        root = settings.state_dir / "workers" / slot / "worktree"
        subprocess.run(["git", "commit", "--allow-empty", "-m", "unchanged repair"],
                       cwd=root, check=True, capture_output=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                             capture_output=True, text=True).stdout.strip()
        submitted = submit(client, match_id, slot, tokens[slot], sha)
        assert submitted.status_code == 202, submitted.text
        assert submit(client, match_id, slot, tokens[slot], sha).status_code == 409
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert state["repair_round"] == 1 and state["phase"] == "decision"


def test_selection_rejects_stale_key_old_candidate_ineligible_and_pending(tmp_path):
    client, app, settings, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    original_a = state["slots"]["a"]["candidate"]["candidate_id"]
    for slot in ("a", "b"):
        post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
             req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                  ["candidate"]["candidate_id"]}), tokens[slot])
    assert action(client, match_id, tokens["operator"], "start_repair").status_code == 200
    for slot in ("a", "b"):
        text = "class BookingSystem:\n    def __init__(self, capacity): self.capacity=capacity\n"
        if slot == "a":
            text += "    # ARENA_BROKEN\n"
        root = settings.state_dir / "workers" / slot / "worktree"
        (root / "src/booking.py").write_text(text)
        subprocess.run(["git", "add", "src/booking.py"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "repair candidate"], cwd=root,
                       check=True, capture_output=True)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                             capture_output=True, text=True).stdout.strip()
        assert submit(client, match_id, slot, tokens[slot], sha).status_code == 202
    assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    candidate = state["slots"]["a"]["candidate"]
    assert candidate["candidate_id"] != original_a
    assert candidate["revision"] == 2
    ek = candidate["verification"]["evidence_key"]
    select = lambda cid, key: post(client, f"{API}/matches/{match_id}/selection", req({
        "selection": "a", "candidate_id": cid, "expected_evidence_key": key,
        "reason": "verify selection guard",
    }), tokens["operator"])
    assert select(candidate["candidate_id"], dict(ek, suite_digest="0" * 64)).status_code == 409
    assert select(original_a, ek).status_code == 409
    assert candidate["eligibility"] == "ineligible"
    assert select(candidate["candidate_id"], candidate["verification"]["evidence_key"]).status_code == 409
    # Finalization starts full verification; selection cannot proceed with these jobs pending.
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200
    pending = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert pending["phase"] == "verifying"
    assert select(candidate["candidate_id"], candidate["verification"]["evidence_key"]).status_code == 409


def test_action_retry_does_not_consume_round_and_decision_finalize_recovers_same_candidates(tmp_path):
    client, app, _, _, tokens, match_id, state = make_reviewing(tmp_path, rounds=2)
    for slot in ("a", "b"):
        post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
             req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                  ["candidate"]["candidate_id"]}), tokens[slot])
    body = req({"action": "start_repair", "reason": "one round"})
    first = post(client, f"{API}/matches/{match_id}/actions", body, tokens["operator"])
    retry = post(client, f"{API}/matches/{match_id}/actions", body, tokens["operator"])
    assert first.json() == retry.json() and first.json()["repair_round"] == 1
    # Recover by finalizing from decision without replacing candidates or consuming another round.
    for slot in ("a", "b"):
        from test_protocol import commit_candidate as commit
        sha = commit(app.state.engine.settings, slot)
        submit(client, match_id, slot, tokens[slot], sha)
    app.state.engine.worker_once(); app.state.engine.worker_once()
    before = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    candidate_ids = [before["slots"][s]["candidate"]["candidate_id"] for s in ("a", "b")]
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200
    app.state.engine.worker_once(); app.state.engine.worker_once()
    after = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert after["repair_round"] == 1
    assert [after["slots"][s]["candidate"]["candidate_id"] for s in ("a", "b")] == candidate_ids


def test_both_bad_at_round_cap_can_select_neither_and_exports_no_patch(tmp_path):
    client, app, settings, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True, broken_b=True, rounds=2)
    for slot in ("a", "b"):
        post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete",
             req({"target_candidate_id": state["slots"]["b" if slot == "a" else "a"]
                  ["candidate"]["candidate_id"]}), tokens[slot])
    for expected_round in (1, 2):
        assert action(client, match_id, tokens["operator"], "start_repair").status_code == 200
        for slot in ("a", "b"):
            root = settings.state_dir / "workers" / slot / "worktree"
            subprocess.run(["git", "commit", "--allow-empty", "-m", f"round {expected_round}"],
                           cwd=root, check=True, capture_output=True)
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                                 capture_output=True, text=True).stdout.strip()
            assert submit(client, match_id, slot, tokens[slot], sha).status_code == 202
        assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200
    assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    decision_state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    assert decision_state["phase"] == "decision"
    outcome = post(client, f"{API}/matches/{match_id}/selection", req({
        "selection": "neither", "candidate_id": None, "expected_evidence_key": None,
        "reason": "Both failed the full suite",
    }), tokens["operator"])
    assert outcome.status_code == 200
    match = outcome.json()
    artifact = get(client, f"{API}/artifacts/{match['outcome']['evidence_artifact_id']}", tokens["operator"])
    assert artifact.status_code == 200
    evidence = json.loads(artifact.text)
    assert evidence["match"]["outcome"]["selection"] == "neither"
    assert evidence["match"]["outcome"]["patch_artifact_id"] is None
    assert match["outcome"]["patch_artifact_id"] is None


def test_common_evidence_excludes_private_practice_but_operator_keeps_access(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path, MatchRunner())
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha_a = commit_candidate(settings, "a")
    sha_b = commit_candidate(settings, "b")
    practice = post(client, f"{API}/matches/{match_id}/practice", req({
        "slot": "a", "commit_sha": sha_a,
    }), tokens["a"])
    assert practice.status_code == 202
    assert app.state.engine.worker_once()
    practice_id = practice.json()["job_id"]
    practice_job = get(client, f"{API}/jobs/{practice_id}", tokens["operator"]).json()
    practice_log_id = practice_job["result"]["log_artifact_id"]
    assert practice_job["status"] == "completed"
    assert get(client, f"{API}/artifacts/{practice_log_id}", tokens["operator"]).status_code == 200

    assert submit(client, match_id, "a", tokens["a"], sha_a).status_code == 202
    assert submit(client, match_id, "b", tokens["b"], sha_b).status_code == 202
    assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    assert action(client, match_id, tokens["operator"], "reveal").status_code == 200
    state = get(client, f"{API}/matches/{match_id}", tokens["operator"]).json()
    complete_reviews(client, match_id, state, tokens)
    assert action(client, match_id, tokens["operator"], "finalize").status_code == 200
    assert app.state.engine.worker_once(); assert app.state.engine.worker_once()
    selected = post(client, f"{API}/matches/{match_id}/selection", req({
        "selection": "neither", "candidate_id": None, "expected_evidence_key": None,
        "reason": "No selection for export privacy check",
    }), tokens["operator"])
    assert selected.status_code == 200
    evidence_id = selected.json()["outcome"]["evidence_artifact_id"]
    evidence = get(client, f"{API}/artifacts/{evidence_id}", tokens["operator"])
    assert evidence.status_code == 200
    assert practice_id not in evidence.text
    assert practice_log_id not in evidence.text
    # The export is shared evidence; private slot/operator access to the job remains intact.
    assert get(client, f"{API}/jobs/{practice_id}", tokens["operator"]).status_code == 200
    assert get(client, f"{API}/artifacts/{practice_log_id}", tokens["a"]).status_code == 200
