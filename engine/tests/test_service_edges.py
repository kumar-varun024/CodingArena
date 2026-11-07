import pytest

from arena_engine.errors import ArenaError
from arena_engine.runner import RunnerError
from arena_engine.runtime import Settings, DEFAULT_IMAGE
from arena_engine.service import Engine
from arena_engine.workspaces import initialize


class ReadyRunner:
    digest = "a" * 64

    def available(self):
        return True

    def cancel(self):
        pass


def test_exclusive_server_lock_releases_after_shutdown(tmp_path):
    settings = Settings(tmp_path / "state", DEFAULT_IMAGE)
    initialize(settings)
    engine = Engine(settings, ReadyRunner(), exclusive=True)
    try:
        with pytest.raises(ArenaError, match="Another engine server"):
            Engine(settings, ReadyRunner(), exclusive=True)
        with pytest.raises(ArenaError) as error:
            engine.authenticate("Bearer λ")
        assert error.value.status == 401
    finally:
        engine.stop()
    restarted = Engine(settings, ReadyRunner(), exclusive=True)
    restarted.stop()


def test_failed_orphan_cleanup_blocks_execution(tmp_path):
    class CleanupFailure(ReadyRunner):
        def cleanup_interrupted(self):
            raise RunnerError("Docker removal failed")

    settings = Settings(tmp_path / "state", DEFAULT_IMAGE)
    initialize(settings)
    engine = Engine(settings, CleanupFailure(), exclusive=True)
    try:
        assert engine.worker_failed is True
        engine.start()
        assert engine._thread is None
    finally:
        engine.stop()


def test_legacy_match_cannot_silently_use_a_new_reference(tmp_path):
    from test_full_match import make_reviewing, report_challenge
    client, app, _, _, tokens, match_id, match = make_reviewing(tmp_path)
    with app.state.engine.store.transaction() as db:
        old = app.state.engine._match(db, match_id)
        old.pop("_reference")
        app.state.engine.store.save_match(db, old)
    response = report_challenge(client, match_id, "a", tokens["a"], match["slots"]["b"]["candidate"]["candidate_id"])
    assert response.status_code == 409
    assert "no frozen reference" in response.json()["error"]["message"]


def test_changed_legacy_baseline_is_refused_before_finalization(tmp_path):
    from test_full_match import make_reviewing, req, post, action, API
    client, app, _, _, tokens, match_id, match = make_reviewing(tmp_path)
    with app.state.engine.store.transaction() as db:
        old = app.state.engine._match(db, match_id)
        old.pop("_baseline_checks")
        old.pop("_public_cases")
        app.state.engine.store.save_match(db, old)
    for slot in ("a", "b"):
        response = post(client, f"{API}/matches/{match_id}/reviews/{slot}/complete", req({
            "target_candidate_id": match["slots"]["b" if slot == "a" else "a"]["candidate"]["candidate_id"],
        }), tokens[slot])
        assert response.status_code == 200
    # Model a newer installed task pack while retaining the older frozen match.
    app.state.engine.full = app.state.engine.full + [{"check_id": "NEW-CHECK", "scenario": {
        "capacity": 1, "steps": [{"op": "available", "args": [], "expected": 1}]}}]
    response = action(client, match_id, tokens["operator"], "finalize")
    assert response.status_code == 409
    assert "Legacy task checks changed" in response.json()["error"]["message"]
