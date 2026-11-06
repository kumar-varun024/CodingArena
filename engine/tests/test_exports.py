import json
import subprocess

import pytest

from arena_engine.exports import build_export


def _candidate(status="passed", eligibility="eligible", failures=None):
    return {
        "candidate_id": "cand-a",
        "eligibility": eligibility,
        "verification": {
            "status": status,
            "check_count": 3,
            "passed_count": 3 - len(failures or []),
            "failed_check_ids": failures or [],
            "evidence_key": {"candidate_digest": "sha256:x", "runner_digest": "sha256:y",
                             "spec_digest": "sha256:z", "suite_digest": "sha256:q"},
        },
    }


def _match(selection="a", candidate=None):
    candidate = candidate or _candidate()
    return {
        "match_id": "match-1",
        "mode": "fixture",
        "phase": "complete",
        "task_id": "booking-v1",
        "slots": {"a": {"candidate": candidate, "review_complete": True},
                  "b": {"candidate": None, "review_complete": True}},
        "outcome": {"selection": selection, "selected_candidate_id": "cand-a" if selection == "a" else None,
                    "evidence_artifact_id": "evidence-1",
                    "patch_artifact_id": "patch-1" if selection == "a" else None,
                    "reason": "recorded decision"},
    }


def _apply_patch(tmp_path, base, patch):
    repo = tmp_path / "fresh"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "booking.py").write_bytes(base)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "src/booking.py"], check=True)
    patch_file = tmp_path / "candidate.patch"
    patch_file.write_bytes(patch)
    subprocess.run(["git", "-C", str(repo), "apply", "--allow-empty", str(patch_file)], check=True)
    return (repo / "src" / "booking.py").read_bytes()


def test_selected_patch_applies_exact_bytes_without_final_newline(tmp_path):
    base = b"# coding: latin-1\nclass BookingSystem:\n    pass"
    source = b"# coding: latin-1\n# caf\xe9\nclass BookingSystem:\n    pass\n"
    exported = build_export(_match(), [], source, base)
    assert set(exported) == {"evidence.json", "summary.md", "candidate.patch"}
    assert _apply_patch(tmp_path, base, exported["candidate.patch"]) == source


def test_identical_selected_source_has_valid_empty_patch(tmp_path):
    base = b"# coding: latin-1\nclass BookingSystem: pass"
    exported = build_export(_match(), [], base, base)
    assert exported["candidate.patch"] == b""
    assert _apply_patch(tmp_path, base, exported["candidate.patch"]) == base


def test_neither_exports_no_patch_or_source_and_reports_blockers():
    match = _match("neither", _candidate("failed", "ineligible", ["BOOK-02", "BOOK-06"]))
    events = [{"seq": 1, "type": "finalized"}]
    exported = build_export(match, events, b"secret candidate", b"hidden base")
    assert set(exported) == {"evidence.json", "summary.md"}
    evidence = json.loads(exported["evidence.json"])
    assert evidence["version"] == "1.0"
    assert evidence["match"] == match
    assert evidence["events"] == events
    assert "secret candidate" not in exported["evidence.json"].decode()
    assert "hidden base" not in exported["evidence.json"].decode()
    assert "BOOK-02, BOOK-06" in exported["summary.md"].decode()


def test_selected_export_requires_eligible_fresh_passing_candidate():
    for candidate in (_candidate("stale"), _candidate("passed", "unknown"),
                      {**_candidate(), "verification": {"status": "passed"}},
                      {**_candidate(), "verification": None}):
        with pytest.raises(ValueError):
            build_export(_match(candidate=candidate), [], b"src", b"base")


def test_selected_export_requires_source_and_allocated_artifact_id():
    with pytest.raises(ValueError):
        build_export(_match(), [], None, b"base")
    match = _match()
    match["outcome"]["patch_artifact_id"] = None
    with pytest.raises(ValueError):
        build_export(match, [], b"src", b"base")


def test_fixture_event_is_reported_even_when_runtime_mode_is_live():
    match = _match()
    match["mode"] = "live"
    events = [{"seq": 1, "type": "match_created",
               "data": {"source": {"kind": "fixture", "room_id": None, "message_id": None}}}]
    exported = build_export(match, events, b"src", b"base")
    evidence = json.loads(exported["evidence.json"])
    assert evidence["match"]["mode"] == "live"
    assert evidence["coverage"]["fixture_source"] is True
    assert "Fixture interactions; no live Switch match is claimed." in exported["summary.md"].decode()
