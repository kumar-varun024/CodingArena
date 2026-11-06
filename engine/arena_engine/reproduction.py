"""Trusted, bounded reproduction of a submitted challenge scenario."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .driver import validate_scenario
from .runner import RunnerError


def _checked_result(result: Any) -> bool | None:
    """Accept only the exact one-case verify response shape and types."""
    if type(result) is not dict or set(result) != {
        "check_count", "passed_count", "failed_check_ids", "log"
    }:
        return None
    if (type(result["check_count"]) is not int or type(result["passed_count"]) is not int
            or type(result["failed_check_ids"]) is not list
            or type(result["log"]) is not str
            or any(type(check_id) is not str for check_id in result["failed_check_ids"])):
        return None
    if result["check_count"] != 1 or result["passed_count"] not in (0, 1):
        return None
    ids = result["failed_check_ids"]
    if result["passed_count"] == 1 and ids == []:
        return True
    if result["passed_count"] == 0 and ids == ["CHALLENGE"]:
        return False
    return None


def reproduce(runner: Any, reference_source: Path, target_source: Path,
              scenario: dict, cancel_event: threading.Event | None = None) -> dict:
    """Run a challenge against trusted reference and twice against frozen target."""
    result = {
        "status": "inconclusive", "reference_passed": None,
        "target_failed_twice": None, "actual_summary": "Reproduction inconclusive",
        "log": "reference: NOT RUN\ntarget attempt 1: NOT RUN\ntarget attempt 2: NOT RUN",
    }
    cancellation = cancel_event or threading.Event()
    try:
        validate_scenario(scenario)
    except (ValueError, RecursionError):
        result.update(status="invalid", actual_summary="Scenario is invalid",
                      log="scenario: INVALID")
        return result

    def cancelled() -> bool:
        return cancellation.is_set()

    lines: list[str] = []
    try:
        if cancelled():
            raise RunnerError("Verification cancelled")
        reference = _checked_result(runner.verify(
            Path(reference_source), [{"check_id": "CHALLENGE", "scenario": scenario}],
            include_isolation=False, cancel_event=cancellation,
        ))
        if cancelled():
            raise RunnerError("Verification cancelled")
        if reference is None:
            lines.append("reference: INVALID RESULT")
            result["status"] = "inconclusive"
            result["actual_summary"] = "Runner returned an invalid reference result"
            result["log"] = "\n".join(lines)
            return result
        result["reference_passed"] = reference
        lines.append(f"reference: {'PASS' if reference else 'FAIL'}")
        if not reference:
            result.update(status="invalid", actual_summary="Scenario does not pass the trusted reference",
                          log="\n".join(lines))
            return result

        target_results: list[bool] = []
        for attempt in (1, 2):
            if cancelled():
                raise RunnerError("Verification cancelled")
            passed = _checked_result(runner.verify(
                Path(target_source), [{"check_id": "CHALLENGE", "scenario": scenario}],
                include_isolation=False, cancel_event=cancellation,
            ))
            if cancelled():
                raise RunnerError("Verification cancelled")
            if passed is None:
                lines.append(f"target attempt {attempt}: INVALID RESULT")
                result.update(status="inconclusive", actual_summary="Runner returned an invalid target result",
                              log="\n".join(lines))
                return result
            target_results.append(passed)
            lines.append(f"target attempt {attempt}: {'PASS' if passed else 'FAIL'}")

        result["target_failed_twice"] = target_results == [False, False]
        if target_results == [False, False]:
            result.update(status="reproduced", actual_summary="Target failed both fresh attempts")
        elif target_results == [True, True]:
            result.update(status="not_reproduced", actual_summary="Target passed both fresh attempts")
        else:
            result.update(status="inconclusive", actual_summary="Target results differed between attempts")
        result["log"] = "\n".join(lines)
        return result
    except Exception:
        # Infrastructure errors, cancellation, and unexpected runner failures are
        # never evidence of a target defect.
        lines.append("reproduction: INCONCLUSIVE")
        result.update(status="inconclusive", actual_summary="Runner failed or reproduction was cancelled",
                      log="\n".join(lines))
        return result
