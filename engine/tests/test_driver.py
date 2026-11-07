import pytest

from arena_engine.driver import (
    run_instance_isolation,
    run_scenario,
    strict_equal,
    validate_scenario,
)


def scenario(steps=None):
    return {
        "capacity": 3,
        "steps": steps or [{"op": "available", "args": [], "expected": 3}],
    }


@pytest.mark.parametrize("capacity", [True, 0, 21, 1.0, None])
def test_rejects_invalid_capacity(capacity):
    value = scenario()
    value["capacity"] = capacity
    with pytest.raises(ValueError):
        validate_scenario(value)


@pytest.mark.parametrize(
    "step",
    [
        {"op": "book", "args": ["x"], "expected": True},
        {"op": "available", "args": [None], "expected": 3},
        {"op": "other", "args": [], "expected": 3},
        {"op": "available", "args": [], "expected": None},
        {"op": "available", "args": [], "expected": 3, "extra": 1},
    ],
)
def test_rejects_malformed_steps(step):
    with pytest.raises(ValueError):
        validate_scenario(scenario([step]))


def test_permits_business_invalid_json_arguments():
    validate_scenario(scenario([
        {"op": "book", "args": [None, False], "expected": False},
        {"op": "cancel", "args": [{}], "expected": False},
    ]))


def test_rejects_oversized_or_deep_arguments():
    with pytest.raises(ValueError):
        validate_scenario(scenario([{"op": "book", "args": ["x", [1] * 300], "expected": False}]))
    nested = 0
    for _ in range(10):
        nested = [nested]
    with pytest.raises(ValueError):
        validate_scenario(scenario([{"op": "book", "args": ["x", nested], "expected": False}]))


def test_strict_equal_is_type_strict_and_structural():
    assert not strict_equal(True, 1)
    assert not strict_equal([1], [True])
    assert strict_equal({"x": [True, 2]}, {"x": [True, 2]})
    assert strict_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert not strict_equal({"a": 1}, {"a": True})


class ToyBooking:
    def __init__(self, capacity):
        self.capacity = capacity
        self.bookings = {}

    def book(self, booking_id, seats):
        if type(booking_id) is not str or not booking_id or type(seats) is not int or seats <= 0:
            return False
        if booking_id in self.bookings or sum(self.bookings.values()) + seats > self.capacity:
            return False
        self.bookings[booking_id] = seats
        return True

    def cancel(self, booking_id):
        if type(booking_id) is not str or not booking_id or booking_id not in self.bookings:
            return False
        del self.bookings[booking_id]
        return True

    def available(self):
        return self.capacity - sum(self.bookings.values())

    def reservations(self):
        return dict(self.bookings)


def test_run_scenario_against_toy_factory():
    value = scenario([
        {"op": "book", "args": ["family", 2], "expected": True},
        {"op": "available", "args": [], "expected": 1},
        {"op": "cancel", "args": ["family"], "expected": True},
        {"op": "reservations", "args": [], "expected": {}},
    ])
    result = run_scenario(ToyBooking, value)
    assert result == {"passed": True, "failed_step": None, "summary": "all scenario steps passed"}


def test_instance_isolation_passes_for_independent_instances():
    assert run_instance_isolation(ToyBooking) == {
        "passed": True,
        "failed_step": None,
        "summary": "instance isolation passed",
    }


def test_instance_isolation_detects_shared_state():
    class SharedBooking(ToyBooking):
        shared_bookings = {}

        def __init__(self, capacity):
            self.capacity = capacity
            self.bookings = self.shared_bookings

    SharedBooking.shared_bookings.clear()
    result = run_instance_isolation(SharedBooking)
    assert result["passed"] is False
    assert result["failed_step"] is None
    assert "second starts" in result["summary"]


def test_candidate_exceptions_are_failures():
    class Broken:
        def __init__(self, capacity):
            pass

        def available(self):
            raise SystemExit(9)

    result = run_scenario(Broken, scenario())
    assert result["passed"] is False
    assert result["failed_step"] == 1
    assert "SystemExit" in result["summary"]


def test_invalid_scenario_shape_returns_failure_result():
    result = run_scenario(ToyBooking, {"capacity": 3, "steps": []})
    assert result["passed"] is False
    assert result["failed_step"] is None
    assert result["summary"].startswith("invalid scenario:")


def test_wrong_expectation_and_boolean_integer_mismatch_fail():
    assert run_scenario(ToyBooking, scenario([
        {"op": "available", "args": [], "expected": 2},
    ]))["passed"] is False
    assert run_scenario(ToyBooking, scenario([
        {"op": "available", "args": [], "expected": True},
    ]))["passed"] is False


def test_cli_validates_input_before_loading_candidate(monkeypatch, capsys):
    import io
    import arena_engine.driver as driver
    monkeypatch.setattr(driver.sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"steps":[]}')))
    def unexpected_import(_path):
        raise AssertionError("candidate must not be loaded for invalid input")
    monkeypatch.setattr(driver, "_load_factory", unexpected_import)
    assert driver.main(["/unused/booking.py"]) == 2
    assert "invalid scenario" in capsys.readouterr().out


def test_cli_internal_isolation_flag(monkeypatch, capsys):
    import json
    import arena_engine.driver as driver
    monkeypatch.setattr(driver, "_load_factory", lambda _path: ToyBooking)
    assert driver.main(["/unused/booking.py", "--check-instance-isolation"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
