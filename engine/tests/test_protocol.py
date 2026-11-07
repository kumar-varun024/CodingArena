"""Sprint 2 HTTP protocol and visibility tests (runner is deliberately fake)."""

import json
import sqlite3
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arena_engine.api import create_app
from arena_engine.runtime import DEFAULT_IMAGE, Settings
from arena_engine.contract import load_contract
from arena_engine.workspaces import initialize


class FakeRunner:
    digest = "a" * 64

    def __init__(self, available=True, raises=False, failed_id=None):
        self.is_available = available
        self.raises = raises
        self.failed_id = failed_id
        self.calls = []

    def available(self):
        return self.is_available

    def verify(self, source, scenarios, include_isolation, cancel_event=None):
        self.calls.append((source, scenarios, include_isolation))
        if self.raises:
            raise RuntimeError("synthetic runner failure")
        count = len(scenarios) + int(include_isolation)
        failed = [self.failed_id] if self.failed_id else []
        return {"check_count": count, "passed_count": count - len(failed),
                "failed_check_ids": failed, "log": "fake pass"}

    def cancel(self):
        pass


def source(kind="fixture"):
    return {"kind": kind, "room_id": None, "message_id": None, "note": "protocol test"}


def rid():
    return str(uuid.uuid4())


def setup(tmp_path, runner=None):
    settings = Settings(tmp_path / "state", DEFAULT_IMAGE)
    initialize(settings)
    runner = runner or FakeRunner()
    app = create_app(settings=settings, runner=runner, start_worker=False)
    client = TestClient(app)
    state = settings.state_dir
    tokens = {
        "operator": (state / "auth/operator.token").read_text().strip(),
        "a": (state / "workers/a/.arena/slot.token").read_text().strip(),
        "b": (state / "workers/b/.arena/slot.token").read_text().strip(),
    }
    return client, app, settings, runner, tokens


def post(client, path, body, token):
    return client.post(path, json=body, headers={"Authorization": "Bearer " + token})


def get(client, path, token):
    return client.get(path, headers={"Authorization": "Bearer " + token})


def create_match(client, operator, request_id=None, **extra):
    body = {
        "request_id": request_id or rid(), "source": source(), "task_id": "booking-v1",
        "candidate_budget_minutes": 10, "max_repair_rounds": 1,
        "provider_labels": {"a": "Alpha", "b": "Beta"},
    }
    body.update(extra)
    response = post(client, "/api/v1/matches", body, operator)
    assert response.status_code == 201, response.text
    return response.json()


def commit_candidate(settings, slot, text=None):
    root = settings.state_dir / "workers" / slot / "worktree"
    source_path = root / "src/booking.py"
    if text is None:
        text = "class BookingSystem:\n    def __init__(self, capacity): self.capacity, self.items = capacity, {}\n    def book(self, booking_id, seats): return False\n    def cancel(self, booking_id): return False\n    def available(self): return self.capacity\n    def reservations(self): return {}\n"
    source_path.write_text(text)
    subprocess.run(["git", "add", "src/booking.py"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "candidate"], cwd=root, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def submit(client, match_id, slot, token, commit, request_id=None):
    return post(client, f"/api/v1/matches/{match_id}/submissions", {
        "request_id": request_id or rid(), "source": source(), "slot": slot,
        "commit_sha": commit,
    }, token)


def test_create_and_submit_are_idempotent_and_reject_body_conflicts(tmp_path):
    client, _, settings, _, tokens = setup(tmp_path)
    create_id = rid()
    body = {"request_id": create_id, "source": source(), "task_id": "booking-v1",
            "candidate_budget_minutes": 10, "max_repair_rounds": 1,
            "provider_labels": {"a": "Alpha", "b": "Beta"}}
    first = post(client, "/api/v1/matches", body, tokens["operator"])
    restarted = TestClient(create_app(settings=settings, runner=FakeRunner(), start_worker=False))
    retry = post(restarted, "/api/v1/matches", body, tokens["operator"])
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json() == first.json()
    changed = dict(body, candidate_budget_minutes=9)
    assert post(client, "/api/v1/matches", changed, tokens["operator"]).status_code == 409

    match_id = first.json()["match_id"]
    sha = commit_candidate(settings, "a")
    submit_id = rid()
    submission = {"request_id": submit_id, "source": source(), "slot": "a", "commit_sha": sha}
    one = post(client, f"/api/v1/matches/{match_id}/submissions", submission, tokens["a"])
    restarted = TestClient(create_app(settings=settings, runner=FakeRunner(), start_worker=False))
    two = post(restarted, f"/api/v1/matches/{match_id}/submissions", submission, tokens["a"])
    assert one.status_code == 202 and two.status_code == 202
    assert two.json() == one.json()
    assert len(get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()["jobs"]) == 1
    assert post(client, f"/api/v1/matches/{match_id}/submissions",
                dict(submission, commit_sha="0" * 40), tokens["a"]).status_code == 409


def test_auth_slot_ownership_and_strict_request_shape(tmp_path):
    client, _, settings, _, tokens = setup(tmp_path)
    match = create_match(client, tokens["operator"])
    match_id = match["match_id"]
    sha = commit_candidate(settings, "a")
    assert get(client, f"/api/v1/matches/{match_id}", "not-a-token").status_code == 401
    assert submit(client, match_id, "a", tokens["b"], sha).status_code == 403
    assert submit(client, match_id, "b", tokens["a"], sha).status_code == 403
    invalid = {"request_id": rid(), "source": source(), "slot": "a", "commit_sha": sha,
               "result": {"passed": True}, "eligibility": "eligible"}
    response = post(client, f"/api/v1/matches/{match_id}/submissions", invalid, tokens["a"])
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert client.post("/api/v1/matches", content="{", headers={
        "Authorization": "Bearer " + tokens["operator"], "Content-Type": "application/json",
    }).status_code == 400


def test_slot_responses_do_not_include_candidate_or_hidden_test_source(tmp_path):
    client, app, _, _, tokens = setup(tmp_path)
    match_id = create_match(client, tokens["operator"])["match_id"]
    text = "class BookingSystem:\n    def __init__(self, capacity): self.capacity = capacity\n"
    sha_a = commit_candidate(app.state.engine.settings, "a", text)
    sha_b = commit_candidate(app.state.engine.settings, "b", text.replace("self.capacity", "self.other"))
    submit(client, match_id, "a", tokens["a"], sha_a)
    submit(client, match_id, "b", tokens["b"], sha_b)
    response = json.dumps(get(client, f"/api/v1/matches/{match_id}", tokens["a"]).json())
    assert text not in response
    assert "HELD-BOOK-02" not in response
    assert "reference" not in response.lower()


def test_private_until_reveal_then_review_copy_and_terminal_verification(tmp_path):
    client, app, settings, runner, tokens = setup(tmp_path)
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha_a, sha_b = commit_candidate(settings, "a"), commit_candidate(settings, "b")
    job_a = submit(client, match_id, "a", tokens["a"], sha_a).json()["job_id"]
    job_b = submit(client, match_id, "b", tokens["b"], sha_b).json()["job_id"]
    assert app.state.engine.worker_once() is True
    assert app.state.engine.worker_once() is True
    before = get(client, f"/api/v1/matches/{match_id}", tokens["a"]).json()
    assert before["slots"]["b"].get("candidate") is None
    assert all(job.get("slot") in (None, "a") for job in before.get("jobs", []))
    assert get(client, f"/api/v1/jobs/{job_b}", tokens["a"]).status_code == 403
    b_log = get(client, f"/api/v1/jobs/{job_b}", tokens["operator"]).json()["result"]["log_artifact_id"]
    assert get(client, f"/api/v1/artifacts/{b_log}", tokens["a"]).status_code == 403
    assert get(client, f"/api/v1/artifacts/{b_log}", tokens["b"]).status_code == 200
    assert get(client, f"/api/v1/matches/{match_id}/assignments/b", tokens["a"]).status_code == 403
    events = get(client, f"/api/v1/matches/{match_id}/events", tokens["a"]).json()
    assert "slot_b" not in json.dumps(events)
    assert job_b not in json.dumps(events)
    reveal = post(client, f"/api/v1/matches/{match_id}/actions",
                  {"request_id": rid(), "source": source(), "action": "reveal", "reason": "both submitted"},
                  tokens["operator"])
    assert reveal.status_code == 200, reveal.text
    assert get(client, f"/api/v1/jobs/{job_a}", tokens["a"]).json()["status"] == "completed"
    assert get(client, f"/api/v1/jobs/{job_b}", tokens["a"]).status_code == 200
    log = get(client, f"/api/v1/artifacts/{b_log}", tokens["a"])
    assert log.status_code == 200
    assert log.headers["content-type"].startswith("text/plain")
    assert log.headers["content-disposition"].startswith("attachment;")
    assignment = get(client, f"/api/v1/matches/{match_id}/assignments/a", tokens["a"])
    assert assignment.status_code == 200
    review_path = assignment.json().get("review_path")
    assert review_path and (Path(review_path) / "src/booking.py").is_file()
    assert Path(review_path).resolve().is_relative_to((settings.state_dir / "workers/a").resolve())
    assert runner.calls and all(call[0] != "" for call in runner.calls)


def test_cancel_running_job_cannot_be_overwritten_by_late_pass(tmp_path):
    import threading
    started, release = threading.Event(), threading.Event()

    class SlowRunner(FakeRunner):
        def verify(self, *args, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            return super().verify(*args, **kwargs)

    client, app, settings, _, tokens = setup(tmp_path, SlowRunner())
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha = commit_candidate(settings, "a")
    job_id = submit(client, match_id, "a", tokens["a"], sha).json()["job_id"]
    worker = threading.Thread(target=app.state.engine.worker_once)
    worker.start()
    try:
        assert started.wait(timeout=5)
        cancelled = post(client, f"/api/v1/matches/{match_id}/actions", {
            "request_id": rid(), "source": source(), "action": "cancel", "reason": "during execution",
        }, tokens["operator"])
        assert cancelled.status_code == 200
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert get(client, f"/api/v1/jobs/{job_id}", tokens["operator"]).json()["status"] == "error"
    candidate = get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()["slots"]["a"]["candidate"]
    assert candidate["verification"]["status"] == "error"
    assert candidate["eligibility"] == "unknown"


def test_practice_does_not_change_candidate_or_eligibility(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path)
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha = commit_candidate(settings, "a")
    candidate = submit(client, match_id, "a", tokens["a"], sha).json()
    assert app.state.engine.worker_once() is True
    before = get(client, f"/api/v1/matches/{match_id}", tokens["a"]).json()["slots"]["a"]["candidate"]
    practice_body = {"request_id": rid(), "source": source(), "slot": "a", "commit_sha": sha}
    practiced = post(client, f"/api/v1/matches/{match_id}/practice", practice_body, tokens["a"])
    assert practiced.status_code == 202, practiced.text
    assert app.state.engine.worker_once() is True
    after = get(client, f"/api/v1/matches/{match_id}", tokens["a"]).json()["slots"]["a"]["candidate"]
    assert after["candidate_id"] == before["candidate_id"]
    assert after["verification"] == before["verification"]
    assert after["eligibility"] == before["eligibility"] == "pending"
    practice_job = get(client, f"/api/v1/jobs/{practiced.json()['job_id']}", tokens["a"]).json()
    assert practice_job["kind"] == "practice"
    assert after["eligibility"] == "pending"
    assert candidate["candidate_id"] == after["candidate_id"]


def test_unavailable_runner_and_runner_exception_are_not_success(tmp_path):
    client, _, settings, runner, tokens = setup(tmp_path, FakeRunner(available=False))
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha = commit_candidate(settings, "a")
    request_id = rid()
    response = submit(client, match_id, "a", tokens["a"], sha, request_id=request_id)
    assert response.status_code == 503
    runner.is_available = True
    assert submit(client, match_id, "a", tokens["a"], sha, request_id=request_id).json() == response.json()
    conflict = submit(client, match_id, "a", tokens["a"], "0" * 40, request_id=request_id)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    client, app, _, _, tokens = setup(tmp_path / "second", FakeRunner(raises=True))
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha_a, sha_b = commit_candidate(Settings(tmp_path / "second" / "state", DEFAULT_IMAGE), "a"), None
    # Setup already provisioned the workspaces; create the second contender there too.
    sha_b = commit_candidate(Settings(tmp_path / "second" / "state", DEFAULT_IMAGE), "b")
    ja = submit(client, match_id, "a", tokens["a"], sha_a).json()["job_id"]
    jb = submit(client, match_id, "b", tokens["b"], sha_b).json()["job_id"]
    assert app.state.engine.worker_once() is True
    assert app.state.engine.worker_once() is True
    assert get(client, f"/api/v1/jobs/{ja}", tokens["operator"]).json()["status"] == "error"
    assert get(client, f"/api/v1/jobs/{jb}", tokens["operator"]).json()["status"] == "error"
    state = get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()
    assert all(slot["candidate"]["eligibility"] == "unknown" for slot in state["slots"].values())


def test_restart_converts_interrupted_running_job_to_error(tmp_path):
    client, _, settings, runner, tokens = setup(tmp_path)
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha = commit_candidate(settings, "a")
    job_id = submit(client, match_id, "a", tokens["a"], sha).json()["job_id"]
    db_path = settings.state_dir / "arena.sqlite3"
    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT data FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        job = json.loads(row[0])
        job["status"] = "running"
        db.execute("UPDATE jobs SET status='running', data=? WHERE job_id=?", (json.dumps(job), job_id))
        match_row = db.execute("SELECT data FROM matches WHERE match_id=?", (match_id,)).fetchone()
        match = json.loads(match_row[0])
        match["slots"]["a"]["candidate"]["verification"]["status"] = "running"
        db.execute("UPDATE matches SET data=? WHERE match_id=?", (json.dumps(match), match_id))

    restarted = create_app(settings=settings, runner=runner, start_worker=False)
    recovered = TestClient(restarted)
    assert get(recovered, f"/api/v1/jobs/{job_id}", tokens["operator"]).json()["status"] == "error"
    match = get(recovered, f"/api/v1/matches/{match_id}", tokens["operator"]).json()
    assert match["slots"]["a"]["candidate"]["verification"]["status"] == "error"
    assert match["slots"]["a"]["candidate"]["eligibility"] == "unknown"


def test_cancel_fails_queued_work_and_is_idempotent(tmp_path):
    client, _, settings, _, tokens = setup(tmp_path)
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha = commit_candidate(settings, "a")
    job_id = submit(client, match_id, "a", tokens["a"], sha).json()["job_id"]
    body = {"request_id": rid(), "source": source(), "action": "cancel", "reason": "stop run"}
    cancelled = post(client, f"/api/v1/matches/{match_id}/actions", body, tokens["operator"])
    events_after = get(client, f"/api/v1/matches/{match_id}/events", tokens["operator"]).json()
    duplicate = post(client, f"/api/v1/matches/{match_id}/actions", body, tokens["operator"])
    events_retry = get(client, f"/api/v1/matches/{match_id}/events", tokens["operator"]).json()
    assert cancelled.status_code == 200 and duplicate.status_code == 200
    assert duplicate.json() == cancelled.json()
    assert events_retry == events_after
    assert get(client, f"/api/v1/jobs/{job_id}", tokens["operator"]).json()["status"] == "error"
    state = get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()
    assert state["slots"]["a"]["candidate"]["eligibility"] == "unknown"
    after_cancel = post(client, f"/api/v1/matches/{match_id}/practice", {
        "request_id": rid(), "source": source(), "slot": "a", "commit_sha": sha,
    }, tokens["a"])
    assert after_cancel.status_code == 409


def test_reveal_requires_terminal_jobs_but_accepts_failed_verification(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path, FakeRunner(failed_id="BOOK-01"))
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha_a, sha_b = commit_candidate(settings, "a"), commit_candidate(settings, "b")
    submit(client, match_id, "a", tokens["a"], sha_a)
    submit(client, match_id, "b", tokens["b"], sha_b)
    action = lambda: post(client, f"/api/v1/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "reveal", "reason": "initial checks done",
    }, tokens["operator"])
    assert action().status_code == 409
    assert app.state.engine.worker_once() is True
    assert app.state.engine.worker_once() is True
    match = get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()
    assert match["slots"]["a"]["candidate"]["verification"]["status"] == "failed"
    assert match["slots"]["a"]["candidate"]["eligibility"] == "ineligible"
    result = action()
    assert result.status_code == 200, result.text
    assert result.json()["phase"] == "reviewing"


def test_manifest_field_sets_for_protocol_responses(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path)
    contract_types = load_contract()["types"]
    match_id = create_match(client, tokens["operator"])["match_id"]
    sha_a, sha_b = commit_candidate(settings, "a"), commit_candidate(settings, "b")
    submit(client, match_id, "a", tokens["a"], sha_a)
    submit(client, match_id, "b", tokens["b"], sha_b)
    app.state.engine.worker_once()
    app.state.engine.worker_once()
    post(client, f"/api/v1/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "reveal", "reason": "checks done",
    }, tokens["operator"])
    match = get(client, f"/api/v1/matches/{match_id}", tokens["operator"]).json()
    assert set(match) == set(contract_types["Match"])
    candidate = match["slots"]["a"]["candidate"]
    assert set(candidate) == set(contract_types["Candidate"])
    assert set(candidate["verification"]) == set(contract_types["Verification"])
    job_id = candidate["verification"]["job_id"]
    job = get(client, f"/api/v1/jobs/{job_id}", tokens["operator"]).json()
    assert set(job) == set(contract_types["Job"])
    assignment = get(client, f"/api/v1/matches/{match_id}/assignments/a", tokens["a"]).json()
    assert set(assignment) == set(contract_types["Assignment"])
