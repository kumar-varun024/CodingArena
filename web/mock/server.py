#!/usr/bin/env python3
"""Contract 1.1 fixture replay server. Never executes contestant code or tests."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

SPEC = json.loads(Path(__file__).with_name("task_spec.json").read_text())
TOKENS = {"fixture-operator": "operator", "fixture-a": "a", "fixture-b": "b"}
SLOTS = ("a", "b")
TERMINAL = ("completed", "error")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class APIError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def require(condition, status=409, code="INVALID_STATE", message="Action is unavailable in this fixture state"):
    if not condition:
        raise APIError(status, code, message)


def validate_source(source):
    require(isinstance(source, dict) and set(source) == {"kind", "room_id", "message_id", "note"}, 422, "INVALID_INPUT", "source must contain kind, room_id, message_id and note")
    require(source["kind"] in ("switch_context", "unverified_context", "operator_recorded", "fixture"), 422, "INVALID_INPUT", "Unknown source kind")
    require(all(source[k] is None or isinstance(source[k], str) for k in ("room_id", "message_id", "note")), 422, "INVALID_INPUT", "Source context must be string or null")


def validate_scenario(scenario):
    require(isinstance(scenario, dict) and set(scenario) == {"capacity", "steps"}, 422, "INVALID_INPUT", "Scenario requires capacity and steps")
    require(type(scenario["capacity"]) is int and 1 <= scenario["capacity"] <= 20, 422, "INVALID_INPUT", "capacity must be integer 1..20")
    steps = scenario["steps"]
    require(isinstance(steps, list) and 1 <= len(steps) <= 30, 422, "INVALID_INPUT", "Scenario needs 1..30 steps")
    arities = {"book": 2, "cancel": 1, "available": 0, "reservations": 0}
    for step in steps:
        require(isinstance(step, dict) and set(step) == {"op", "args", "expected"}, 422, "INVALID_INPUT", "Step requires op, args and expected")
        require(isinstance(step["op"], str) and step["op"] in arities, 422, "INVALID_INPUT", "Unknown operation")
        require(isinstance(step["args"], list) and len(step["args"]) == arities[step["op"]], 422, "INVALID_INPUT", "Incorrect argument count")
        expected = step["expected"]
        require(type(expected) in (bool, int, dict), 422, "INVALID_INPUT", "Expected values must be boolean, integer or reservation mapping")
        if isinstance(expected, dict):
            require(all(isinstance(k, str) and type(v) is int for k, v in expected.items()), 422, "INVALID_INPUT", "Expected reservation values must be integers")
        # Business-invalid IDs/seats, including bool and null, remain legal JSON arguments.


class FixtureStore:
    def __init__(self, state_path=None):
        self.lock = threading.RLock()
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and self.state_path.exists():
            self.data = json.loads(self.state_path.read_text())
        else:
            self.data = {"matches": {}, "jobs": {}, "job_meta": {}, "artifacts": {}, "events": {}, "journal": {}, "submitted": [], "counter": 0, "created_active": None}
            self.seed()

    def save(self):
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(canonical(self.data))
            temporary.replace(self.state_path)

    def ident(self, kind):
        self.data["counter"] += 1
        return f"{kind}-fixture-{self.data['counter']}"

    def evidence_key(self, match, candidate):
        return {"candidate_digest": candidate["tree_digest"], "runner_digest": digest("fixture-runner-replay-not-execution"), "spec_digest": match["spec_digest"], "suite_digest": match["suite_digest"]}

    def event(self, match, event_type, actor="engine", data=None, slot=None):
        events = self.data["events"].setdefault(match["match_id"], [])
        events.append({"seq": len(events) + 1, "at": now(), "actor": "slot_" + actor if actor in SLOTS else actor, "type": event_type, "data": data or {"note": "Deterministic fixture replay; no code executed"}, "_slot": slot})
        match["updated_at"] = now()

    def artifact(self, match, kind, content, slot=None, content_type="text/plain; charset=utf-8"):
        ident = self.ident(kind)
        self.data["artifacts"][ident] = {"match_id": match["match_id"], "slot": slot, "content": content, "content_type": content_type, "filename": ident + (".json" if content_type == "application/json" else ".txt")}
        return ident

    def verification(self, match, candidate, status="passed", kind="verification"):
        job_id = self.ident("job")
        log = self.artifact(match, "log", "FIXTURE REPLAY: these check counts and failures are synthetic. No candidate code or test suite was executed.\n", candidate["slot"])
        checks = (5 if kind == "practice" else 8) + len({c["regression_digest"] for c in match["challenges"] if c["disposition"] == "accepted"})
        result = {"status": status, "job_id": job_id, "check_count": checks, "passed_count": checks if status == "passed" else (0 if status == "error" else checks - 1), "failed_check_ids": ["BOOK-04-repeat-cancel"] if status == "failed" else [], "evidence_key": self.evidence_key(match, candidate), "log_artifact_id": log}
        if kind == "practice":
            result["evidence_key"]["suite_digest"] = digest(["fixture-practice", match["suite_digest"]])
        job = {"job_id": job_id, "match_id": match["match_id"], "kind": kind, "status": "error" if status == "error" else "completed", "candidate_id": None if kind == "practice" else candidate["candidate_id"], "challenge_id": None, "result": result, "error": {"code": "RUNNER_UNAVAILABLE", "message": "Fixture replay of runner failure", "details": {}} if status == "error" else None}
        self.data["jobs"][job_id] = job
        self.data["job_meta"][job_id] = {"slot": candidate["slot"]}
        return copy.deepcopy(result)

    def candidate(self, match, slot, status="passed", revision=1, commit=None):
        ident = f"{match['match_id']}-{slot}-r{revision}"
        eligibility = ("eligible" if match["phase"] == "decision" else "pending") if status == "passed" else ("unknown" if status == "error" else "ineligible")
        candidate = {"candidate_id": ident, "slot": slot, "revision": revision, "commit_sha": commit or digest([ident, "fixture-commit"])[:40], "tree_digest": digest([ident, "fixture-tree"]), "eligibility": eligibility}
        candidate["verification"] = self.verification(match, candidate, status)
        return candidate

    def blank_match(self, ident, phase="building", labels=None, rounds=2, budget=10):
        return {"match_id": ident, "task_id": "booking-v1", "mode": "fixture", "phase": phase, "repair_round": 0, "max_repair_rounds": rounds, "provider_labels": labels or {"a": None, "b": None}, "spec_digest": digest(SPEC), "suite_digest": digest("fixture-public-heldout-baseline"), "slots": {s: {"candidate": None, "review_complete": False} for s in SLOTS}, "challenges": [], "jobs": [], "outcome": None, "created_at": now(), "updated_at": now(), "_budget": budget, "_revealed": phase != "building"}

    def seed(self):
        for name, phase in (("building", "building"), ("reviewing", "reviewing"), ("pending", "reviewing"), ("repair", "repairing"), ("decision", "decision"), ("neither", "decision"), ("stale", "decision"), ("error", "decision")):
            match = self.blank_match("fixture-" + name, phase)
            self.data["matches"][match["match_id"]] = match
            self.event(match, "fixture.loaded", data={"scenario": name, "note": "Synthetic replay state; no live agent or runner results"})
            if name != "building":
                for slot in SLOTS:
                    status = "error" if name == "error" else ("failed" if name == "neither" or slot == "a" and name in ("reviewing", "pending", "repair") else "passed")
                    match["slots"][slot]["candidate"] = self.candidate(match, slot, status)
                    match["slots"][slot]["review_complete"] = phase in ("repairing", "decision")
                if name in ("pending", "repair"):
                    challenge = self.new_challenge(match, "b", match["slots"]["a"]["candidate"], SPEC["challenge_example"], "Fixture: repeated cancellation releases capacity twice", ["BOOK-04"])
                    if name == "repair":
                        self.accept_challenge(match, challenge, "Accepted synthetic fixture replay")
                        match["repair_round"] = 1
        self.save()

    def get_match(self, ident):
        require(ident in self.data["matches"], 404, "NOT_FOUND", "Match not found")
        return self.data["matches"][ident]

    def visible(self, match, owner, actor):
        return actor == "operator" or match["_revealed"] or owner is None or actor == owner

    def project_match(self, match, actor):
        result = {k: copy.deepcopy(v) for k, v in match.items() if not k.startswith("_")}
        result["jobs"] = [copy.deepcopy(job) for ident, job in self.data["jobs"].items() if job["match_id"] == match["match_id"] and self.visible(match, self.data["job_meta"][ident]["slot"], actor)]
        if actor in SLOTS and not match["_revealed"]:
            result["slots"]["b" if actor == "a" else "a"]["candidate"] = None
            result["challenges"] = []
        return result

    def new_challenge(self, match, actor, target, scenario, title, requirements):
        ident = self.ident("challenge")
        job_id = self.ident("job")
        recorded = canonical(scenario) == canonical(SPEC["challenge_example"])
        reproduced = recorded and target["slot"] == "a" and target["revision"] == 1
        status = "reproduced" if reproduced else ("not_reproduced" if recorded else "inconclusive")
        summary = "FIXTURE REPLAY: recorded repeated-cancellation mismatch" if reproduced else ("FIXTURE REPLAY: recorded healthy target passes this scenario" if recorded else "FIXTURE: no recorded result for this scenario; use the live engine for execution")
        log = self.artifact(match, "challenge-log", summary + "\nNo code was executed.\n")
        reproduction = {"job_id": job_id, "status": status, "reference_passed": True if recorded else None, "target_failed_twice": reproduced if recorded else None, "actual_summary": summary, "log_artifact_id": log}
        challenge = {"challenge_id": ident, "submitted_by": actor, "target_candidate_id": target["candidate_id"], "title": title, "requirement_ids": requirements, "scenario": copy.deepcopy(scenario), "reproduction": reproduction, "disposition": "rejected" if status == "not_reproduced" else "pending", "decision_reason": "Recorded fixture target passed" if status == "not_reproduced" else None, "regression_digest": None}
        match["challenges"].append(challenge)
        self.data["jobs"][job_id] = {"job_id": job_id, "match_id": match["match_id"], "kind": "challenge", "status": "completed", "candidate_id": target["candidate_id"], "challenge_id": ident, "result": copy.deepcopy(reproduction), "error": None}
        self.data["job_meta"][job_id] = {"slot": actor}
        self.event(match, "challenge.replayed", actor, {"challenge_id": ident, "status": status})
        return challenge

    def accept_challenge(self, match, challenge, reason):
        challenge["disposition"] = "accepted"
        challenge["decision_reason"] = reason
        challenge["regression_digest"] = digest(challenge["scenario"])
        match["suite_digest"] = digest(sorted(c["regression_digest"] for c in match["challenges"] if c["disposition"] == "accepted"))
        for state in match["slots"].values():
            if state["candidate"]:
                state["candidate"]["verification"]["status"] = "stale"
                state["candidate"]["eligibility"] = "pending"

    def full_verify(self, match):
        match["phase"] = "verifying"
        self.event(match, "verification.started")
        for state in match["slots"].values():
            candidate = state["candidate"]
            status = "failed" if candidate["slot"] == "a" and candidate["revision"] == 1 else "passed"
            candidate["verification"] = self.verification(match, candidate, status)
            candidate["eligibility"] = "eligible" if status == "passed" else "ineligible"
        match["phase"] = "decision"
        self.event(match, "verification.replayed", data={"note": "Instant deterministic fixture transition; no tests executed"})

    def dispatch(self, method, path, query, actor, body=None):
        parts = [unquote(p) for p in path.strip("/").split("/")]
        require(parts[:2] == ["api", "v1"], 404, "NOT_FOUND", "Unknown API route")
        route = parts[2:]
        if method == "GET" and route == ["health"]:
            return 200, {"api_version": "1.1", "mode": "fixture", "runner_available": True, "status": "ok"}, None
        require(actor is not None, 401, "UNAUTHORIZED", "Use a documented fixture token")
        if method == "POST":
            require(isinstance(body, dict), 400, "INVALID_INPUT", "JSON body must be an object")
            try:
                UUID(body.get("request_id", ""))
            except (ValueError, TypeError, AttributeError):
                raise APIError(422, "INVALID_INPUT", "request_id must be a UUID")
            validate_source(body.get("source"))
            key = canonical([actor, path, body["request_id"]])
            stored = self.data["journal"].get(key)
            if stored:
                require(stored["body"] == canonical(body), 409, "IDEMPOTENCY_CONFLICT", "request_id already used with another body")
                return stored["status"], copy.deepcopy(stored["response"]), None
            status, response, artifact = self.mutate(route, actor, body)
            self.data["journal"][key] = {"body": canonical(body), "status": status, "response": copy.deepcopy(response)}
            self.save()
            return status, response, artifact
        require(method == "GET", 404, "NOT_FOUND", "Unknown API route")
        if len(route) == 2 and route[0] == "jobs":
            job = self.data["jobs"].get(route[1])
            require(job is not None, 404, "NOT_FOUND", "Job not found")
            match = self.get_match(job["match_id"])
            require(self.visible(match, self.data["job_meta"][route[1]]["slot"], actor), 403, "FORBIDDEN", "Job is private until reveal")
            return 200, copy.deepcopy(job), None
        if len(route) == 2 and route[0] == "artifacts":
            artifact = self.data["artifacts"].get(route[1])
            require(artifact is not None, 404, "NOT_FOUND", "Artifact not found")
            require(self.visible(self.get_match(artifact["match_id"]), artifact["slot"], actor), 403, "FORBIDDEN", "Artifact is private until reveal")
            return 200, None, artifact
        require(len(route) >= 2 and route[0] == "matches", 404, "NOT_FOUND", "Unknown API route")
        match = self.get_match(route[1])
        if len(route) == 2:
            return 200, self.project_match(match, actor), None
        if len(route) == 3 and route[2] == "events":
            try:
                after = int(query.get("after", ["0"])[0])
            except ValueError:
                raise APIError(422, "INVALID_INPUT", "after must be an integer")
            require(after >= 0, 422, "INVALID_INPUT", "after must be nonnegative")
            visible = [e for e in self.data["events"][match["match_id"]] if self.visible(match, e["_slot"], actor)]
            events = [{k: copy.deepcopy(v) for k, v in e.items() if not k.startswith("_")} for e in visible if e["seq"] > after]
            return 200, {"events": events, "next_after": max([after] + [e["seq"] for e in visible])}, None
        if len(route) == 4 and route[2] == "assignments":
            slot = route[3]
            require(slot in SLOTS, 404, "NOT_FOUND", "Slot not found")
            require(actor == "operator" or actor == slot, 403, "FORBIDDEN", "Assignment belongs to another slot")
            target = match["slots"]["b" if slot == "a" else "a"]["candidate"] if match["_revealed"] else None
            assignment = {"match_id": match["match_id"], "slot": slot, "task_id": "booking-v1", "task_text": "FIXTURE task card. Implement BookingSystem according to the recorded BOOK-01..BOOK-07 requirements. Fixture paths are examples; no live workspace is provisioned.", "task_spec": copy.deepcopy(SPEC), "workspace_path": f"/fixture/workers/{slot}/worktree", "base_commit": digest("fixture-base")[:40], "allowed_files": ["src/booking.py"], "public_checks": ["tests/test_booking_public.py"], "public_check_descriptions": ["Fixture public checks: booking, cancellation, capacity and invalid inputs"], "practice_endpoint": f"POST /api/v1/matches/{match['match_id']}/practice", "spec_digest": match["spec_digest"], "suite_digest": match["suite_digest"], "phase": match["phase"], "repair_round": match["repair_round"], "candidate_budget_minutes": match["_budget"], "target_candidate_id": target["candidate_id"] if target else None, "review_path": f"/fixture/workers/{slot}/review/{target['candidate_id']}" if target else None, "accepted_challenges": copy.deepcopy([c for c in match["challenges"] if c["disposition"] == "accepted"]), "provider_labels": copy.deepcopy(match["provider_labels"])}
            return 200, assignment, None
        raise APIError(404, "NOT_FOUND", "Unknown API route")

    def mutate(self, route, actor, body):
        def fields(names):
            require(set(body) == set(names) | {"request_id", "source"}, 422, "INVALID_INPUT", "Unexpected or missing request fields")

        if route == ["matches"]:
            fields(["task_id", "provider_labels", "max_repair_rounds", "candidate_budget_minutes"])
            require(actor == "operator", 403, "FORBIDDEN", "Only the operator can create a match")
            labels = body["provider_labels"]
            require(isinstance(labels, dict) and set(labels) == set(SLOTS) and all(v is None or isinstance(v, str) and bool(v.strip()) for v in labels.values()), 422, "INVALID_INPUT", "provider_labels requires a and b strings or null")
            require(body["task_id"] == "booking-v1" and type(body["max_repair_rounds"]) is int and 0 <= body["max_repair_rounds"] <= 2 and type(body["candidate_budget_minutes"]) is int and body["candidate_budget_minutes"] > 0, 422, "INVALID_INPUT", "Invalid task or match limits")
            active = self.data["created_active"]
            require(not active or self.get_match(active)["phase"] in ("complete", "cancelled"), message="Only one user-created fixture match can be active")
            match = self.blank_match(self.ident("match"), labels=labels, rounds=body["max_repair_rounds"], budget=body["candidate_budget_minutes"])
            self.data["matches"][match["match_id"]] = match
            self.data["created_active"] = match["match_id"]
            self.event(match, "match.created", "operator")
            return 201, self.project_match(match, actor), None
        require(len(route) >= 3 and route[0] == "matches", 404, "NOT_FOUND", "Unknown API route")
        match = self.get_match(route[1])
        require(match["phase"] not in ("complete", "cancelled"), message="Match is terminal")
        command = route[2]
        if len(route) == 3 and command in ("practice", "submissions"):
            fields(["slot", "commit_sha"])
            slot = body["slot"]
            require(slot in SLOTS and actor == slot, 403, "FORBIDDEN", "Only the matching slot can submit/check")
            require(match["phase"] in ("building", "repairing"))
            require(isinstance(body["commit_sha"], str) and re.fullmatch(r"[0-9a-fA-F]{40}", body["commit_sha"]), 422, "INVALID_INPUT", "commit_sha must be a full Git SHA")
            if command == "practice":
                candidate = {"candidate_id": "fixture-practice", "slot": slot, "tree_digest": digest([body["commit_sha"], "fixture-practice"])}
                result = self.verification(match, candidate, "passed", "practice")
                self.event(match, "practice.replayed", actor, {"job_id": result["job_id"]}, slot=slot)
                return 202, {"job_id": result["job_id"]}, None
            submitted_key = f"{match['match_id']}:{slot}:{match['repair_round']}"
            require(submitted_key not in self.data["submitted"], message="Slot already submitted this round")
            self.data["submitted"].append(submitted_key)
            current = match["slots"][slot]["candidate"]
            revision = current["revision"] + 1 if current else 1
            candidate = self.candidate(match, slot, "failed" if slot == "a" and revision == 1 else "passed", revision, body["commit_sha"])
            match["slots"][slot]["candidate"] = candidate
            self.event(match, "candidate.submitted", actor, {"candidate_id": candidate["candidate_id"], "note": "Fixture snapshot; commit was not inspected"}, slot=slot)
            if match["phase"] == "repairing" and all(f"{match['match_id']}:{s}:{match['repair_round']}" in self.data["submitted"] for s in SLOTS):
                self.full_verify(match)
            return 202, {"candidate_id": candidate["candidate_id"], "job_id": candidate["verification"]["job_id"], "tree_digest": candidate["tree_digest"]}, None
        if len(route) == 3 and command == "challenges":
            fields(["target_candidate_id", "title", "requirement_ids", "scenario"])
            require(actor in SLOTS, 403, "FORBIDDEN", "Only contestants submit challenges")
            require(match["phase"] == "reviewing" and not match["slots"][actor]["review_complete"])
            target = match["slots"]["b" if actor == "a" else "a"]["candidate"]
            require(target is not None and target["candidate_id"] == body["target_candidate_id"], 409, "STALE_SNAPSHOT", "Challenge must target current frozen opponent")
            ids = body["requirement_ids"]
            require(isinstance(body["title"], str) and bool(body["title"].strip()) and isinstance(ids, list) and ids and all(isinstance(i, str) and i in SPEC["requirements"] for i in ids) and len(set(ids)) == len(ids), 422, "INVALID_INPUT", "Invalid title or requirement IDs")
            validate_scenario(body["scenario"])
            for challenge in match["challenges"]:
                if challenge["target_candidate_id"] == target["candidate_id"] and canonical(challenge["scenario"]) == canonical(body["scenario"]) and challenge["reproduction"]["status"] not in ("inconclusive", "queued", "running"):
                    return 202, {"challenge_id": challenge["challenge_id"], "job_id": challenge["reproduction"]["job_id"]}, None
            challenge = self.new_challenge(match, actor, target, body["scenario"], body["title"], ids)
            return 202, {"challenge_id": challenge["challenge_id"], "job_id": challenge["reproduction"]["job_id"]}, None
        if len(route) == 5 and command == "reviews" and route[4] == "complete":
            fields(["target_candidate_id"])
            slot = route[3]
            require(slot in SLOTS and actor == slot, 403, "FORBIDDEN", "Only matching slot completes review")
            require(match["phase"] == "reviewing")
            target = match["slots"]["b" if slot == "a" else "a"]["candidate"]
            require(target and target["candidate_id"] == body["target_candidate_id"], 409, "STALE_SNAPSHOT", "Review target is stale")
            match["slots"][slot]["review_complete"] = True
            self.event(match, "review.completed", actor)
            return 200, self.project_match(match, actor), None
        require(actor == "operator", 403, "FORBIDDEN", "Operator token is required")
        if len(route) == 5 and command == "challenges" and route[4] == "decision":
            fields(["disposition", "reason"])
            require(match["phase"] == "reviewing")
            challenge = next((c for c in match["challenges"] if c["challenge_id"] == route[3]), None)
            require(challenge is not None, 404, "NOT_FOUND", "Challenge not found")
            require(challenge["disposition"] == "pending", message="Challenge decision is already resolved")
            require(isinstance(body["reason"], str) and bool(body["reason"].strip()), 422, "INVALID_INPUT", "A reason is required")
            require(body["disposition"] in ("accepted", "rejected"), 422, "INVALID_INPUT", "Invalid disposition")
            require(challenge["reproduction"]["status"] not in ("queued", "running"))
            if body["disposition"] == "accepted":
                require(challenge["reproduction"]["status"] == "reproduced", message="Only reproduced claims may be accepted")
                self.accept_challenge(match, challenge, body["reason"])
            else:
                challenge["disposition"], challenge["decision_reason"] = "rejected", body["reason"]
            self.event(match, "challenge.decided", "operator", {"challenge_id": challenge["challenge_id"], "disposition": body["disposition"]})
            return 200, self.project_match(match, actor), None
        if len(route) == 3 and command == "actions":
            fields(["action", "reason"])
            require(isinstance(body["reason"], str) and bool(body["reason"].strip()), 422, "INVALID_INPUT", "A reason is required")
            action = body["action"]
            if action == "cancel":
                match["phase"] = "cancelled"
            elif action == "reveal":
                require(match["phase"] == "building" and all(state["candidate"] for state in match["slots"].values()))
                match["phase"], match["_revealed"] = "reviewing", True
            elif action in ("start_repair", "finalize"):
                require(match["phase"] in ("reviewing", "decision"))
                require(all(state["review_complete"] for state in match["slots"].values()) and not any(c["disposition"] == "pending" for c in match["challenges"]), message="Both reviews and all challenge dispositions must be resolved")
                if action == "start_repair":
                    require(match["repair_round"] < match["max_repair_rounds"], message="Repair cap reached")
                    match["repair_round"] += 1
                    match["phase"] = "repairing"
                    for state in match["slots"].values():
                        state["candidate"]["eligibility"] = "pending"
                else:
                    self.full_verify(match)
            else:
                raise APIError(422, "INVALID_INPUT", "Unknown action")
            self.event(match, "match." + action, "operator", {"reason": body["reason"]})
            return 200, self.project_match(match, actor), None
        if len(route) == 3 and command == "selection":
            fields(["selection", "candidate_id", "expected_evidence_key", "reason"])
            require(match["phase"] == "decision")
            require(isinstance(body["reason"], str) and bool(body["reason"].strip()), 422, "INVALID_INPUT", "A reason is required")
            selection = body["selection"]
            require(selection in (*SLOTS, "neither"), 422, "INVALID_INPUT", "Invalid selection")
            selected = None
            if selection == "neither":
                require(body["candidate_id"] is None and body["expected_evidence_key"] is None, 422, "INVALID_INPUT", "Neither must use null candidate/evidence")
            else:
                selected = match["slots"][selection]["candidate"]
                if match["match_id"] == "fixture-stale":
                    if not match.get("_stale_triggered"):
                        match["_stale_triggered"] = True
                        match["suite_digest"] = digest([match["suite_digest"], "fixture-concurrent-evidence-change"])
                        for state in match["slots"].values():
                            state["candidate"]["verification"]["status"] = "stale"
                            state["candidate"]["eligibility"] = "pending"
                        self.event(match, "fixture.evidence_changed", data={"note": "Synthetic concurrent evidence change for 409 recovery testing"})
                        self.save()
                    raise APIError(409, "STALE_SNAPSHOT", "Fixture replay: the selected evidence became stale; refresh the match")
                require(selected and selected["candidate_id"] == body["candidate_id"] and selected["eligibility"] == "eligible" and selected["verification"]["status"] == "passed" and selected["verification"]["evidence_key"] == body["expected_evidence_key"] and body["expected_evidence_key"] == self.evidence_key(match, selected), 409, "STALE_SNAPSHOT", "Candidate is not current, eligible and freshly verified")
                require(not any(c["disposition"] == "pending" for c in match["challenges"]) and all(j["status"] in TERMINAL for j in self.data["jobs"].values() if j["match_id"] == match["match_id"]))
            evidence = self.artifact(match, "evidence", canonical({"kind": "fixture_replay", "note": "Synthetic fixture replay, not a live verification result", "match_id": match["match_id"], "selection": selection}), content_type="application/json")
            patch = self.artifact(match, "patch", "# FIXTURE REPLAY ONLY — no executable selected patch is produced by the mock server.\n") if selected else None
            match["outcome"] = {"selection": selection, "reason": body["reason"], "selected_candidate_id": selected["candidate_id"] if selected else None, "patch_artifact_id": patch, "evidence_artifact_id": evidence}
            match["phase"] = "complete"
            self.event(match, "match.selected", "operator", {"selection": selection, "reason": body["reason"]})
            return 200, self.project_match(match, actor), None
        raise APIError(404, "NOT_FOUND", "Unknown API route")


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "CodingArenaFixture/1.1"

    def log_message(self, *_args):
        pass  # Never log Authorization or request bodies.

    def respond(self, status, response=None, artifact=None):
        content = artifact["content"].encode() if artifact else canonical(response).encode()
        self.send_response(status)
        self.send_header("X-Arena-Mode", "fixture")
        self.send_header("Content-Type", artifact["content_type"] if artifact else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if artifact:
            self.send_header("Content-Disposition", f'attachment; filename="{artifact["filename"]}"')
        origin = getattr(self, "headers", {}).get("Origin")
        if origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Expose-Headers", "X-Arena-Mode, Content-Disposition")
        self.end_headers()
        self.wfile.write(content)

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"error": {"code": "INVALID_INPUT" if code == 400 else "NOT_FOUND", "message": "Malformed request" if code == 400 else "Unsupported request", "details": {}}})

    def handle_request(self, method):
        try:
            parsed = urlsplit(self.path)
            body = None
            if method == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    require(0 < length <= 65536, 400, "INVALID_INPUT", "JSON body must be 1..65536 bytes")
                    body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
                except (ValueError, UnicodeError):
                    raise APIError(400, "INVALID_INPUT", "Malformed JSON body")
            authorization = self.headers.get("Authorization", "")
            actor = TOKENS.get(authorization[7:]) if authorization.startswith("Bearer ") else None
            with self.server.store.lock:
                status, response, artifact = self.server.store.dispatch(method, parsed.path, parse_qs(parsed.query), actor, body)
            self.respond(status, response, artifact)
        except APIError as error:
            self.respond(error.status, {"error": {"code": error.code, "message": error.message, "details": error.details}})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("X-Arena-Mode", "fixture")
        origin = self.headers.get("Origin")
        if origin in ("http://127.0.0.1:5173", "http://localhost:5173"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "X-Arena-Mode, Content-Disposition")
        self.end_headers()


def create_server(host="127.0.0.1", port=8766, state_path=None):
    server = ThreadingHTTPServer((host, port), FixtureHandler)
    server.daemon_threads = True
    server.store = FixtureStore(state_path)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--state-file", type=Path, help="Optional persisted fixture mutations/idempotency; omit for fresh replay on restart")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.state_file)
    print(f"FIXTURE REPLAY ONLY: http://{args.host}:{server.server_address[1]}/api/v1 — no agents or candidate tests execute", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
