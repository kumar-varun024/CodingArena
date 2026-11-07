import threading

import pytest

from arena_engine.reproduction import reproduce
from arena_engine.runner import RunnerError


SCENARIO = {"capacity": 2, "steps": [
    {"op": "book", "args": ["x", 1], "expected": True},
]}
REFERENCE = "trusted-reference.py"
TARGET = "frozen-target.py"


def response(passed):
    return {"check_count": 1, "passed_count": int(passed),
            "failed_check_ids": [] if passed else ["CHALLENGE"],
            "log": "CHALLENGE: PASS" if passed else "CHALLENGE: FAIL"}


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def verify(self, source, scenarios, include_isolation, cancel_event=None):
        self.calls.append((source, scenarios, include_isolation, cancel_event))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_reproduces_only_after_two_fresh_target_failures():
    runner = FakeRunner([response(True), response(False), response(False)])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome == {
        "status": "reproduced", "reference_passed": True,
        "target_failed_twice": True, "actual_summary": "Target failed both fresh attempts",
        "log": "reference: PASS\ntarget attempt 1: FAIL\ntarget attempt 2: FAIL",
    }
    assert len(runner.calls) == 3
    for source, cases, isolation, _ in runner.calls:
        assert str(source) in (REFERENCE, TARGET)
        assert cases == [{"check_id": "CHALLENGE", "scenario": SCENARIO}]
        assert isolation is False


@pytest.mark.parametrize(("target", "status", "failed_twice"), [
    ([True, True], "not_reproduced", False),
    ([False, True], "inconclusive", False),
    ([True, False], "inconclusive", False),
])
def test_target_outcomes(target, status, failed_twice):
    runner = FakeRunner([response(True), *(response(value) for value in target)])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome["status"] == status
    assert outcome["target_failed_twice"] is failed_twice


def test_reference_failure_is_invalid_and_never_runs_target():
    runner = FakeRunner([response(False)])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome["status"] == "invalid"
    assert outcome["reference_passed"] is False
    assert outcome["target_failed_twice"] is None
    assert len(runner.calls) == 1


def test_malformed_scenario_is_invalid_without_runner_call():
    runner = FakeRunner([])
    outcome = reproduce(runner, REFERENCE, TARGET, {"capacity": True, "steps": []})
    assert outcome["status"] == "invalid"
    assert runner.calls == []


@pytest.mark.parametrize("garbage", [
    {"check_count": True, "passed_count": 0, "failed_check_ids": ["CHALLENGE"], "log": ""},
    {"check_count": 1, "passed_count": False, "failed_check_ids": ["CHALLENGE"], "log": ""},
    {"check_count": 1, "passed_count": 0, "failed_check_ids": ["OTHER"], "log": ""},
    {"check_count": 1, "passed_count": 1, "failed_check_ids": ["CHALLENGE"], "log": ""},
    {"check_count": 1, "passed_count": 0, "failed_check_ids": [], "log": ""},
])
def test_garbage_result_cannot_become_reproduction(garbage):
    runner = FakeRunner([garbage])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome["status"] == "inconclusive"
    assert outcome["target_failed_twice"] is None
    assert len(runner.calls) == 1


def test_malformed_reference_result_is_inconclusive():
    runner = FakeRunner([{
        "check_count": True, "passed_count": 1,
        "failed_check_ids": [], "log": "CHALLENGE: PASS",
    }])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome["status"] == "inconclusive"
    assert outcome["reference_passed"] is None
    assert outcome["target_failed_twice"] is None
    assert len(runner.calls) == 1


def test_cancellation_after_final_target_run_is_inconclusive():
    event = threading.Event()

    class CancellingRunner(FakeRunner):
        def verify(self, source, scenarios, include_isolation, cancel_event=None):
            result = super().verify(source, scenarios, include_isolation, cancel_event)
            if len(self.calls) == 3:
                event.set()
            return result

    runner = CancellingRunner([response(True), response(False), response(False)])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO, event)
    assert outcome["status"] == "inconclusive"
    assert outcome["target_failed_twice"] is None


@pytest.mark.parametrize("error", [RunnerError("docker unavailable"), OSError("broken")])
def test_runner_infrastructure_errors_are_inconclusive(error):
    runner = FakeRunner([response(True), error])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO)
    assert outcome["status"] == "inconclusive"
    assert outcome["reference_passed"] is True
    assert outcome["target_failed_twice"] is None


def test_pre_cancelled_event_is_inconclusive_without_execution():
    event = threading.Event()
    event.set()
    runner = FakeRunner([])
    outcome = reproduce(runner, REFERENCE, TARGET, SCENARIO, event)
    assert outcome["status"] == "inconclusive"
    assert outcome["target_failed_twice"] is None
    assert runner.calls == []


def test_expected_mismatch_fails_reference_without_target_execution():
    mismatch = {"capacity": 2, "steps": [
        {"op": "available", "args": [], "expected": 1},
    ]}
    runner = FakeRunner([response(False)])
    outcome = reproduce(runner, REFERENCE, TARGET, mismatch)
    assert outcome["status"] == "invalid"
    assert outcome["reference_passed"] is False
    assert len(runner.calls) == 1
    assert "expected" not in outcome["log"]
