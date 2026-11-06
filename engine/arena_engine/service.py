"""Persistent first-match workflow and serialized verification worker."""

import hashlib
import hmac
import fcntl
import json
import os
import shutil
import threading
from pathlib import Path

from .contract import ROOT, canonical_bytes, load_contract
from .errors import ArenaError
from .persistence import Store
from .runner import DockerRunner, RunnerError
from .workspaces import WorkspaceError, freeze, read_runtime, _git


from .domain import now, digest, uid, verification
from .workflow import Workflow
from .reproduction import reproduce


class Engine(Workflow):
    def __init__(self, settings, runner=None, exclusive=False):
        self.settings = settings
        self.runtime = read_runtime(settings)
        self._lock_file = None
        if exclusive:
            self._lock_file = (settings.state_dir / ".engine.lock").open("a")
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._lock_file.close()
                raise ArenaError("INVALID_STATE", "Another engine server owns this state directory") from exc
        self.store = Store(settings.state_dir)
        self.runner = runner or DockerRunner(settings)
        self.contract = load_contract()
        pack = ROOT / "fixtures" / "booking-v1"
        self.public = json.loads((pack / "public_cases/public_cases.json").read_text())
        self.full = self.public + json.loads((pack / "held_out_cases/held_out_cases.json").read_text())
        self.suite_digest = digest({"checks": self.full, "instance_isolation": True, "regressions": []})
        self.practice_digest = digest({"kind": "practice", "checks": self.public, "regressions": []})
        self.tokens = {"operator": (settings.state_dir / "auth/operator.token").read_text().strip()}
        self.tokens.update({"slot_" + s: (settings.state_dir / f"workers/{s}/.arena/slot.token").read_text().strip()
                            for s in ("a", "b")})
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._execution_lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self.worker_failed = False
        if exclusive and hasattr(self.runner, "cleanup_interrupted"):
            try:
                self.runner.cleanup_interrupted()
            except RunnerError:
                self.worker_failed = True
        self._recover(include_queued=self.worker_failed, reason=(
            "Runner startup cleanup failed; rerun required" if self.worker_failed else
            "Verification interrupted by engine restart; rerun required"))

    def authenticate(self, header):
        if not header or not header.startswith("Bearer "):
            raise ArenaError("UNAUTHORIZED", "A bearer token is required", 401)
        value = header[7:]
        for actor, token in self.tokens.items():
            if hmac.compare_digest(value.encode("utf-8"), token.encode("ascii")):
                return actor
        raise ArenaError("UNAUTHORIZED", "Invalid bearer token", 401)

    @staticmethod
    def operator(actor):
        if actor != "operator":
            raise ArenaError("FORBIDDEN", "Operator token required", 403)

    @staticmethod
    def slot(actor, slot):
        if actor != "slot_" + slot:
            raise ArenaError("FORBIDDEN", "Matching slot token required", 403)

    @staticmethod
    def _match(db, match_id):
        row = db.execute("SELECT data FROM matches WHERE match_id=?", (match_id,)).fetchone()
        if row is None:
            raise ArenaError("NOT_FOUND", "Match not found", 404)
        return json.loads(row["data"])

    @staticmethod
    def _visible(actor, slot, revealed, reveal_visible):
        return actor == "operator" or slot is None or actor == "slot_" + slot or (revealed and reveal_visible)

    def _projection(self, db, match, actor):
        result = {k: v for k, v in match.items() if not k.startswith("_")}
        result = json.loads(json.dumps(result))
        revealed = match["_revealed"]
        if actor != "operator" and not revealed:
            other = "b" if actor == "slot_a" else "a"
            result["slots"][other]["candidate"] = None
        rows = db.execute("SELECT * FROM jobs WHERE match_id=? ORDER BY rowid", (match["match_id"],)).fetchall()
        result["jobs"] = [json.loads(row["data"]) for row in rows
                          if self._visible(actor, row["slot"], revealed,
                                           json.loads(row["data"])["kind"] in ("verification", "challenge"))]
        return result

    def _event(self, db, match_id, actor, kind, data, slot=None, reveal_visible=False):
        seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE match_id=?", (match_id,)).fetchone()[0]
        event = {"seq": seq, "at": now(), "actor": actor, "type": kind, "data": data}
        db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (match_id, seq, json.dumps(event), slot, int(reveal_visible)))

    def mutate(self, actor, endpoint, body, operation):
        request_id = body["request_id"]
        body_digest = digest(body)
        with self.store.transaction() as db:
            old = db.execute("SELECT * FROM requests WHERE actor=? AND endpoint=? AND request_id=?",
                             (actor, endpoint, request_id)).fetchone()
            if old:
                if old["digest"] != body_digest:
                    raise ArenaError("IDEMPOTENCY_CONFLICT", "Request ID was used with a different body")
                return json.loads(old["response"]), old["status"]
            db.execute("SAVEPOINT operation")
            try:
                response, status = operation(db)
            except ArenaError as exc:
                db.execute("ROLLBACK TO operation")
                response, status = exc.payload(), exc.status
            finally:
                db.execute("RELEASE operation")
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?)",
                       (actor, endpoint, request_id, body_digest, json.dumps(response), status))
        self._wake.set()
        return response, status

    def create(self, actor, body):
        self.operator(actor)
        def operation(db):
            if db.execute("SELECT 1 FROM matches WHERE phase NOT IN ('complete','cancelled')").fetchone():
                raise ArenaError("INVALID_STATE", "Only one active match is allowed")
            # A new match must begin at the same untouched base for both slots.
            # Sprint 2 never silently resets an agent's work.
            for s in ("a", "b"):
                path = self.settings.state_dir / f"workers/{s}/worktree"
                if (_git(path, "rev-parse", "HEAD").stdout.strip() != self.runtime["base_commit"]
                        or _git(path, "status", "--porcelain", "--untracked-files=all").stdout):
                    raise ArenaError("INVALID_STATE", "New matches require clean task-base workspaces; initialize a fresh state directory")
            match_id, at = uid("match"), now()
            match = {"match_id": match_id, "task_id": "booking-v1", "mode": "live", "phase": "building",
                     "repair_round": 0, "max_repair_rounds": body["max_repair_rounds"],
                     "spec_digest": self.runtime["spec_digest"], "suite_digest": self.suite_digest,
                     "created_at": at, "updated_at": at, "outcome": None,
                     "slots": {s: {"candidate": None, "review_complete": False} for s in ("a", "b")},
                     "jobs": [], "challenges": [], "_revealed": False,
                     "_budget": body["candidate_budget_minutes"], "_provider_labels": body["provider_labels"],
                     "_baseline_checks": self.full, "_public_cases": self.public,
                     "_reference": (ROOT / "fixtures/booking-v1/reference/booking.py").read_text(),
                     "_task_spec": self.contract["booking_contract"],
                     "_task_text": _git(self.settings.state_dir / "task-base", "show",
                                        self.runtime["base_commit"] + ":SPEC.md").stdout}
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "match.created", {"source": body["source"],
                        "provider_labels": body["provider_labels"]})
            return self._projection(db, match, actor), 201
        return self.mutate(actor, "/matches", body, operation)

    def get_match(self, actor, match_id):
        with self.store.transaction() as db:
            return self._projection(db, self._match(db, match_id), actor)

    def assignment(self, actor, match_id, slot):
        if slot not in ("a", "b"):
            raise ArenaError("NOT_FOUND", "Slot not found", 404)
        if actor != "operator":
            self.slot(actor, slot)
        with self.store.transaction() as db:
            match = self._match(db, match_id)
            other = "b" if slot == "a" else "a"
            target = match["slots"][other]["candidate"] if match["_revealed"] else None
            public = json.loads((ROOT / "fixtures/booking-v1/starter/public_checks.json").read_text())
            return {"match_id": match_id, "slot": slot, "task_id": "booking-v1", "phase": match["phase"],
                    "repair_round": match["repair_round"], "task_spec": match.get("_task_spec", self.contract["booking_contract"]),
                    "task_text": match.get("_task_text", (ROOT / "fixtures/booking-v1/SPEC.md").read_text()),
                    "spec_digest": match["spec_digest"], "suite_digest": match["suite_digest"],
                    "base_commit": self.runtime["base_commit"], "allowed_files": ["src/booking.py"],
                    "candidate_budget_minutes": match["_budget"],
                    "workspace_path": str(self.settings.state_dir / f"workers/{slot}/worktree"),
                    "review_path": str(self.settings.state_dir / f"workers/{slot}/review/{target['candidate_id']}") if target else None,
                    "target_candidate_id": target["candidate_id"] if target else None,
                    "public_checks": [entry["check_id"] for entry in public],
                    "public_check_descriptions": [entry["description"] for entry in public],
                    "practice_endpoint": f"POST /api/v1/matches/{match_id}/practice",
                    "accepted_challenges": [c for c in match["challenges"] if c["disposition"] == "accepted"]}

    def submit(self, actor, match_id, body, practice=False):
        return self.submit_candidate(actor, match_id, body, practice)

    def get_job(self, actor, job_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise ArenaError("NOT_FOUND", "Job not found", 404)
            match = self._match(db, row["match_id"])
            job = json.loads(row["data"])
            if not self._visible(actor, row["slot"], match["_revealed"], job["kind"] in ("verification", "challenge")):
                raise ArenaError("FORBIDDEN", "Job is not visible to this slot", 403)
            return job

    def events(self, actor, match_id, after):
        with self.store.transaction() as db:
            match = self._match(db, match_id)
            rows = db.execute("SELECT * FROM events WHERE match_id=? AND seq>? ORDER BY seq", (match_id, after)).fetchall()
            events = [json.loads(row["data"]) for row in rows
                      if self._visible(actor, row["slot"], match["_revealed"], row["reveal_visible"])]
            return {"events": events, "next_after": rows[-1]["seq"] if rows else after}

    def artifact(self, actor, artifact_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if row is None:
                raise ArenaError("NOT_FOUND", "Artifact not found", 404)
            match = self._match(db, row["match_id"])
            if not self._visible(actor, row["slot"], match["_revealed"], row["reveal_visible"]):
                raise ArenaError("FORBIDDEN", "Artifact is not visible to this slot", 403)
            path = self.settings.state_dir / "artifacts" / row["path"]
            if not path.is_file() or path.is_symlink():
                raise ArenaError("NOT_FOUND", "Artifact is unavailable", 404)
            return path.read_bytes(), row["filename"] or artifact_id + ".log", row["content_type"]

    def action(self, actor, match_id, body):
        self.operator(actor)
        def operation(db):
            match = self._match(db, match_id)
            action = body["action"]
            if match["phase"] in ("complete", "cancelled"):
                raise ArenaError("INVALID_STATE", "Match is terminal")
            if action == "reveal":
                if match["phase"] != "building" or not all(match["slots"][s]["candidate"] for s in ("a", "b")):
                    raise ArenaError("INVALID_STATE", "Reveal requires both initial candidates")
                for slot in ("a", "b"):
                    candidate = match["slots"][slot]["candidate"]
                    row = db.execute("SELECT status,internal FROM jobs WHERE job_id=?",
                                     (candidate["verification"]["job_id"],)).fetchone()
                    if row["status"] not in ("completed", "error"):
                        raise ArenaError("INVALID_STATE", "Initial verification jobs must be terminal")
                self._stage_review(db, match)
                match["_revealed"] = True
                match["phase"] = "reviewing"
            elif action == "cancel":
                match["phase"] = "cancelled"
                self._cancel.set()
                rows = db.execute("SELECT * FROM jobs WHERE match_id=? AND status IN ('queued','running')", (match_id,)).fetchall()
                for row in rows:
                    self._fail_job(db, row, match, "Match cancelled by operator")
            else:
                self.advance(db, match, action)
            match["updated_at"] = now()
            self.store.save_match(db, match)
            self._event(db, match_id, actor, "match." + action, {"reason": body["reason"], "source": body["source"]})
            return self._projection(db, match, actor), 200
        return self.mutate(actor, f"/matches/{match_id}/actions", body, operation)

    def _stage_review(self, db, match):
        for slot in ("a", "b"):
            other = "b" if slot == "a" else "a"
            candidate = match["slots"][other]["candidate"]
            row = db.execute("SELECT internal FROM jobs WHERE job_id=?", (candidate["verification"]["job_id"],)).fetchone()
            source = Path(json.loads(row["internal"])["source"])
            review_root = self.settings.state_dir / f"workers/{slot}/review"
            if review_root.is_symlink() or not review_root.is_dir():
                raise ArenaError("INVALID_STATE", "Review root must remain a real directory within its slot")
            target = review_root / candidate["candidate_id"]
            if target.is_symlink() or (target / "src").is_symlink() or (target / "src/booking.py").is_symlink():
                raise ArenaError("INVALID_STATE", "Review snapshot cannot contain symlinks")
            if target.exists():
                if (target / "src/booking.py").read_bytes() != source.read_bytes():
                    raise ArenaError("INVALID_STATE", "Review snapshot does not match frozen candidate")
                continue
            (target / "src").mkdir(parents=True)
            shutil.copyfile(source, target / "src/booking.py")
            os.chmod(target / "src/booking.py", 0o400)
            os.chmod(target / "src", 0o500)
            os.chmod(target, 0o500)

    def _fail_job(self, db, row, match, message):
        job = json.loads(row["data"])
        job["status"] = "error"
        job["error"] = {"code": "RUNNER_UNAVAILABLE", "message": message, "details": {}}
        if job["kind"] == "challenge":
            challenge = self._find_challenge(match, job["challenge_id"])
            challenge["reproduction"].update(status="inconclusive", actual_summary=message,
                                             reference_passed=None, target_failed_twice=None)
            job["result"] = dict(challenge["reproduction"])
        else:
            job["result"] = verification("error", job["job_id"])
        self.store.save_job(db, job, json.loads(row["internal"]), row["slot"])
        if job["kind"] == "verification":
            candidate = match["slots"][row["slot"]]["candidate"]
            if candidate and candidate["candidate_id"] == job["candidate_id"]:
                candidate["verification"] = job["result"]
                candidate["eligibility"] = "unknown"
        self._event(db, match["match_id"], "engine", "job.error", {"job_id": job["job_id"], "reason": message},
                    row["slot"], job["kind"] in ("verification", "challenge"))

    def _recover(self, include_queued=False, reason="Verification interrupted by engine restart; rerun required"):
        with self.store.transaction() as db:
            statuses = "('running','queued')" if include_queued else "('running')"
            for row in db.execute("SELECT * FROM jobs WHERE status IN " + statuses).fetchall():
                match = self._match(db, row["match_id"])
                self._fail_job(db, row, match, reason)
                self._update_decision(db, match)
                match["updated_at"] = now()
                self.store.save_match(db, match)

    def worker_once(self):
        with self._execution_lock:
            with self.store.transaction() as db:
                row = None
                for pending in db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid").fetchall():
                    pending_job = json.loads(pending["data"])
                    pending_match = self._match(db, pending_job["match_id"])
                    if pending_match["phase"] == "repairing" and pending_job["kind"] == "verification":
                        continue
                    row = pending
                    break
                if row is None:
                    return False
                job, internal = json.loads(row["data"]), json.loads(row["internal"])
                match = self._match(db, job["match_id"])
                if match["phase"] == "cancelled":
                    self._fail_job(db, row, match, "Match cancelled")
                    self.store.save_match(db, match)
                    return True
                self._cancel.clear()
                job["status"] = "running"
                self.store.save_job(db, job, internal, row["slot"])
                if job["kind"] == "verification":
                    match["slots"][row["slot"]]["candidate"]["verification"]["status"] = "running"
                    self.store.save_match(db, match)
                if job["kind"] == "challenge":
                    self._find_challenge(match, job["challenge_id"])["reproduction"]["status"] = "running"
                    self.store.save_match(db, match)
                self._event(db, job["match_id"], "engine", "job.running", {"job_id": job["job_id"]},
                            row["slot"], job["kind"] in ("verification", "challenge"))
            try:
                source = Path(internal["source"])
                if hashlib.sha256(source.read_bytes()).hexdigest() != internal["candidate_digest"]:
                    raise RunnerError("Frozen source digest mismatch")
                if not self.runner.available() or self.runner.digest != internal["runner_digest"]:
                    raise RunnerError("Runner is unavailable or its identity changed")
                if job["kind"] == "challenge":
                    reference = Path(internal["reference_source"])
                    if hashlib.sha256(reference.read_bytes()).hexdigest() != internal["reference_digest"]:
                        raise RunnerError("Frozen reference digest mismatch")
                    result = reproduce(self.runner, reference, source, internal["scenario"], self._cancel)
                else:
                    result = self.runner.verify(source, internal["checks"], internal["include_isolation"], cancel_event=self._cancel)
                    expected_ids = {item["check_id"] for item in internal["checks"]}
                    if internal["include_isolation"]:
                        expected_ids.add("HELD-BOOK-07-ISOLATION")
                    failed = result["failed_check_ids"]
                    if (type(result["check_count"]) is not int or type(result["passed_count"]) is not int
                            or result["check_count"] != len(expected_ids)
                            or type(failed) is not list or len(failed) != len(set(failed))
                            or not set(failed).issubset(expected_ids)
                            or result["passed_count"] != result["check_count"] - len(failed)
                            or type(result["log"]) is not str or len(result["log"]) > 65536):
                        raise RunnerError("Verification returned invalid counts or identifiers")
                error = None
            except RunnerError as exc:
                result, error = None, str(exc)
            except Exception:
                # Do not copy candidate output or internal paths into API errors.
                result, error = None, "Verification infrastructure failed or execution was interrupted"
            with self.store.transaction() as db:
                current = db.execute("SELECT * FROM jobs WHERE job_id=?", (job["job_id"],)).fetchone()
                if current["status"] != "running":
                    return True
                match = self._match(db, job["match_id"])
                if error or self._cancel.is_set():
                    self._fail_job(db, current, match, error or "Verification cancelled")
                else:
                    artifact_id = self._write_artifact(db, job["match_id"], row["slot"], result["log"],
                                                       "verification.log", reveal_visible=job["kind"] != "practice")
                    if job["kind"] == "challenge":
                        self._finish_challenge(db, match, job, internal, row["slot"], result, artifact_id)
                    else:
                        outcome = {"status": "passed" if not result["failed_check_ids"] else "failed",
                                   "check_count": result["check_count"], "passed_count": result["passed_count"],
                                   "failed_check_ids": result["failed_check_ids"], "job_id": job["job_id"],
                                   "log_artifact_id": artifact_id,
                                   "evidence_key": {k: internal[k] for k in
                                                    ("candidate_digest", "spec_digest", "suite_digest", "runner_digest")}}
                        job.update(status="completed", result=outcome)
                        self.store.save_job(db, job, internal, row["slot"])
                        if job["kind"] == "verification":
                            candidate = match["slots"][row["slot"]]["candidate"]
                            candidate["verification"] = outcome
                            candidate["eligibility"] = "pending" if outcome["status"] == "passed" else "ineligible"
                        self._event(db, job["match_id"], "engine", "job.completed", {"job_id": job["job_id"], "status": outcome["status"]},
                                    row["slot"], job["kind"] in ("verification", "challenge"))
                self._update_decision(db, match)
                match["updated_at"] = now()
                self.store.save_match(db, match)
            return True

    def start(self):
        if self.worker_failed:
            return
        def work():
            while not self._stop.is_set():
                try:
                    if self.worker_once():
                        continue
                except Exception:
                    self.worker_failed = True
                    try:
                        self._recover(include_queued=True, reason="Verification worker stopped unexpectedly; rerun required")
                    except Exception:
                        pass
                    self._stop.set()
                    break
                self._wake.wait(0.5)
                self._wake.clear()
        self._thread = threading.Thread(target=work, name="arena-verification", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._cancel.set()
        self._wake.set()
        self.runner.cancel()
        if self._thread:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                self.worker_failed = True
                self._recover(include_queued=True, reason="Engine shutdown interrupted execution; rerun required")
                return  # Retain the state lock until the process exits.
        if self._lock_file:
            self._lock_file.close()
