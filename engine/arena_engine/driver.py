"""Trusted scenario validation and execution helpers for booking-v1."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


_OPS = {
    "book": 2,
    "cancel": 1,
    "available": 0,
    "reservations": 0,
}
_MAX_NODES = 256
_MAX_DEPTH = 8
_MAX_STRING_LENGTH = 4096


def _bounded_json(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    """Return whether value is small, bounded JSON data (also rejects NaN/Infinity)."""
    if budget is None:
        budget = [_MAX_NODES]
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_DEPTH:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is float:
        # JSON's standard numeric domain excludes non-finite values.
        import math

        return math.isfinite(value)
    if type(value) is str:
        return len(value) <= _MAX_STRING_LENGTH
    if type(value) is list:
        return len(value) <= _MAX_NODES and all(
            _bounded_json(item, depth=depth + 1, budget=budget) for item in value
        )
    if type(value) is dict:
        if len(value) > _MAX_NODES:
            return False
        return all(
            type(key) is str
            and len(key) <= _MAX_STRING_LENGTH
            and _bounded_json(item, depth=depth + 1, budget=budget)
            for key, item in value.items()
        )
    return False


def validate_scenario(scenario: Any) -> None:
    """Validate scenario structure, raising ValueError for malformed input.

    Operation arguments deliberately accept arbitrary bounded JSON values so
    business-invalid IDs and seat counts can be exercised by scenarios.
    """
    if type(scenario) is not dict or set(scenario) != {"capacity", "steps"}:
        raise ValueError("scenario must contain exactly capacity and steps")
    capacity = scenario["capacity"]
    if type(capacity) is not int or not 1 <= capacity <= 20:
        raise ValueError("capacity must be an integer from 1 through 20")
    steps = scenario["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= 30:
        raise ValueError("steps must be an array with 1 through 30 entries")
    if not _bounded_json(scenario):
        raise ValueError("scenario contains unsupported or oversized JSON data")

    for index, step in enumerate(steps):
        if type(step) is not dict or set(step) != {"op", "args", "expected"}:
            raise ValueError(f"step {index + 1} must contain exactly op, args, and expected")
        op = step["op"]
        if type(op) is not str or op not in _OPS:
            raise ValueError(f"step {index + 1} has an unknown operation")
        args = step["args"]
        if type(args) is not list or len(args) != _OPS[op]:
            raise ValueError(f"step {index + 1} has the wrong argument count")
        expected = step["expected"]
        if type(expected) not in (bool, int, dict):
            raise ValueError(f"step {index + 1} has an invalid expected value type")
        if type(expected) is dict and any(
            type(key) is not str or type(value) is not int
            for key, value in expected.items()
        ):
            raise ValueError(f"step {index + 1} expected object must map strings to integers")


def strict_equal(a: Any, b: Any) -> bool:
    """Compare JSON-like values structurally while distinguishing bool and int."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(strict_equal(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b))
    return a == b


def run_scenario(factory: Any, scenario: Any) -> dict[str, Any]:
    """Execute validated steps against one fresh candidate instance."""
    try:
        validate_scenario(scenario)
    except ValueError as exc:
        return {"passed": False, "failed_step": None, "summary": f"invalid scenario: {exc}"}

    try:
        instance = factory(scenario["capacity"])
    except BaseException as exc:
        return {"passed": False, "failed_step": None, "summary": f"constructor raised {type(exc).__name__}"}

    for index, step in enumerate(scenario["steps"], 1):
        try:
            actual = getattr(instance, step["op"])(*step["args"])
            matches = strict_equal(actual, step["expected"])
        except BaseException as exc:
            return {"passed": False, "failed_step": index, "summary": f"{step['op']} raised {type(exc).__name__}"}
        if not matches:
            return {
                "passed": False,
                "failed_step": index,
                "summary": f"{step['op']} returned a value different from expected",
            }
    return {"passed": True, "failed_step": None, "summary": "all scenario steps passed"}


def run_instance_isolation(factory: Any) -> dict[str, Any]:
    """Check BOOK-07 by exercising two independent candidate instances."""
    try:
        first = factory(3)
        second = factory(3)
        checks = (
            ("first book", lambda: first.book("first", 1), True),
            ("second starts available", second.available, 3),
            ("second starts empty", second.reservations, {}),
            ("second book", lambda: second.book("second", 2), True),
            ("first retains only its booking", first.reservations, {"first": 1}),
            ("first availability", first.available, 2),
            ("second retains only its booking", second.reservations, {"second": 2}),
            ("second availability", second.available, 1),
        )
        for label, operation, expected in checks:
            actual = operation()
            if not strict_equal(actual, expected):
                return {"passed": False, "failed_step": None, "summary": f"instance isolation failed: {label}"}
    except BaseException as exc:
        return {"passed": False, "failed_step": None, "summary": f"instance isolation raised {type(exc).__name__}"}
    return {"passed": True, "failed_step": None, "summary": "instance isolation passed"}


def _load_factory(path: str) -> Any:
    candidate_path = Path(path).resolve(strict=True)
    spec = importlib.util.spec_from_file_location("arena_candidate", candidate_path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load candidate module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BookingSystem


def main(argv: list[str] | None = None) -> int:
    """Container CLI: run a scenario or the internal BOOK-07 isolation check."""
    args = sys.argv[1:] if argv is None else argv
    isolation_mode = len(args) == 2 and args[1] == "--check-instance-isolation"
    if not (len(args) == 1 or isolation_mode):
        print(json.dumps({
            "passed": False,
            "failed_step": None,
            "summary": "usage: driver.py CANDIDATE.py [--check-instance-isolation]",
        }))
        return 2
    if not isolation_mode:
        try:
            raw_scenario = sys.stdin.buffer.read(64 * 1024 + 1)
            if len(raw_scenario) > 64 * 1024:
                raise ValueError("scenario input is too large")
            scenario = json.loads(
                raw_scenario,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            validate_scenario(scenario)
        except (ValueError, RecursionError) as exc:
            print(json.dumps({"passed": False, "failed_step": None,
                              "summary": f"invalid scenario: {type(exc).__name__}"}))
            return 2

    try:
        factory = _load_factory(args[0])
    except BaseException as exc:
        result = {"passed": False, "failed_step": None,
                  "summary": f"candidate import raised {type(exc).__name__}"}
    else:
        result = run_instance_isolation(factory) if isolation_mode else run_scenario(factory, scenario)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
