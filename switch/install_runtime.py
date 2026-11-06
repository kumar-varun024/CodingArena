#!/usr/bin/env python3
"""Install Role B materials into existing engine-provisioned stable slot roots.

This tool never provisions task checkouts, reads token contents, calls the engine,
or registers agents. Native Switch smoke evidence must be observed separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit


class InstallError(Exception):
    pass


def api_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        port = parts.port
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment
                or parts.path.rstrip("/") not in {"", "/api/v1"}
                or any(char.isspace() for char in value)
                or (port is not None and port < 1)):
            raise ValueError
    except ValueError as exc:
        raise InstallError("--api-url must be an HTTP(S) origin or /api/v1 URL without credentials, query or fragment") from exc
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "/api/v1", "", ""))


def no_symlinks(path: Path) -> None:
    """Check every existing component, including the final file, without resolving it."""
    if not path.is_absolute() or ".." in path.parts:
        raise InstallError("use an absolute path without parent traversal")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise InstallError(f"symlink destination component is not allowed: {current}")
        if current.exists() and current != path and not current.is_dir():
            raise InstallError(f"destination parent is not a directory: {current}")


def command(arguments: list[str]) -> str:
    return shlex.join(arguments)


def console_instructions(root: Path, slot: str, url: str, common: str) -> bytes:
    client = root / ".arena" / "bin" / "arena_client.py"
    token = root / ".arena" / "slot.token"
    journal = root / ".arena" / "client-state"
    smoke = root / ".arena" / "bin" / "arena_smoke.py"
    arguments = [str(client), "--api-url", url, "--token-file", str(token),
                 "--state-dir", str(journal)]
    values = {"SLOT_ROOT": str(root), "ENGINE_URL": url, "CLIENT": str(client),
              "TOKEN_FILE": str(token), "JOURNAL_DIR": str(journal), "SLOT": slot}
    # Supply concrete values without making the prose's generic example an unsafe
    # shell command when the real directory contains spaces or apostrophes.
    common = common.replace(
        "python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR assignment --match MATCH_ID --slot SLOT",
        "Use the shell-specific assignment command below after receiving the actual match ID.")
    header = f"""# Console instructions for arena-{slot}

Registered Directory: `{root}`
Slot: `{slot}`. Keep this agent out of the other contender's build room.
No match has been selected by this installer. Wait for the human's actual match ID;
replace MATCH_ID_PROVIDED_BY_OPERATOR below before running assignment commands.
Do not interpret that placeholder as an assignment or create a match yourself.

Runtime values (paths only; no credential contents):
"""
    header += "\n".join(f"- `{key}` = `{value}`" for key, value in values.items())
    footer = "\n\n## Commands on this runtime host\n\n"
    footer += "Run from the registered Directory. These commands require a POSIX shell; request OS-specific instructions if this host uses another shell:\n\n```sh\n"
    footer += "cd -- " + shlex.quote(str(root)) + "\n"
    footer += command(["python3", str(smoke), "--expected-root", str(root)]) + "\n"
    footer += command(["python3", *arguments, "assignment", "--match", "MATCH_ID_PROVIDED_BY_OPERATOR", "--slot", slot]) + "\n```\n"
    footer += "\nThe helper output alone proves only a local command. A native smoke passes only after an actual human-addressed Switch request, native execution and observed room reply. This installer never records a native smoke pass.\n"
    return (header + "\n\n" + common + footer).encode("utf-8")


def plan_install(state_dir: Path, url: str, replace: bool = False,
                 repository: Path | None = None) -> tuple[list[dict], dict[str, str]]:
    no_symlinks(state_dir)
    if not state_dir.is_dir():
        raise InstallError("--state-dir must be an existing engine state directory")
    repository = repository or Path(__file__).resolve().parents[1]
    source_paths = [repository / "switch_bridge" / "arena_client.py",
                    repository / "switch" / "arena_smoke.py"]
    prompt_root = repository / "switch" / "prompts"
    prompt_paths = sorted(prompt_root.glob("*.md"))
    if not prompt_paths or not (prompt_root / "common.md").is_file():
        raise InstallError("Role B prompt sources are missing")
    for path in [*source_paths, *prompt_paths]:
        if path.is_symlink() or not path.is_file():
            raise InstallError(f"Role B source must be a regular file: {path.name}")
    sources = {path: path.read_bytes() for path in [*source_paths, *prompt_paths]}
    common = sources[prompt_root / "common.md"].decode("utf-8")
    slots: dict[str, str] = {}
    plans = []
    for slot in ("a", "b"):
        root = state_dir / "workers" / slot
        checkout = root / "worktree"
        arena = root / ".arena"
        for path in [root, checkout, checkout / ".git", arena, arena / "slot.token"]:
            no_symlinks(path)
        if not root.is_dir() or not checkout.is_dir() or not (checkout / ".git").exists():
            raise InstallError(f"slot {slot} needs an existing engine-provisioned root and Git worktree")
        if not arena.is_dir() or not stat.S_ISREG((arena / "slot.token").stat().st_mode):
            raise InstallError(f"slot {slot} needs the engine-provisioned .arena/slot.token file")
        slots[slot] = str(root)
        files = [(arena / "bin" / source.name, sources[source]) for source in source_paths]
        files += [(arena / "prompts" / source.name, sources[source]) for source in prompt_paths]
        files.append((arena / "console-instructions.md", console_instructions(root, slot, url, common)))
        for destination, content in files:
            no_symlinks(destination)
            if destination.exists() and not destination.is_file():
                raise InstallError(f"Role B destination is not a regular file: {destination}")
            action = "create"
            if destination.exists():
                action = "unchanged" if destination.read_bytes() == content else "replace"
                if action == "replace" and not replace:
                    raise InstallError(f"existing Role B file differs; inspect it and use --replace if intended: {destination}")
            plans.append({"path": destination, "content": content, "action": action})
    return plans, slots


def install(state_dir: Path, url: str, *, check: bool = False, replace: bool = False,
            repository: Path | None = None) -> dict:
    url = api_url(url)
    plans, slots = plan_install(state_dir, url, replace, repository)
    # Both roots and every conflict are checked before the first mkdir/write.
    if not check:
        for item in plans:
            if item["action"] == "unchanged":
                continue
            destination = item["path"]
            no_symlinks(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".arena-install-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(item["content"])
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(0o644)
                no_symlinks(destination)
                os.replace(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return {"mode": "check" if check else "installed", "api_url": url,
            "state_dir": str(state_dir), "slot_roots": slots,
            "slots": {slot: {"root": root, "instructions_file": str(Path(root) / ".arena" / "console-instructions.md")} for slot, root in slots.items()},
            "shell_commands_use": "POSIX",
            "native_smoke": "not_run", "credentials_read": False,
            "files": [{"path": str(item["path"]), "action": item["action"],
                       "sha256": hashlib.sha256(item["content"]).hexdigest()} for item in plans]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--check", action="store_true", help="preflight only; do not create or replace files")
    parser.add_argument("--replace", action="store_true", help="permit replacement of changed Role B files after inspection")
    args = parser.parse_args(argv)
    try:
        result = install(args.state_dir, args.api_url, check=args.check, replace=args.replace)
    except (InstallError, OSError, UnicodeError) as exc:
        print(json.dumps({"error": str(exc), "native_smoke": "not_run"}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
