from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess

import pytest

from arena_engine.runtime import Settings
from arena_engine.workspaces import WorkspaceError, freeze, initialize, read_runtime


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def _commit_candidate(meta: dict, slot: str = "a") -> str:
    worktree = Path(meta["workers"][slot]) / "worktree"
    source = worktree / "src" / "booking.py"
    source.write_text(source.read_text() + "\n# candidate change\n", encoding="utf-8")
    _git(worktree, "add", "src/booking.py")
    _git(worktree, "commit", "-m", "candidate")
    return _git(worktree, "rev-parse", "HEAD")


def test_initialize_builds_separate_sanitized_clones_and_reuses_tokens(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "state", "image")
    meta = initialize(settings)
    base = Path(settings.state_dir) / "task-base"
    a, b = (Path(meta["workers"][s]) / "worktree" for s in ("a", "b"))
    assert meta["base_commit"] == _git(base, "rev-parse", "HEAD")
    assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD") == meta["base_commit"]
    assert a != b and a.resolve() != b.resolve()
    assert not (base / "reference").exists()
    assert not (base / "held_out_cases").exists()
    assert set(p.name for p in base.iterdir()) == {".git", ".gitignore", "SPEC.md", "public_cases.json", "public_checks.json", "src"}
    token = (Path(settings.state_dir) / "auth" / "operator.token").read_text()
    assert os.stat(Path(settings.state_dir) / "auth" / "operator.token").st_mode & 0o777 == 0o600
    assert initialize(settings) == meta
    assert (Path(settings.state_dir) / "auth" / "operator.token").read_text() == token
    assert read_runtime(settings) == meta


def test_freeze_is_immutable_and_rejects_dirty_or_unallowed_changes(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "state", "image")
    meta = initialize(settings)
    sha = _commit_candidate(meta)
    frozen = freeze(settings, "a", sha, "snap_1")
    snapshot = Path(frozen["path"])
    original = snapshot.read_bytes()
    assert frozen["tree_digest"]
    worktree = Path(meta["workers"]["a"]) / "worktree"
    (worktree / "src" / "booking.py").write_text("changed after freeze", encoding="utf-8")
    assert snapshot.read_bytes() == original
    with pytest.raises(WorkspaceError, match="uncommitted"):
        freeze(settings, "a", sha, "snap_2")

    _git(worktree, "checkout", "--", "src/booking.py")
    (worktree / "extra.txt").write_text("not allowed", encoding="utf-8")
    _git(worktree, "add", "extra.txt")
    _git(worktree, "commit", "-m", "extra")
    with pytest.raises(WorkspaceError, match="only src/booking.py"):
        freeze(settings, "a", _git(worktree, "rev-parse", "HEAD"), "snap_3")


def test_freeze_rejects_non_descendant_and_invalid_snapshot_id(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "state", "image")
    meta = initialize(settings)
    wt = Path(meta["workers"]["a"]) / "worktree"
    _git(wt, "checkout", "--orphan", "orphan")
    _git(wt, "rm", "-rf", ".")
    (wt / "src").mkdir()
    (wt / "src" / "booking.py").write_text("x = 1\n", encoding="utf-8")
    _git(wt, "add", "src/booking.py")
    _git(wt, "commit", "-m", "orphan")
    sha = _git(wt, "rev-parse", "HEAD")
    with pytest.raises(WorkspaceError, match="does not descend"):
        freeze(settings, "a", sha, "snap")
    with pytest.raises(WorkspaceError, match="snapshot id"):
        freeze(settings, "a", sha, "../escape")


def test_freeze_allows_unchanged_base_source(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "state", "image")
    meta = initialize(settings)
    result = freeze(settings, "a", meta["base_commit"], "base")
    assert Path(result["path"]).read_bytes() == (Path(meta["workers"]["a"]) / "worktree/src/booking.py").read_bytes()


def test_initialize_refuses_unmarked_and_active_state(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "keep").write_text("data")
    with pytest.raises(WorkspaceError, match="unmarked"):
        initialize(Settings(state, "image"))

    state2 = tmp_path / "active"
    settings = Settings(state2, "image")
    initialize(settings)
    db = sqlite3.connect(state2 / "arena.sqlite3")
    db.execute("CREATE TABLE matches(match_id TEXT PRIMARY KEY, phase TEXT, data TEXT)")
    db.execute("INSERT INTO matches VALUES('m1','building','{}')")
    db.commit()
    db.close()
    # Active state prevents reinitialization, but submissions must still freeze.
    active_meta = read_runtime(settings)
    assert freeze(settings, "a", active_meta["base_commit"], "during_match")["commit_sha"] == active_meta["base_commit"]
    with pytest.raises(WorkspaceError, match="active"):
        initialize(settings)
