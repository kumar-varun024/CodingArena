"""Focused regressions for the additive 1.1 public interface."""

import hashlib
import json

from fastapi.testclient import TestClient

from arena_engine.api import create_app
from test_protocol import commit_candidate, create_match, get, post, rid, setup, source, submit


API = "/api/v1"
V11_SHA256 = "c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f"
V10_SHA256 = "3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80"


def test_contract_v11_is_additive_and_v10_manifest_stays_frozen():
    from arena_engine.contract import ROOT, canonical_bytes, load_contract

    v10 = json.loads((ROOT / "contracts/arena-v1.json").read_text())
    assert hashlib.sha256(canonical_bytes(v10)).hexdigest() == V10_SHA256
    v11_path = ROOT / "contracts/arena-v1.1.json"
    v11 = json.loads(v11_path.read_text())
    assert hashlib.sha256(canonical_bytes(v11)).hexdigest() == V11_SHA256
    assert load_contract() == v11


def test_provider_labels_accept_null_but_reject_empty_and_wrong_types(tmp_path):
    client, _, _, _, tokens = setup(tmp_path)
    for labels in ({"a": "Team A", "b": "Team B"}, {"a": None, "b": "Team B"},
                   {"a": "Team A", "b": None}, {"a": None, "b": None}):
        body = {"request_id": rid(), "source": source(), "task_id": "booking-v1",
                "candidate_budget_minutes": 10, "max_repair_rounds": 1,
                "provider_labels": labels}
        response = post(client, f"{API}/matches", body, tokens["operator"])
        assert response.status_code == 201, response.text
        # Complete/cancel before opening the next match.
        stopped = post(client, f"{API}/matches/{response.json()['match_id']}/actions", {
            "request_id": rid(), "source": source(), "action": "cancel", "reason": "test",
        }, tokens["operator"])
        assert stopped.status_code == 200
    for labels in ({"a": "", "b": "Team B"}, {"a": "  ", "b": None}, {"a": 1, "b": "Team B"},
                   {"a": "Team A"}, {"a": None, "b": None, "c": None}, None):
        body = {"request_id": rid(), "source": source(), "task_id": "booking-v1",
                "candidate_budget_minutes": 10, "max_repair_rounds": 1,
                "provider_labels": labels}
        assert post(client, f"{API}/matches", body, tokens["operator"]).status_code == 422


def test_labels_are_public_and_survive_restart_on_match_and_assignment(tmp_path):
    client, _, settings, runner, tokens = setup(tmp_path)
    labels = {"a": "Provider One", "b": None}
    match = create_match(client, tokens["operator"], provider_labels=labels)
    mid = match["match_id"]
    assert match["provider_labels"] == labels
    assert get(client, f"{API}/matches/{mid}/assignments/a", tokens["a"]).json()["provider_labels"] == labels
    restarted = TestClient(create_app(settings=settings, runner=runner, start_worker=False))
    assert get(restarted, f"{API}/matches/{mid}", tokens["operator"]).json()["provider_labels"] == labels
    assert get(restarted, f"{API}/matches/{mid}/assignments/b", tokens["b"]).json()["provider_labels"] == labels


def test_existing_v10_state_and_cached_match_retries_upgrade_without_reset(tmp_path):
    from arena_engine.workspaces import read_runtime

    client, app, settings, runner, tokens = setup(tmp_path)
    labels = {"a": "  Recorded label  ", "b": "Provider Two"}
    body = {"request_id": rid(), "source": source(), "task_id": "booking-v1",
            "candidate_budget_minutes": 10, "max_repair_rounds": 1, "provider_labels": labels}
    original = post(client, f"{API}/matches", body, tokens["operator"]).json()
    metadata_path = settings.state_dir / "runtime.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["contract_version"] = "1.0"
    metadata_path.write_text(json.dumps(metadata))
    # 1.0 persisted the same private labels but did not project them publicly.
    old_response = {key: value for key, value in original.items() if key != "provider_labels"}
    with app.state.engine.store.transaction() as db:
        db.execute("UPDATE requests SET response=? WHERE request_id=?", (json.dumps(old_response), body["request_id"]))
    token_bytes = (settings.state_dir / "auth/operator.token").read_bytes()
    assert read_runtime(settings)["base_commit"] == metadata["base_commit"]
    restarted = TestClient(create_app(settings=settings, runner=runner, start_worker=False))
    replay = post(restarted, f"{API}/matches", body, tokens["operator"])
    assert replay.status_code == 201 and replay.json() == original
    assert get(restarted, f"{API}/matches/{original['match_id']}/assignments/a", tokens["a"]).json()["provider_labels"] == labels
    assert (settings.state_dir / "auth/operator.token").read_bytes() == token_bytes
    assert json.loads(metadata_path.read_text()) == metadata


def test_challenge_requirement_ids_must_be_unique(tmp_path):
    from test_full_match import make_reviewing
    client, app, settings, _, tokens, mid, state = make_reviewing(tmp_path)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    body = {"request_id": rid(), "source": source(), "target_candidate_id": target,
            "requirement_ids": ["BOOK-01", "BOOK-01"], "title": "Duplicate requirement",
            "scenario": {"capacity": 1, "steps": [{"op": "available", "args": [], "expected": 1}]}}
    assert post(client, f"{API}/matches/{mid}/challenges", body, tokens["b"]).status_code == 422
    body.update(requirement_ids=["BOOK-01"], title="  ")
    assert post(client, f"{API}/matches/{mid}/challenges", body, tokens["b"]).status_code == 422


def test_api_mode_header_covers_json_text_errors_and_generic_failures(tmp_path, monkeypatch):
    client, app, settings, _, tokens = setup(tmp_path)
    responses = [client.get(f"{API}/health"),
                 post(client, f"{API}/matches", {"broken": True}, tokens["operator"]),
                 get(client, f"{API}/matches/missing", "invalid-token")]
    match = create_match(client, tokens["operator"])
    mid = match["match_id"]
    responses += [get(client, f"{API}/matches/{mid}", tokens["operator"]),
                  get(client, f"{API}/matches/{mid}/assignments/a", tokens["a"])]
    sha = commit_candidate(settings, "a")
    job_id = submit(client, mid, "a", tokens["a"], sha).json()["job_id"]
    assert app.state.engine.worker_once()
    job_response = get(client, f"{API}/jobs/{job_id}", tokens["operator"])
    responses.append(job_response)
    artifact_id = job_response.json()["result"]["log_artifact_id"]
    artifact_response = get(client, f"{API}/artifacts/{artifact_id}", tokens["operator"])
    assert artifact_response.headers["content-type"].startswith("text/plain")
    responses.append(artifact_response)
    responses.append(post(client, f"{API}/matches/{mid}/actions", {
                      "request_id": rid(), "source": source(), "action": "cancel", "reason": "header test",
                  }, tokens["operator"]))
    # Force the app-wide exception handler without relying on an invalid endpoint.
    monkeypatch.setattr(app.state.engine, "get_match", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    responses.append(get(client, f"{API}/matches/{mid}", tokens["operator"]))
    for response in responses:
        assert response.headers.get("X-Arena-Mode") == "live", (response.status_code, response.text)


def test_cors_exposes_mode_including_preflight_and_internal_errors(tmp_path, monkeypatch):
    from dataclasses import replace

    _, _, settings, runner, tokens = setup(tmp_path)
    origin = "http://127.0.0.1:5173"
    app = create_app(settings=replace(settings, ui_origin=origin), runner=runner, start_worker=False)
    client = TestClient(app)
    preflight = client.options(f"{API}/matches", headers={"Origin": origin,
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
    monkeypatch.setattr(app.state.engine, "get_match", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    failed = client.get(f"{API}/matches/missing", headers={"Origin": origin,
        "Authorization": "Bearer " + tokens["operator"]})
    assert failed.status_code == 503
    for response in (preflight, failed):
        assert response.headers["X-Arena-Mode"] == "live"
        assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "X-Arena-Mode" in failed.headers["Access-Control-Expose-Headers"]
