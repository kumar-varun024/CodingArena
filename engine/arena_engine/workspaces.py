"""Provision isolated contestant workspaces and immutable source snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

from .contract import ROOT, canonical_bytes, load_contract
from .runtime import Settings

TASK_ID = "booking-v1"
MAX_SOURCE_BYTES = 128 * 1024
MARKER = "coding-arena-state-v1\n"
PUBLIC_FILES = ("SPEC.md", "public_cases.json", "public_checks.json", "src/booking.py")


class WorkspaceError(ValueError):
    """Workspace state or candidate snapshot is invalid."""


def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=path, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError("git is unavailable") from exc
    if check and result.returncode:
        raise WorkspaceError("git workspace validation failed")
    return result


def _safe_state_path(settings: Settings) -> Path:
    raw = Path(settings.state_dir).expanduser()
    if raw.is_symlink():
        raise WorkspaceError("state directory cannot be a symlink")
    target = raw.resolve()
    product = ROOT.resolve()
    if target == product or target in product.parents:
        raise WorkspaceError("state directory cannot be the product checkout or its ancestor")
    return target


def _check_active(state: Path) -> None:
    db = state / "arena.sqlite3"
    if not db.exists():
        return
    if db.is_symlink() or not db.is_file():
        raise WorkspaceError("invalid runtime database")
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "matches" not in tables:
                return
            if not {"match_id", "phase", "data"}.issubset({row[1] for row in conn.execute("PRAGMA table_info(matches)")}):
                raise WorkspaceError("corrupt runtime database")
            if conn.execute("SELECT 1 FROM matches WHERE phase NOT IN ('complete','cancelled') LIMIT 1").fetchone():
                raise WorkspaceError("cannot initialize while a match is active")
    except sqlite3.Error as exc:
        raise WorkspaceError("corrupt runtime database") from exc


def _validate_initialized(state: Path) -> dict:
    required = [state / "runtime.json", state / "auth" / "operator.token"]
    required += [state / "workers" / slot / ".arena" / "slot.token" for slot in ("a", "b")]
    required += [state / "workers" / slot / "worktree" / ".git" for slot in ("a", "b")]
    required += [state / "task-base" / ".git"]
    # Reject symlinks at every state-owned path component, not only the leaf.
    owned = [state / "runtime.json", state / "auth", state / "auth" / "operator.token",
             state / "task-base", state / "task-base" / ".git", state / "workers"]
    for slot in ("a", "b"):
        owned += [state / "workers" / slot, state / "workers" / slot / ".arena",
                  state / "workers" / slot / ".arena" / "slot.token",
                  state / "workers" / slot / "worktree", state / "workers" / slot / "worktree" / ".git"]
    if any(p.is_symlink() for p in owned) or any(not p.exists() for p in required):
        raise WorkspaceError("marked state directory is incomplete or corrupted")
    try:
        meta = json.loads((state / "runtime.json").read_text(encoding="utf-8"))
        if meta.get("task_id") != TASK_ID or meta.get("contract_version") != "1.0":
            raise ValueError
        contract = load_contract()
        expected_digest = hashlib.sha256(canonical_bytes(contract["booking_contract"])).hexdigest()
        if meta.get("spec_digest") != expected_digest:
            raise ValueError
        expected_workers = {s: str(state / "workers" / s) for s in ("a", "b")}
        if meta.get("workers") != expected_workers:
            raise ValueError
        for token in [state / "auth" / "operator.token"] + [state / "workers" / s / ".arena" / "slot.token" for s in ("a", "b")]:
            if not token.is_file() or not token.read_bytes().strip() or stat.S_IMODE(token.stat().st_mode) != 0o600:
                raise ValueError
        base = _git(state / "task-base", "rev-parse", "HEAD").stdout.strip()
        if base != meta.get("base_commit"):
            raise ValueError
        for slot in ("a", "b"):
            path = state / "workers" / slot / "worktree"
            if _git(path, "rev-parse", "--show-toplevel").stdout.strip() != str(path):
                raise ValueError
            # Worktrees are intentionally mutable after initialization. The
            # pinned base is verified through runtime metadata and clone origin.
            origin = _git(path, "config", "--get", "remote.origin.url").stdout.strip()
            if Path(origin).resolve() != (state / "task-base").resolve():
                raise ValueError
        return meta
    except (OSError, ValueError, KeyError, WorkspaceError, json.JSONDecodeError) as exc:
        raise WorkspaceError("marked state directory is incomplete or corrupted") from exc


def initialize(settings: Settings) -> dict:
    """Create stable slot roots, sanitized shared base, and private bearer tokens."""
    state = _safe_state_path(settings)
    if state.exists():
        if not state.is_dir() or state.is_symlink():
            raise WorkspaceError("state path must be a real directory")
        marker = state / ".arena-state"
        if not marker.is_file() or marker.is_symlink():
            if any(state.iterdir()):
                raise WorkspaceError("refusing nonempty unmarked state directory")
        else:
            if marker.read_text(encoding="utf-8") != MARKER:
                raise WorkspaceError("invalid state marker")
            _check_active(state)
            return _validate_initialized(state)
    else:
        state.mkdir(parents=True, mode=0o700)
    try:
        _check_active(state)
        (state / ".arena-state").write_text(MARKER, encoding="utf-8")
        os.chmod(state / ".arena-state", 0o600)
        base = state / "task-base"
        base.mkdir()
        starter = ROOT / "fixtures" / TASK_ID / "starter"
        for rel in PUBLIC_FILES:
            src, dst = starter / rel, base / rel
            if not src.is_file() or src.is_symlink():
                raise WorkspaceError("starter task pack is incomplete")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        (base / ".gitignore").write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")
        _git(base, "init", "-q")
        _git(base, "config", "user.name", "Coding Arena")
        _git(base, "config", "user.email", "arena@localhost")
        _git(base, "add", "--", ".gitignore", *PUBLIC_FILES)
        _git(base, "commit", "-q", "-m", "booking-v1 sanitized task base")
        base_commit = _git(base, "rev-parse", "HEAD").stdout.strip()
        for slot in ("a", "b"):
            root = state / "workers" / slot
            (root / ".arena").mkdir(parents=True)
            (root / "review").mkdir()
            worktree = root / "worktree"
            _git(state, "clone", "-q", str(base), str(worktree))
            _git(worktree, "config", "user.name", "Coding Arena " + slot.upper())
            _git(worktree, "config", "user.email", f"slot-{slot}@localhost")
        auth = state / "auth"
        auth.mkdir()
        token_paths = [auth / "operator.token"] + [state / "workers" / s / ".arena" / "slot.token" for s in ("a", "b")]
        for token in token_paths:
            fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(secrets.token_urlsafe(32) + "\n")
        contract = load_contract()
        meta = {
            "base_commit": base_commit,
            "task_id": TASK_ID,
            "contract_version": "1.0",
            "spec_digest": hashlib.sha256(canonical_bytes(contract["booking_contract"])).hexdigest(),
            "workers": {s: str(state / "workers" / s) for s in ("a", "b")},
        }
        (state / "runtime.json").write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.chmod(state / "runtime.json", 0o600)
        return meta
    except Exception as exc:
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError("failed to initialize runtime state") from exc


def read_runtime(settings: Settings) -> dict:
    """Read non-secret workspace metadata without provisioning anything."""
    state = _safe_state_path(settings)
    marker = state / ".arena-state"
    if not marker.is_file() or marker.is_symlink() or marker.read_text(encoding="utf-8") != MARKER:
        raise WorkspaceError("runtime state is not initialized")
    return _validate_initialized(state)


def freeze(settings: Settings, slot: str, commit_sha: str, snapshot_id: str) -> dict:
    """Validate a submitted commit and atomically preserve its allowed source."""
    if slot not in ("a", "b") or not re.fullmatch(r"[0-9a-fA-F]{40}", str(commit_sha)):
        raise WorkspaceError("invalid slot or commit")
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", snapshot_id) or snapshot_id in (".", ".."):
        raise WorkspaceError("invalid snapshot id")
    state = _safe_state_path(settings)
    meta = read_runtime(settings)
    worktree = Path(meta["workers"][slot]) / "worktree"
    if worktree.is_symlink() or _git(worktree, "rev-parse", "--show-toplevel").stdout.strip() != str(worktree):
        raise WorkspaceError("invalid worker worktree")
    commit_sha = commit_sha.lower()
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    if head != commit_sha:
        raise WorkspaceError("commit is not the workspace HEAD")
    if _git(worktree, "status", "--porcelain", "--untracked-files=all").stdout:
        raise WorkspaceError("workspace has uncommitted changes")
    if _git(worktree, "merge-base", "--is-ancestor", meta["base_commit"], commit_sha, check=False).returncode:
        raise WorkspaceError("commit does not descend from pinned task base")
    changed = _git(worktree, "diff", "--no-ext-diff", "--no-textconv", "--name-only", meta["base_commit"] + "..." + commit_sha).stdout.splitlines()
    if changed not in ([], ["src/booking.py"]):
        raise WorkspaceError("commit must change only src/booking.py")
    entry = _git(worktree, "ls-tree", commit_sha, "--", "src/booking.py").stdout.strip().split()
    if len(entry) < 4 or entry[0] != "100644" or entry[1] != "blob" or entry[3] != "src/booking.py":
        raise WorkspaceError("candidate source must be a regular 100644 file")
    try:
        blob_result = subprocess.run(
            ["git", "cat-file", "blob", commit_sha + ":src/booking.py"],
            cwd=worktree, capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkspaceError("candidate source could not be read") from exc
    blob = blob_result.stdout
    if len(blob) > MAX_SOURCE_BYTES:
        raise WorkspaceError("candidate source exceeds size limit")
    snapshots = state / "snapshots"
    if snapshots.is_symlink():
        raise WorkspaceError("invalid snapshots directory")
    snapshots.mkdir(exist_ok=True)
    dest = snapshots / snapshot_id
    try:
        dest.mkdir(mode=0o700)
        srcdir = dest / "src"
        srcdir.mkdir(mode=0o700)
        out = srcdir / "booking.py"
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
        os.chmod(out, 0o400)
        os.chmod(srcdir, 0o500)
        os.chmod(dest, 0o500)
    except FileExistsError as exc:
        raise WorkspaceError("snapshot already exists") from exc
    except OSError as exc:
        raise WorkspaceError("could not create immutable snapshot") from exc
    return {"commit_sha": commit_sha, "tree_digest": hashlib.sha256(blob).hexdigest(), "path": str(out.resolve())}
