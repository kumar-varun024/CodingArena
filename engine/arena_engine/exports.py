"""Build public, downloadable match evidence and selected source patches."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _selected_candidate(match: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    outcome = match.get("outcome")
    if type(outcome) is not dict or outcome.get("selection") not in {"a", "b"}:
        raise ValueError("a selected candidate is required to export a patch")
    slot = outcome["selection"]
    try:
        candidate = match["slots"][slot]["candidate"]
    except (KeyError, TypeError) as exc:
        raise ValueError("selected candidate is missing") from exc
    if type(candidate) is not dict or candidate.get("candidate_id") != outcome.get("selected_candidate_id"):
        raise ValueError("outcome does not identify the current selected candidate")
    if candidate.get("eligibility") != "eligible":
        raise ValueError("selected candidate is not eligible")
    verification = candidate.get("verification")
    key = verification.get("evidence_key") if type(verification) is dict else None
    if type(verification) is not dict or verification.get("status") != "passed" or type(key) is not dict:
        raise ValueError("selected candidate has no passing full verification")
    return candidate, verification


def _patch(source: bytes, base_source: bytes) -> bytes:
    """Produce a git-applicable patch without interpreting candidate source."""
    with tempfile.TemporaryDirectory(prefix="arena-export-") as temp:
        root = Path(temp)
        target = root / "src" / "booking.py"
        target.parent.mkdir()
        target.write_bytes(base_source)
        subprocess.run(["git", "init", "-q", str(root)], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=10)
        subprocess.run(["git", "-C", str(root), "add", "--", "src/booking.py"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Arena Export",
                        "-c", "user.email=arena-export@invalid", "-c", "core.hooksPath=/dev/null",
                        "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "base"], check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=10)
        target.write_bytes(source)
        result = subprocess.run(["git", "-C", str(root), "-c", "core.hooksPath=/dev/null",
                                 "-c", "core.fsmonitor=false", "diff", "--no-ext-diff",
                                 "--no-textconv", "--", "src/booking.py"], check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return result.stdout


def _fixture_source(events: list[dict[str, Any]]) -> bool:
    return any(type(event) is dict
               and type(event.get("data")) is dict
               and type(event["data"].get("source")) is dict
               and event["data"]["source"].get("kind") == "fixture"
               for event in events)


def _coverage_summary(match: dict[str, Any], candidate: dict[str, Any], verification: dict[str, Any],
                      fixture_source: bool) -> str:
    failed = verification.get("failed_check_ids") or []
    checks = f"{verification.get('passed_count', 0)} of {verification.get('check_count', 0)} recorded checks passed"
    if failed:
        checks += "; failed checks: " + ", ".join(map(str, failed))
    limits = ["Passing checks are evidence for this recorded suite, not a guarantee that the code is bug-free."]
    if match.get("mode") == "fixture":
        limits.append("This match used fixture mode; no live Switch match is claimed.")
    if fixture_source and match.get("mode") != "fixture":
        limits.append("Fixture interactions; no live Switch match is claimed.")
    return f"{checks}. " + " ".join(limits)


def _summary(match: dict[str, Any], candidate: dict[str, Any] | None,
             verification: dict[str, Any] | None, fixture_source: bool) -> bytes:
    outcome = match.get("outcome") or {}
    selection = outcome.get("selection", "unknown")
    lines = [f"# Match {match.get('match_id', 'unknown')}", "", f"Selection: **{selection}**."]
    if selection in {"a", "b"} and candidate is not None and verification is not None:
        lines.extend([f"Selected candidate: `{candidate.get('candidate_id', 'unknown')}`.",
                      _coverage_summary(match, candidate, verification, fixture_source)])
    else:
        blockers: list[str] = []
        slots = match.get("slots") if type(match.get("slots")) is dict else {}
        for name in ("a", "b"):
            item = slots.get(name) if type(slots.get(name)) is dict else {}
            current = item.get("candidate") if type(item.get("candidate")) is dict else None
            if current is None:
                blockers.append(f"slot {name}: no current candidate")
                continue
            if current.get("eligibility") in {"unknown", "pending"}:
                blockers.append(f"slot {name}: eligibility {current.get('eligibility')}")
            ver = current.get("verification") if type(current.get("verification")) is dict else {}
            status = ver.get("status", "unknown")
            if status == "stale":
                blockers.append(f"slot {name}: evidence is stale")
            elif status == "failed":
                failures = ver.get("failed_check_ids") or []
                blockers.append(f"slot {name}: failed checks {', '.join(map(str, failures)) or 'unknown'}")
            elif status != "passed" and current.get("eligibility") != "ineligible":
                blockers.append(f"slot {name}: verification {status}")
        if outcome.get("reason"):
            blockers.append(f"decision: {outcome['reason']}")
        lines.extend(["", "No candidate patch is included.", "", "Blockers: " +
                      ("; ".join(blockers) if blockers else "selection is neither or no eligible candidate was selected")])
    if fixture_source and match.get("mode") != "fixture":
        lines.extend(["", "Fixture interactions; no live Switch match is claimed."])
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def build_export(match: dict, events: list[dict], source: bytes | None,
                 base_source: bytes | None) -> dict[str, bytes]:
    """Build evidence and summary; include a patch only for a valid selection."""
    if type(match) is not dict or type(events) is not list:
        raise ValueError("match and events must be canonical objects")
    outcome = match.get("outcome")
    selection = outcome.get("selection") if type(outcome) is dict else None
    candidate: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    if selection in {"a", "b"}:
        candidate, verification = _selected_candidate(match)
        if not isinstance(source, bytes) or not isinstance(base_source, bytes):
            raise ValueError("selected candidate source and frozen base source are required")
        if type(outcome.get("patch_artifact_id")) is not str or not outcome["patch_artifact_id"]:
            raise ValueError("selected outcome must have an allocated patch artifact ID")
    fixture_source = _fixture_source(events)
    evidence = {
        "version": "1.0",
        "match": match,
        "events": events,
        "coverage": {
            "kind": "full_verification" if selection in {"a", "b"} else "recorded_match_evidence",
            "fixture_source": fixture_source,
            "note": ("Recorded check results describe only the named suite and do not establish bug-free code."
                     " Fixture evidence does not establish Switch provenance."),
        },
    }
    artifacts = {"evidence.json": json.dumps(evidence, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":")).encode("utf-8") + b"\n",
                 "summary.md": _summary(match, candidate, verification, fixture_source)}
    if selection in {"a", "b"}:
        assert source is not None and base_source is not None
        artifacts["candidate.patch"] = _patch(source, base_source)
    return artifacts
