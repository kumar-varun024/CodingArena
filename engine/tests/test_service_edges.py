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
