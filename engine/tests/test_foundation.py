import hashlib
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from arena_engine.api import create_app
from arena_engine.contract import ROOT, CONTRACT_SHA256, canonical_bytes, load_contract
from arena_engine.driver import validate_scenario
from arena_engine.runtime import DEFAULT_IMAGE, Settings, runtime_status


def test_frozen_contract_and_canonical_types(tmp_path):
    contract = load_contract()
    assert hashlib.sha256(canonical_bytes(contract)).hexdigest() == CONTRACT_SHA256
    assert contract["contract_version"] == "1.1"
    assert canonical_bytes({"expected": True}) != canonical_bytes({"expected": 1})
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps({**contract, "contract_version": "2.0"}))
    with pytest.raises(ValueError, match="digest mismatch"):
        load_contract(changed)


def test_health_matches_manifest_and_unknown_route_is_json(tmp_path):
    with TestClient(create_app(settings=Settings(tmp_path / "uninitialized", DEFAULT_IMAGE))) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"api_version": "1.1", "mode": "live",
                                   "runner_available": False, "status": "ok"}
        missing = client.get("/api/v1/unknown-route")
        assert missing.status_code == 404
        assert missing.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found", "details": {}}}


def test_doctor_missing_docker_and_image_readiness_are_not_execution(monkeypatch, tmp_path):
    settings = Settings(tmp_path, DEFAULT_IMAGE)
    def missing(*_args, **_kwargs):
        raise FileNotFoundError("docker missing")
    monkeypatch.setattr(subprocess, "run", missing)
    status = runtime_status(settings)
    assert not status["docker_available"]
    assert not status["image_available"]
    assert not status["runner_available"]
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0))
    status = runtime_status(settings)
    assert status["docker_available"] and status["image_available"]
    assert not status["runner_available"]
    assert not runtime_status(Settings(tmp_path, "python:latest"))["image_available"]


def test_doctor_timeout_is_unavailable(monkeypatch, tmp_path):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("docker", 5)
    monkeypatch.setattr(subprocess, "run", timeout)
    assert not runtime_status(Settings(tmp_path, DEFAULT_IMAGE))["docker_available"]


def test_starter_contains_only_frozen_public_material():
    pack = ROOT / "fixtures" / "booking-v1"
    starter = pack / "starter"
    files = {str(path.relative_to(starter)) for path in starter.rglob("*") if path.is_file()}
    assert files == {"src/booking.py", "SPEC.md", "public_checks.json", "public_cases.json"}
    assert (starter / "SPEC.md").read_bytes() == (pack / "SPEC.md").read_bytes()
    public = pack / "public_cases" / "public_cases.json"
    assert (starter / "public_cases.json").read_bytes() == public.read_bytes()
    cases = json.loads(public.read_text()) + json.loads(
        (pack / "held_out_cases" / "held_out_cases.json").read_text())
    assert len({case["check_id"] for case in cases}) == len(cases)
    for case in cases:
        validate_scenario(case["scenario"])
