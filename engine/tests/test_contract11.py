"""Integration coverage for the live 1.1 HTTP contract and response mode."""

import json

from fastapi.testclient import TestClient

from arena_engine.api import create_app
from arena_engine.runtime import DEFAULT_IMAGE, Settings
from test_protocol import FakeRunner, commit_candidate, get, post, rid, setup, source, submit


API = "/api/v1"


def assert_live(response):
    assert response.headers.get("X-Arena-Mode") == "live", (response.status_code, response.text)
    return response


def test_legacy_create_retry_keeps_original_result_and_recorded_labels(tmp_path):
    client, app, _, _, tokens = setup(tmp_path)
    body = create_body({"a": "Recorded A", "b": "Recorded B"})
    created = post(client, f"{API}/matches", body, tokens["operator"])
    original = created.json()
    # Emulate a saved 1.0 response and the private metadata used by that engine.
    with app.state.engine.store.transaction() as db:
        match = app.state.engine._match(db, original["match_id"])
        match.pop("provider_labels")
        app.state.engine.store.save_match(db, match)
        archived = dict(original)
        archived.pop("provider_labels")
        db.execute("UPDATE requests SET response=? WHERE request_id=?", (json.dumps(archived), body["request_id"]))
    retried = assert_live(post(client, f"{API}/matches", body, tokens["operator"]))
    assert retried.status_code == 201
    assert retried.json() == original


def create_body(labels=None, **extra):
    body = {
        "request_id": rid(),
        "source": source(),
        "task_id": "booking-v1",
        "candidate_budget_minutes": 10,
        "max_repair_rounds": 1,
        "provider_labels": labels if labels is not None else {"a": "Alpha", "b": "Beta"},
    }
    body.update(extra)
    return body


def advance_to_neither_decision(client, app, settings, tokens, match_id):
    for slot in ("a", "b"):
        sha = commit_candidate(settings, slot)
        response = assert_live(submit(client, match_id, slot, tokens[slot], sha))
        assert response.status_code == 202
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    state = assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"])).json()
    reveal = assert_live(post(client, f"{API}/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "reveal", "reason": "test",
    }, tokens["operator"]))
    assert reveal.status_code == 200
    state = assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"])).json()
    for slot in ("a", "b"):
        target_slot = "b" if slot == "a" else "a"
        response = assert_live(post(client,
            f"{API}/matches/{match_id}/reviews/{slot}/complete", {
                "request_id": rid(), "source": source(),
                "target_candidate_id": state["slots"][target_slot]["candidate"]["candidate_id"],
            }, tokens[slot]))
        assert response.status_code == 200
    finalized = assert_live(post(client, f"{API}/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "finalize", "reason": "test",
    }, tokens["operator"]))
    assert finalized.status_code == 200
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    decision = assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"]))
    assert decision.json()["phase"] == "decision"
    selected = assert_live(post(client, f"{API}/matches/{match_id}/selection", {
        "request_id": rid(), "source": source(), "selection": "neither",
        "candidate_id": None, "expected_evidence_key": None,
        "reason": "No eligible candidate in protocol fixture",
    }, tokens["operator"]))
    assert selected.status_code == 200
    return selected.json()["outcome"]


def test_live_mode_header_on_success_and_error_responses(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path)
    assert_live(client.get(f"{API}/health"))
    created = assert_live(post(client, f"{API}/matches", create_body(), tokens["operator"]))
    assert created.status_code == 201
    match_id = created.json()["match_id"]
    assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"]))
    assert_live(get(client, f"{API}/matches/{match_id}/assignments/a", tokens["a"]))

    assert assert_live(get(client, f"{API}/matches/{match_id}", "invalid-token")).status_code == 401
    assert assert_live(get(client, f"{API}/matches/{match_id}/assignments/a", tokens["b"])).status_code == 403
    assert assert_live(get(client, f"{API}/matches/missing", tokens["operator"])).status_code == 404

    phase_conflict = post(client, f"{API}/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "reveal", "reason": "too early",
    }, tokens["operator"])
    assert assert_live(phase_conflict).status_code == 409

    invalid = create_body()
    invalid["provider_labels"] = {"a": " ", "b": "Beta"}
    assert assert_live(post(client, f"{API}/matches", invalid, tokens["operator"])).status_code == 422
    malformed = client.post(f"{API}/matches", content="{", headers={
        "Authorization": "Bearer " + tokens["operator"], "Content-Type": "application/json",
    })
    assert assert_live(malformed).status_code == 400

    app.state.engine.get_match = lambda *_args: (_ for _ in ()).throw(RuntimeError("injected"))
    assert assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"])).status_code == 503


def test_runner_unavailable_error_has_live_mode(tmp_path):
    client, _, _, _, tokens = setup(tmp_path, FakeRunner(available=False))
    response = assert_live(post(client, f"{API}/matches", create_body(), tokens["operator"]))
    match_id = response.json()["match_id"]
    sha = commit_candidate(client.app.state.engine.settings, "a")
    submitted = assert_live(submit(client, match_id, "a", tokens["a"], sha))
    assert submitted.status_code == 503


def test_provider_labels_round_trip_assignment_and_restart(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path)
    labels = {"a": None, "b": "Codex local"}
    created = assert_live(post(client, f"{API}/matches", create_body(labels), tokens["operator"]))
    assert created.status_code == 201
    match_id = created.json()["match_id"]

    def assert_labels(target):
        match = assert_live(get(target, f"{API}/matches/{match_id}", tokens["operator"])).json()
        assert match["provider_labels"] == labels
        for slot in ("a", "b"):
            assignment = assert_live(get(target, f"{API}/matches/{match_id}/assignments/{slot}", tokens[slot]))
            assert assignment.json()["provider_labels"] == labels

    assert_labels(client)
    for slot in ("a", "b"):
        sha = commit_candidate(settings, slot)
        assert assert_live(submit(client, match_id, slot, tokens[slot], sha)).status_code == 202
    assert app.state.engine.worker_once()
    assert app.state.engine.worker_once()
    reveal = assert_live(post(client, f"{API}/matches/{match_id}/actions", {
        "request_id": rid(), "source": source(), "action": "reveal", "reason": "test",
    }, tokens["operator"]))
    assert reveal.status_code == 200
    assert_labels(client)

    restarted = TestClient(create_app(settings=settings, runner=FakeRunner(), start_worker=False))
    assert_labels(restarted)


def test_provider_labels_reject_empty_extra_and_duplicate_keys(tmp_path):
    client, _, _, _, tokens = setup(tmp_path)
    empty = create_body({"a": "", "b": "Beta"})
    extra = create_body({"a": "Alpha", "b": "Beta", "c": "Extra"})
    assert assert_live(post(client, f"{API}/matches", empty, tokens["operator"])).status_code == 422
    assert assert_live(post(client, f"{API}/matches", extra, tokens["operator"])).status_code == 422

    duplicate_key_body = json.dumps(create_body()).replace(
        '"a": "Alpha"', '"a": "Alpha", "a": "Second"', 1,
    )
    duplicate = client.post(f"{API}/matches", content=duplicate_key_body, headers={
        "Authorization": "Bearer " + tokens["operator"], "Content-Type": "application/json",
    })
    assert assert_live(duplicate).status_code == 422


def test_duplicate_challenge_requirement_ids_are_rejected_with_live_mode(tmp_path):
    from test_full_match import make_reviewing

    client, _, _, _, tokens, match_id, state = make_reviewing(tmp_path, broken_a=True)
    target = state["slots"]["a"]["candidate"]["candidate_id"]
    body = {
        "request_id": rid(), "source": source(), "target_candidate_id": target,
        "requirement_ids": ["BOOK-01", "BOOK-01"], "title": "Duplicate requirement",
        "scenario": {"capacity": 3, "steps": [
            {"op": "available", "args": [], "expected": 3},
        ]},
    }
    response = assert_live(post(client, f"{API}/matches/{match_id}/challenges", body, tokens["b"]))
    assert response.status_code == 422


def test_artifact_responses_keep_live_mode_for_text_and_json(tmp_path):
    client, app, settings, _, tokens = setup(tmp_path)
    match_id = assert_live(post(client, f"{API}/matches", create_body(), tokens["operator"])).json()["match_id"]
    outcome = advance_to_neither_decision(client, app, settings, tokens, match_id)
    evidence = assert_live(get(client, f"{API}/artifacts/{outcome['evidence_artifact_id']}", tokens["operator"]))
    assert evidence.status_code == 200
    assert evidence.headers["content-type"].startswith("application/json")
    json.loads(evidence.content)

    state = assert_live(get(client, f"{API}/matches/{match_id}", tokens["operator"])).json()
    job_id = state["slots"]["a"]["candidate"]["verification"]["job_id"]
    job = assert_live(get(client, f"{API}/jobs/{job_id}", tokens["operator"])).json()
    log_id = job["result"]["log_artifact_id"]
    log = assert_live(get(client, f"{API}/artifacts/{log_id}", tokens["operator"]))
    assert log.status_code == 200
    assert log.headers["content-type"].startswith("text/plain")


def test_cors_preflight_and_error_expose_mode_only_for_configured_origin(tmp_path):
    settings = Settings(tmp_path / "cors-state", DEFAULT_IMAGE,
                        ui_origin="http://127.0.0.1:5173")
    from arena_engine.workspaces import initialize
    initialize(settings)
    app = create_app(settings=settings, runner=FakeRunner(), start_worker=False)
    client = TestClient(app)
    token = (settings.state_dir / "auth/operator.token").read_text().strip()
    preflight = client.options(f"{API}/matches", headers={
        "Origin": settings.ui_origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == settings.ui_origin
    assert_live(preflight)

    created = client.post(f"{API}/matches", json=create_body(), headers={
        "Authorization": "Bearer " + token, "Origin": settings.ui_origin,
    })
    assert_live(created)
    assert created.headers.get("access-control-allow-origin") == settings.ui_origin
    assert "x-arena-mode" in created.headers.get("access-control-expose-headers", "").lower()

    app.state.engine.get_match = lambda *_args: (_ for _ in ()).throw(RuntimeError("injected"))
    error = client.get(f"{API}/matches/{created.json()['match_id']}", headers={
        "Authorization": "Bearer " + token, "Origin": settings.ui_origin,
    })
    assert error.status_code == 503
    assert_live(error)
    assert error.headers.get("access-control-allow-origin") == settings.ui_origin
    assert "x-arena-mode" in error.headers.get("access-control-expose-headers", "").lower()

    default_client, _, _, _, _ = setup(tmp_path / "no-cors")
    default_response = default_client.get(f"{API}/health", headers={"Origin": settings.ui_origin})
    assert_live(default_response)
    assert "access-control-allow-origin" not in default_response.headers
