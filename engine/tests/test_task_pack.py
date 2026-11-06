"""Opt-in Docker integration check for the frozen booking task pack."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_task_pack.py"
SPEC = importlib.util.spec_from_file_location("check_task_pack", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import bootstrap
    raise RuntimeError("cannot load check_task_pack.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_snapshot_is_independent_of_later_source_edits() -> None:
    with tempfile.TemporaryDirectory(prefix="arena-snapshot-test-") as directory:
        root = Path(directory)
        source = root / "editable.py"
        snapshot = root / "snapshot" / "booking.py"
        source.write_text("original fixture\n", encoding="utf-8")
        CHECKER._copy_snapshot(source, snapshot)
        source.write_text("changed fixture\n", encoding="utf-8")
        assert snapshot.read_text(encoding="utf-8") == "original fixture\n"


@pytest.mark.skipif(os.environ.get("ARENA_DOCKER_TESTS") != "1", reason="set ARENA_DOCKER_TESTS=1 to run Docker fixture suite")
def test_task_pack_in_restricted_docker() -> None:
    counts = CHECKER.run_check()
    assert counts["executed"] > 0
    assert counts["unexpected"] == 0
