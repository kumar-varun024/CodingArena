#!/usr/bin/env python3
"""Run the frozen booking task-pack fixtures in restricted Docker containers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "fixtures" / "booking-v1"
DRIVER = ROOT / "engine" / "arena_engine" / "driver.py"
DEFAULT_IMAGE = "python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54"
SCENARIO_TIMEOUT = 10
DOCKER_COMMAND_TIMEOUT = 15


class CheckError(RuntimeError):
    """A missing prerequisite or an unexpected fixture outcome."""

    counts: dict[str, int] | None = None


def _copy_snapshot(source: Path, destination: Path) -> None:
    """Copy a trusted pack file before execution so later edits cannot affect it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _read_cases(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read fixture {path.name}: {type(exc).__name__}") from exc
    if type(value) is not list or not value:
        raise CheckError(f"fixture {path.name} must be a non-empty array")
    for entry in value:
        if type(entry) is not dict or type(entry.get("check_id")) is not str or type(entry.get("scenario")) is not dict:
            raise CheckError(f"fixture {path.name} has an invalid entry")
    return value


def _copy_pack_snapshot(snapshot: Path) -> dict[str, Path]:
    files = {
        "driver": DRIVER,
        "reference": PACK / "reference" / "booking.py",
        "known_good": PACK / "known-good" / "booking.py",
        "known_bad_group": PACK / "known-bad" / "group_partial_mutation.py",
        "known_bad_cancel": PACK / "known-bad" / "repeat_cancel.py",
        "public": PACK / "public_cases" / "public_cases.json",
        "held_out": PACK / "held_out_cases" / "held_out_cases.json",
        "bad_group_case": PACK / "known-bad" / "scenarios" / "group_partial_mutation.json",
        "bad_cancel_case": PACK / "known-bad" / "scenarios" / "repeat_cancel.json",
    }
    copied: dict[str, Path] = {}
    for label, source in files.items():
        if not source.is_file():
            raise CheckError(f"required fixture is missing: {source.relative_to(ROOT)}")
        basename = "booking.py" if label in {
            "reference", "known_good", "known_bad_group", "known_bad_cancel"
        } else source.name
        target = snapshot / label / basename
        _copy_snapshot(source, target)
        copied[label] = target
    return copied


def _docker(image: str, args: list[str], *, input_data: bytes | None = None, timeout: int = DOCKER_COMMAND_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["docker", *args], input=input_data, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise CheckError("Docker CLI is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError("Docker command timed out") from exc


def _docker_available(image: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=DOCKER_COMMAND_TIMEOUT, check=False,
        )
    except FileNotFoundError as exc:
        raise CheckError("Docker CLI is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError("Docker image inspection timed out") from exc
    if result.returncode:
        raise CheckError(f"Docker image is unavailable: {image}")


def _container_result(
    image: str, candidate: Path, driver: Path,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = f"arena-fixture-{uuid.uuid4().hex[:20]}"
    command = [
        "--name", name,
        *( ["--interactive"] if scenario is not None else []),
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--user", "65534:65534",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--cpus", "1",
        "--memory", "128m",
        "--pids-limit", "32",
        "--mount", f"type=bind,src={driver.parent},dst=/trusted,readonly",
        "--mount", f"type=bind,src={candidate.parent},dst=/candidate,readonly",
        "--pull=never",
        image,
    ]
    if scenario is None:
        command += ["python", "-I", "/trusted/driver.py", "/candidate/booking.py", "--check-instance-isolation"]
    else:
        command += ["python", "-I", "/trusted/driver.py", "/candidate/booking.py"]
    created = False
    try:
        create = _docker(image, ["create", *command])
        if create.returncode:
            detail = create.stderr.decode("utf-8", "replace").strip().splitlines()
            raise CheckError("Docker container creation failed" + (f": {detail[-1][:200]}" if detail else ""))
        created = True
        try:
            started = _docker(
                image, ["start", "--attach", *( ["--interactive"] if scenario is not None else []), name],
                input_data=(json.dumps(scenario, separators=(",", ":")) + "\n").encode("utf-8") if scenario is not None else None,
                timeout=SCENARIO_TIMEOUT,
            )
        except CheckError as exc:
            if "timed out" in str(exc):
                raise CheckError("scenario container timed out") from exc
            raise
        if started.returncode not in (0, 1):
            raise CheckError(f"Docker container execution failed (exit {started.returncode})")
        try:
            result = json.loads(started.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckError("driver returned invalid JSON") from exc
        if (
            type(result) is not dict
            or set(result) != {"passed", "failed_step", "summary"}
            or type(result["passed"]) is not bool
            or (result["failed_step"] is not None and type(result["failed_step"]) is not int)
            or type(result["summary"]) is not str
        ):
            raise CheckError("driver returned an invalid result shape")
        if started.returncode != (0 if result["passed"] else 1):
            raise CheckError("driver exit status did not match its result")
        return result
    finally:
        # `docker start` may time out after the client exits; force-remove by name
        # even in that case so no candidate container is left running.
        try:
            removed = subprocess.run(
                ["docker", "rm", "--force", name], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=DOCKER_COMMAND_TIMEOUT, check=False,
            )
            if created and removed.returncode:
                raise CheckError("could not remove fixture container")
        except FileNotFoundError as exc:
            if created:
                raise CheckError("Docker CLI disappeared before container cleanup") from exc
        except subprocess.TimeoutExpired as exc:
            if created:
                raise CheckError("timed out removing fixture container") from exc


def run_check(image: str = DEFAULT_IMAGE) -> dict[str, int]:
    counts = {"executed": 0, "expected_pass": 0, "expected_fail": 0, "unexpected": 0}
    try:
        _docker_available(image)
        with tempfile.TemporaryDirectory(prefix="arena-task-pack-") as temporary:
            snapshot = Path(temporary)
            files = _copy_pack_snapshot(snapshot)
            public = _read_cases(files["public"])
            held_out = _read_cases(files["held_out"])
            good_cases = public + held_out

            def verify(label: str, source: Path, case: dict[str, Any], pass_expected: bool, failed_step: int | None = None) -> None:
                result = _container_result(image, source, files["driver"], case["scenario"])
                counts["executed"] += 1
                if result["passed"] is pass_expected and (pass_expected or result["failed_step"] == failed_step):
                    counts["expected_pass" if pass_expected else "expected_fail"] += 1
                    return
                raise CheckError(
                    f"{label}/{case['check_id']} unexpected result: passed={result['passed']}, "
                    f"failed_step={result['failed_step']}, summary={result['summary']}"
                )

            for label in ("reference", "known_good"):
                for case in good_cases:
                    verify(label, files[label], case, True)
                isolation = _container_result(image, files[label], files["driver"])
                counts["executed"] += 1
                if isolation["passed"]:
                    counts["expected_pass"] += 1
                else:
                    raise CheckError(f"{label}/BOOK-07 isolation unexpected result: {isolation['summary']}")
            bad_group = json.loads(files["bad_group_case"].read_text(encoding="utf-8"))
            bad_cancel = json.loads(files["bad_cancel_case"].read_text(encoding="utf-8"))
            verify("known_bad_group", files["known_bad_group"], bad_group, False, 3)
            verify("known_bad_cancel", files["known_bad_cancel"], bad_cancel, False, 3)
    except CheckError as exc:
        exc.counts = counts
        raise
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="container image (default: pinned Python image)")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", args.image):
        print(json.dumps({"error": "--image must be pinned by a sha256 digest", "executed": 0, "unexpected": 1}, separators=(",", ":")))
        return 1
    try:
        counts = run_check(args.image)
    except CheckError as exc:
        counts = exc.counts or {"executed": 0, "expected_pass": 0, "expected_fail": 0, "unexpected": 0}
        counts["unexpected"] += 1
        print(json.dumps({"error": str(exc), **counts}, separators=(",", ":")))
        return 1
    print(json.dumps(counts, separators=(",", ":")))
    return 0 if counts["unexpected"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
