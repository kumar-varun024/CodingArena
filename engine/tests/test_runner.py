import os
import json
import threading
from pathlib import Path

import pytest

from arena_engine.runner import DockerRunner, RunnerError
from arena_engine.runtime import Settings

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "fixtures" / "booking-v1"
IMAGE = "python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54"


def _runner() -> DockerRunner:
    return DockerRunner(Settings(ROOT / "var", IMAGE))


def test_unavailable_docker_is_reported(monkeypatch):
    runner = _runner()

    def unavailable(*args, **kwargs):
        raise RunnerError("Docker daemon unavailable")

    monkeypatch.setattr(runner, "_run", unavailable)
    assert runner.available() is False


def test_unpinned_image_is_rejected_before_docker(monkeypatch):
    runner = DockerRunner(Settings(ROOT / "var", "python:latest"))
    monkeypatch.setattr(runner, "_run", lambda *a, **k: pytest.fail("Docker must not be called"))
    with pytest.raises(RunnerError, match="pinned"):
        runner._refresh_image()


def test_output_overflow_is_signalled():
    class Stream:
        def __init__(self):
            self.data = b"x" * (64 * 1024 + 1)

        def read(self, size):
            data, self.data = self.data[:size], self.data[size:]
            return data

    output, overflow = bytearray(), threading.Event()
    DockerRunner._reader(Stream(), output, overflow)
    assert len(output) == 64 * 1024
    assert overflow.is_set()


def test_cancel_event_aborts_before_docker():
    runner = _runner()
    event = threading.Event()
    event.set()
    with pytest.raises(RunnerError, match="cancelled"):
        runner.verify(PACK / "known-good" / "booking.py", [], False, cancel_event=event)


def test_interrupted_cleanup_is_scoped_to_state_label(monkeypatch, tmp_path):
    runner = DockerRunner(Settings(tmp_path, IMAGE))
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        if args[0] == "ps":
            return type("Result", (), {"returncode": 0, "stdout": b"ours-1\nours-2\n"})()
        return type("Result", (), {"returncode": 0, "stdout": b""})()

    monkeypatch.setattr(runner, "_run", docker)
    assert runner.cleanup_interrupted()
    assert calls[0][:4] == ["ps", "--all", "--quiet", "--filter"]
    assert calls[0][4] == f"label=coding-arena.state={runner._state_label}"
    assert calls[1] == ["rm", "--force", "ours-1", "ours-2"]


def test_interrupted_cleanup_does_not_remove_when_empty(monkeypatch, tmp_path):
    runner = DockerRunner(Settings(tmp_path, IMAGE))
    calls = []

    def docker(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": b""})()

    monkeypatch.setattr(runner, "_run", docker)
    assert runner.cleanup_interrupted()
    assert len(calls) == 1


@pytest.mark.skipif(os.environ.get("ARENA_DOCKER_TESTS") != "1", reason="requires opt-in Docker")
def test_docker_runner_known_good_and_bad():
    runner = _runner()
    if not runner.available():
        pytest.fail("opt-in Docker test requires the daemon and pinned image")
    good = runner.verify(PACK / "known-good" / "booking.py", [], include_isolation=True)
    assert good["failed_check_ids"] == []
    case = json.loads((PACK / "known-bad" / "scenarios" / "repeat_cancel.json").read_text())
    bad = runner.verify(PACK / "known-bad" / "repeat_cancel.py",
                        [case],
                        include_isolation=False)
    assert bad["failed_check_ids"] == [case["check_id"]]
