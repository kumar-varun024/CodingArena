"""Review, common regression suite, repair and human selection operations."""

import hashlib
import json
import os
from pathlib import Path

from .contract import ROOT
from .domain import digest, now, uid, verification
from .errors import ArenaError
from .exports import build_export
from .runner import RunnerError
from .workspaces import WorkspaceError, freeze, _git


class Workflow:
    def _pin_legacy_baseline(self, match):
        if "_baseline_checks" in match:
            return
        initial = digest({"checks": self.full, "instance_isolation": True, "regressions": []})
        if match["challenges"] or match["suite_digest"] != initial:
            raise ArenaError("INVALID_STATE", "Legacy task checks changed; cancel and create a new match")
        match["_baseline_checks"] = self.full
        match["_public_cases"] = json.loads(_git(self.settings.state_dir / "task-base", "show",
            self.runtime["base_commit"] + ":public_cases.json").stdout)

    def _regressions(self, match):
        unique = {c["regression_digest"]: c["scenario"] for c in match["challenges"]
                  if c["disposition"] == "accepted"}
        return [{"check_id": "REG-" + key, "scenario": unique[key]} for key in sorted(unique)]

    def _checks(self, match, practice=False):
        self._pin_legacy_baseline(match)
        base = match.get("_public_cases", self.public) if practice else match.get("_baseline_checks", self.full)
        return base + self._regressions(match)

    def _suite(self, match, practice=False):
        self._pin_legacy_baseline(match)
        regressions = self._regressions(match)
        if practice:
            return digest({"kind": "practice", "checks": match.get("_public_cases", self.public), "regressions": regressions})
        return digest({"checks": match.get("_baseline_checks", self.full), "instance_isolation": True, "regressions": regressions})

    def _runner_identity(self):
        if self.worker_failed or not self.runner.available():
            raise ArenaError("RUNNER_UNAVAILABLE", "Docker verification runner is unavailable", 503)
        try:
            return self.runner.digest
        except (RunnerError, OSError) as exc:
            raise ArenaError("RUNNER_UNAVAILABLE", "Runner identity is unavailable", 503) from exc

    def _candidate_source(self, db, candidate):
        row = db.execute("SELECT internal FROM jobs WHERE job_id=?", (candidate["verification"]["job_id"],)).fetchone()
        if row is None:
            raise ArenaError("INVALID_STATE", "Candidate source record is missing")
        return json.loads(row["internal"])["source"]

    def _queue(self, db, match, slot, source, tree_digest, runner_digest, candidate_id=None, practice=False):
        job_id = uid("job")
        job = {"job_id": job_id, "match_id": match["match_id"], "kind": "practice" if practice else "verification",
               "candidate_id": candidate_id, "challenge_id": None, "status": "queued", "result": None, "error": None}
        internal = {"source": source, "candidate_digest": tree_digest, "runner_digest": runner_digest,
                    "spec_digest": match["spec_digest"], "suite_digest": self._suite(match, practice),
                    "checks": self._checks(match, practice), "include_isolation": not practice}
        self.store.save_job(db, job, internal, slot)
        return job_id

    def submit_candidate(self, actor, match_id, body, practice=False):
        slot = body["slot"]
        self.slot(actor, slot)
        def operation(db):
            match = self._match(db, match_id)
            if match["phase"] not in ("building", "repairing"):
                raise ArenaError("INVALID_STATE", "Submissions and practice require building or repairing")
            previous = match["slots"][slot]["candidate"]
            if not practice and ((match["phase"] == "building" and previous)
                                 or match.get("_repair_submitted", {}).get(slot, False)):
                raise ArenaError("INVALID_STATE", "This slot already submitted in the current round")
            runner_digest = self._runner_identity()
            try:
                snap = freeze(self.settings, slot, body["commit_sha"], uid("snapshot"))
            except WorkspaceError as exc:
                raise ArenaError("STALE_SNAPSHOT", str(exc)) from exc
            candidate_id = None if practice else uid("candidate")
            job_id = self._queue(db, match, slot, snap["path"], snap["tree_digest"], runner_digest, candidate_id, practice)
            if not practice:
                match["slots"][slot]["candidate"] = {"candidate_id": candidate_id, "slot": slot,
                    "revision": previous["revision"] + 1 if previous else 1, "commit_sha": snap["commit_sha"],
                    "tree_digest": snap["tree_digest"], "eligibility": "pending", "verification": verification(job_id=job_id)}
                if match["phase"] == "repairing":
                    match["_repair_submitted"][slot] = True
                    self._stage_review(db, match)
                    if all(match["_repair_submitted"].values()):
                        match["phase"] = "verifying"
            match["updated_at"] = now()
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "practice.queued" if practice else "candidate.submitted",
                        {"job_id": job_id, "candidate_id": candidate_id, "source": body["source"]}, slot, not practice)
            response = {"job_id": job_id}
            if not practice:
                response.update(candidate_id=candidate_id, tree_digest=snap["tree_digest"])
            return response, 202
        endpoint = f"/matches/{match_id}/" + ("practice" if practice else "submissions")
        return self.mutate(actor, endpoint, body, operation)

    def challenge(self, actor, match_id, body):
        if actor not in ("slot_a", "slot_b"):
            raise ArenaError("FORBIDDEN", "A participating slot must submit challenges", 403)
        slot = actor[-1]
        def operation(db):
            match = self._match(db, match_id)
            if match["phase"] != "reviewing" or match["slots"][slot]["review_complete"]:
                raise ArenaError("INVALID_STATE", "Challenge submission requires an open review")
            if "_reference" not in match:
                raise ArenaError("INVALID_STATE", "Legacy match has no frozen reference; cancel and create a new match")
            other = "b" if slot == "a" else "a"
            target = match["slots"][other]["candidate"]
            if body["target_candidate_id"] != target["candidate_id"]:
                raise ArenaError("STALE_SNAPSHOT", "Challenge must target the exact frozen opponent candidate")
            scenario_digest = digest(body["scenario"])
            for existing in match["challenges"]:
                if (existing["target_candidate_id"] == target["candidate_id"]
                        and digest(existing["scenario"]) == scenario_digest
                        and existing["reproduction"]["status"] != "inconclusive"):
                    return {"challenge_id": existing["challenge_id"], "job_id": existing["reproduction"]["job_id"]}, 202
            runner_digest = self._runner_identity()
            challenge_id, job_id = uid("challenge"), uid("job")
            source = self._candidate_source(db, target)
            reference = self.settings.state_dir / "private" / (match_id + "-reference.py")
            reference.parent.mkdir(mode=0o700, exist_ok=True)
            reference_bytes = match.get("_reference", (ROOT / "fixtures/booking-v1/reference/booking.py").read_text()).encode()
            if not reference.exists():
                with reference.open("xb") as stream:
                    stream.write(reference_bytes)
                os.chmod(reference, 0o400)
            if reference.is_symlink() or reference.read_bytes() != reference_bytes:
                raise ArenaError("INVALID_STATE", "Frozen reference identity changed; a new match is required")
            reproduction = {"status": "queued", "job_id": job_id, "reference_passed": None,
                            "target_failed_twice": None, "actual_summary": None, "log_artifact_id": None}
            match["challenges"].append({"challenge_id": challenge_id, "submitted_by": slot,
                "target_candidate_id": target["candidate_id"], "requirement_ids": body["requirement_ids"],
                "title": body["title"], "scenario": body["scenario"], "reproduction": reproduction,
                "disposition": "pending", "decision_reason": None, "regression_digest": None})
            job = {"job_id": job_id, "match_id": match_id, "kind": "challenge", "candidate_id": target["candidate_id"],
                   "challenge_id": challenge_id, "status": "queued", "result": None, "error": None}
            internal = {"source": source, "candidate_digest": target["tree_digest"], "runner_digest": runner_digest,
                        "reference_source": str(reference), "reference_digest": hashlib.sha256(reference_bytes).hexdigest(),
                        "scenario": body["scenario"]}
            self.store.save_job(db, job, internal, slot)
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "challenge.submitted", {"challenge_id": challenge_id, "source": body["source"]})
            return {"challenge_id": challenge_id, "job_id": job_id}, 202
        return self.mutate(actor, f"/matches/{match_id}/challenges", body, operation)

    @staticmethod
    def _find_challenge(match, challenge_id):
        for challenge in match["challenges"]:
            if challenge["challenge_id"] == challenge_id:
                return challenge
        raise ArenaError("NOT_FOUND", "Challenge not found", 404)

    def review_complete(self, actor, match_id, slot, body):
        self.slot(actor, slot)
        def operation(db):
            match = self._match(db, match_id)
            if match["phase"] != "reviewing":
                raise ArenaError("INVALID_STATE", "Review completion requires reviewing phase")
            other = "b" if slot == "a" else "a"
            if body["target_candidate_id"] != match["slots"][other]["candidate"]["candidate_id"]:
                raise ArenaError("STALE_SNAPSHOT", "Review completion must name the exact opponent candidate")
            match["slots"][slot]["review_complete"] = True
            match["updated_at"] = now()
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "review.completed", {"target_candidate_id": body["target_candidate_id"], "source": body["source"]})
            return self._projection(db, match, actor), 200
        return self.mutate(actor, f"/matches/{match_id}/reviews/{slot}/complete", body, operation)

    def adjudicate(self, actor, match_id, challenge_id, body):
        self.operator(actor)
        def operation(db):
            match = self._match(db, match_id)
            if match["phase"] != "reviewing":
                raise ArenaError("INVALID_STATE", "Challenge decisions require reviewing phase")
            challenge = self._find_challenge(match, challenge_id)
            if challenge["disposition"] != "pending" or challenge["reproduction"]["status"] in ("queued", "running"):
                raise ArenaError("INVALID_STATE", "Challenge must be terminal and awaiting a decision")
            if not body["reason"].strip():
                raise ArenaError("INVALID_INPUT", "A meaningful decision reason is required", 422)
            if body["disposition"] == "accepted" and challenge["reproduction"]["status"] != "reproduced":
                raise ArenaError("INVALID_STATE", "Only a reproduced requirement violation may be accepted")
            challenge["disposition"] = body["disposition"]
            challenge["decision_reason"] = body["reason"]
            if body["disposition"] == "accepted":
                challenge["regression_digest"] = digest(challenge["scenario"])
                new_suite = self._suite(match)
                if new_suite != match["suite_digest"]:
                    match["suite_digest"] = new_suite
                    for entry in match["slots"].values():
                        if entry["candidate"]:
                            entry["candidate"]["verification"]["status"] = "stale"
                            entry["candidate"]["eligibility"] = "pending"
            match["updated_at"] = now()
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "challenge." + body["disposition"],
                        {"challenge_id": challenge_id, "reason": body["reason"], "source": body["source"],
                         "suite_digest": match["suite_digest"]})
            return self._projection(db, match, actor), 200
        return self.mutate(actor, f"/matches/{match_id}/challenges/{challenge_id}/decision", body, operation)

    def _review_ready(self, db, match):
        if not all(entry["review_complete"] for entry in match["slots"].values()):
            raise ArenaError("INVALID_STATE", "Both slots must explicitly complete review")
        if any(c["disposition"] == "pending" or c["reproduction"]["status"] in ("queued", "running")
               for c in match["challenges"]):
            raise ArenaError("INVALID_STATE", "Every challenge execution and disposition must be resolved")

    def advance(self, db, match, action):
        if match["phase"] not in ("reviewing", "decision"):
            raise ArenaError("INVALID_STATE", "This action requires resolved review or decision phase")
        self._review_ready(db, match)
        if action == "start_repair":
            if match["repair_round"] >= match["max_repair_rounds"]:
                raise ArenaError("INVALID_STATE", "Repair round cap reached")
            match["repair_round"] += 1
            match["_repair_submitted"] = {"a": False, "b": False}
            match["phase"] = "repairing"
            for entry in match["slots"].values():
                entry["candidate"]["eligibility"] = "pending"
        elif action == "finalize":
            runner_digest = self._runner_identity()
            for slot in ("a", "b"):
                candidate = match["slots"][slot]["candidate"]
                source = self._candidate_source(db, candidate)
                job_id = self._queue(db, match, slot, source, candidate["tree_digest"], runner_digest, candidate["candidate_id"])
                candidate["verification"] = verification(job_id=job_id)
                candidate["eligibility"] = "pending"
            match["phase"] = "verifying"
        else:
            raise ArenaError("INVALID_INPUT", "Unknown action", 422)

    def _update_decision(self, db, match):
        if match["phase"] != "verifying":
            return
        for entry in match["slots"].values():
            candidate = entry["candidate"]
            row = db.execute("SELECT status FROM jobs WHERE job_id=?", (candidate["verification"]["job_id"],)).fetchone()
            if row is None or row["status"] not in ("completed", "error"):
                return
        self._review_ready(db, match)
        match["phase"] = "decision"
        for entry in match["slots"].values():
            candidate = entry["candidate"]
            result = candidate["verification"]
            key = result["evidence_key"]
            try:
                identity = self.runner.digest
            except (RunnerError, OSError):
                identity = None
            expected = {"candidate_digest": candidate["tree_digest"], "spec_digest": match["spec_digest"],
                        "suite_digest": match["suite_digest"], "runner_digest": identity}
            candidate["eligibility"] = ("eligible" if result["status"] == "passed" and key == expected else
                                        "ineligible" if result["status"] == "failed" else "unknown")
        self._event(db, match["match_id"], "engine", "match.decision", {})

    def _finish_challenge(self, db, match, job, internal, slot, result, artifact_id):
        challenge = self._find_challenge(match, job["challenge_id"])
        reproduction = {k: result[k] for k in ("status", "reference_passed", "target_failed_twice", "actual_summary")}
        reproduction.update(job_id=job["job_id"], log_artifact_id=artifact_id)
        challenge["reproduction"] = reproduction
        if result["status"] in ("invalid", "not_reproduced"):
            challenge["disposition"] = "rejected"
            challenge["decision_reason"] = result["actual_summary"]
        job.update(status="error" if result["status"] == "inconclusive" else "completed", result=reproduction)
        if result["status"] == "inconclusive":
            job["error"] = {"code": "INVALID_STATE", "message": "Challenge reproduction was inconclusive", "details": {}}
        self.store.save_job(db, job, internal, slot)
        self._event(db, match["match_id"], "engine", "challenge.executed", {
            "challenge_id": challenge["challenge_id"], "status": result["status"]})

    def _write_artifact(self, db, match_id, slot, content, filename, content_type="text/plain", reveal_visible=True, artifact_id=None):
        artifact_id = artifact_id or uid("artifact")
        root = self.settings.state_dir / "artifacts"
        root.mkdir(exist_ok=True)
        path = root / artifact_id
        with path.open("xb") as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
        os.chmod(path, 0o400)
        db.execute("INSERT INTO artifacts(artifact_id,match_id,slot,path,reveal_visible,content_type,filename) VALUES(?,?,?,?,?,?,?)",
                   (artifact_id, match_id, slot, path.name, int(reveal_visible), content_type, filename))
        return artifact_id

    def select(self, actor, match_id, body):
        self.operator(actor)
        def operation(db):
            match = self._match(db, match_id)
            if match["phase"] != "decision":
                raise ArenaError("INVALID_STATE", "Selection requires decision phase")
            if not body["reason"].strip():
                raise ArenaError("INVALID_INPUT", "A meaningful selection reason is required", 422)
            selection = body["selection"]
            source = base = None
            if selection == "neither":
                if body["candidate_id"] is not None or body["expected_evidence_key"] is not None:
                    raise ArenaError("INVALID_INPUT", "Neither requires null candidate and evidence key", 422)
            else:
                self._review_ready(db, match)
                if db.execute("SELECT 1 FROM jobs WHERE match_id=? AND status IN ('queued','running')", (match_id,)).fetchone():
                    raise ArenaError("INVALID_STATE", "Selection is blocked by pending jobs")
                candidate = match["slots"][selection]["candidate"]
                runner_digest = self._runner_identity()
                key = {"candidate_digest": candidate["tree_digest"], "spec_digest": match["spec_digest"],
                       "suite_digest": match["suite_digest"], "runner_digest": runner_digest}
                if (body["candidate_id"] != candidate["candidate_id"] or body["expected_evidence_key"] != key
                        or candidate["verification"]["evidence_key"] != key):
                    raise ArenaError("STALE_SNAPSHOT", "Candidate revision or exact evidence key changed")
                if candidate["eligibility"] != "eligible" or candidate["verification"]["status"] != "passed":
                    raise ArenaError("INVALID_STATE", "Current candidate is not eligible")
                source = Path(self._candidate_source(db, candidate)).read_bytes()
                if hashlib.sha256(source).hexdigest() != candidate["tree_digest"]:
                    raise ArenaError("STALE_SNAPSHOT", "Frozen candidate source changed")
                base = _git(self.settings.state_dir / "task-base", "show", self.runtime["base_commit"] + ":src/booking.py").stdout.encode()
            ids = {"evidence.json": uid("artifact"), "summary.md": uid("artifact")}
            if selection != "neither":
                ids["candidate.patch"] = uid("artifact")
            match["outcome"] = {"selection": selection, "selected_candidate_id": body["candidate_id"],
                "reason": body["reason"], "evidence_artifact_id": ids["evidence.json"], "patch_artifact_id": ids.get("candidate.patch")}
            match["phase"], match["updated_at"] = "complete", now()
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "match.selected", {"source": body["source"], "reason": body["reason"], "artifacts": ids})
            public = self._projection(db, match, actor)
            shared = {**public, "jobs": [job for job in public["jobs"] if job["kind"] != "practice"]}
            events = [json.loads(row["data"]) for row in db.execute(
                "SELECT data FROM events WHERE match_id=? AND (slot IS NULL OR reveal_visible=1) ORDER BY seq", (match_id,))]
            files = build_export(shared, events, source, base)
            for filename, content in files.items():
                self._write_artifact(db, match_id, selection if selection != "neither" else "a", content, filename,
                                     "application/json" if filename == "evidence.json" else "text/plain", artifact_id=ids[filename])
            return public, 200
        return self.mutate(actor, f"/matches/{match_id}/selection", body, operation)
