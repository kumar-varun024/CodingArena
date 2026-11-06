#!/usr/bin/env python3
"""Harmless local command for an observed native Switch smoke, without credentials."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-root", type=Path, help="Expected registered slot directory")
    args = parser.parse_args()
    actual = Path.cwd().resolve()
    expected = args.expected_root.resolve() if args.expected_root else None
    matches = actual == expected if expected else None
    result = {
        "kind": "local_command_smoke",
        "status": "directory_mismatch" if matches is False else "command_completed",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "working_directory": str(actual),
        "expected_root": str(expected) if expected else None,
        "directory_matches_expected": matches,
        "python_version": platform.python_version(),
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Local command only; no engine, model identity, or native room round trip verified.",
    }
    print(json.dumps(result, sort_keys=True))
    return 1 if matches is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
