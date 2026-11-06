#!/usr/bin/env python3
"""Labelled fixture clients exercise the live HTTP service and Docker runner.

Creates its own disposable state under var/. Never uses or resets existing state.
This is not a native Switch agent run.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = {"kind": "fixture", "room_id": None, "message_id": None,
          "note": "Deterministic engine smoke; no native Switch agent involved"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="save observed non-secret response samples")
    parser.add_argument("--full-match", action="store_true", help="exercise challenge/repair/selection/export")
    parser.add_argument("--neither", action="store_true", help="keep both fixtures broken through two repairs")
    parser.add_argument("--bridge-cli", action="store_true",
                        help="route supported slot requests through the real stdlib Switch bridge CLI")
    parser.add_argument("--runner-recovery", action="store_true",
                        help="inject isolated Docker start failures, finalize unknown candidates, and rerun")
    args = parser.parse_args()
    if args.runner_recovery and args.neither:
        parser.error("--runner-recovery cannot be combined with --neither")
    state = ROOT / "var" / ("smoke-" + uuid4().hex)
    env = {**os.environ, "ARENA_STATE_DIR": str(state), "PYTHONPATH": str(ROOT / "engine")}
    subprocess.run([sys.executable, "-m", "arena_engine", "init"], env=env, cwd=ROOT,
                   check=True, capture_output=True)
    if args.runner_recovery:
        shim_dir = state / "fixture-bin"
        shim_dir.mkdir()
        marker = state / "inject-runner-start-failure"
        shim = shim_dir / "docker"
        shim.write_text("#!/usr/bin/env python3\n"
                        "import os, sys\n"
                        "from pathlib import Path\n"
                        f"marker = Path({str(marker)!r})\n"
                        "if len(sys.argv) > 1 and sys.argv[1] == 'start' and marker.exists():\n"
                        "    evidence = 'FIXTURE_INJECTED_DOCKER_START_FAILURE: scoped smoke fault'\n"
                        "    marker.with_suffix('.observed').write_text(evidence + '\\n')\n"
                        "    print(evidence, file=sys.stderr)\n"
                        "    raise SystemExit(125)\n"
                        "os.execv('/usr/bin/docker', ['/usr/bin/docker', *sys.argv[1:]])\n")
        shim.chmod(0o700)
        env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
    tokens = {"operator": (state / "auth/operator.token").read_text().strip()}
    tokens.update({s: (state / f"workers/{s}/.arena/slot.token").read_text().strip() for s in ("a", "b")})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    responses = []

    def bridge_request(role, path, method, body, expected):
        """Run supported slot operations through the actual bridge executable."""
        if not args.bridge_cli or role not in {"a", "b"} or expected not in {200, 201, 202}:
            return None
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "matches" and parts[2] == "assignments" and method == "GET":
            command = ["assignment", "--match", parts[1], "--slot", parts[3]]
        elif len(parts) == 2 and parts[0] == "matches" and method == "GET":
            command = ["match", "--id", parts[1]]
        elif len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            command = ["job", "--id", parts[1]]
        elif len(parts) == 3 and parts[0] == "matches" and parts[2] in {"practice", "submissions"} and method == "POST":
            command = ["check" if parts[2] == "practice" else "submit", "--match", parts[1],
                       "--slot", body["slot"], "--commit", body["commit_sha"]]
        elif len(parts) == 3 and parts[0] == "matches" and parts[2] == "challenges" and method == "POST":
            challenge_path = state / "workers" / role / ".arena" / ("challenge-" + body["request_id"] + ".json")
            challenge_path.parent.mkdir(parents=True, exist_ok=True)
            challenge_path.write_text(json.dumps({key: body[key] for key in ("title", "requirement_ids", "scenario")},
                                                 separators=(",", ":")))
            command = ["challenge", "--match", parts[1], "--target", body["target_candidate_id"],
                       "--file", str(challenge_path)]
        elif (len(parts) == 5 and parts[0] == "matches" and parts[2] == "reviews"
              and parts[4] == "complete" and method == "POST"):
            command = ["review-done", "--match", parts[1], "--slot", parts[3],
                       "--target", body["target_candidate_id"]]
        else:
            return None
        cli = ROOT / "switch_bridge" / "arena_client.py"
        token_file = state / "workers" / role / ".arena" / "slot.token"
        call = [sys.executable, str(cli), "--api-url", f"http://127.0.0.1:{port}",
                "--token-file", str(token_file), "--state-dir", str(state / "workers" / role / ".arena" / "client-state"),
                *command]
        if method == "POST":
            call.extend(["--request-id", body["request_id"], "--source-kind", "fixture",
                         "--source-note", SOURCE["note"]])
        result = subprocess.run(call, env=env, cwd=ROOT, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def request(role, path, body=None, expected=200, record=True):
        method = "POST" if body is not None else "GET"
        bridged = bridge_request(role, path, method, body, expected)
        if bridged is not None:
            if record:
                responses.append({"role": role, "method": method, "path": path, "status": expected, "body": bridged})
            return bridged
        headers = {"Authorization": "Bearer " + tokens[role], "Content-Type": "application/json"}
        req = Request(f"http://127.0.0.1:{port}/api/v1" + path, method=method, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(req, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            status = response.code
            raw = response.read().decode()
        assert status == expected, (method, path, status, raw)
        value = json.loads(raw)
        if record:
            responses.append({"role": role, "method": method, "path": path, "status": status, "body": value})
        return value

    def mutation(**fields):
        return {"request_id": str(uuid4()), "source": SOURCE, **fields}

    def wait(role, job_id):
        if args.bridge_cli and role in {"a", "b"}:
            # The bridge's bounded wait retains the smoke's original 120 second deadline.
            call = [sys.executable, str(ROOT / "switch_bridge" / "arena_client.py"),
                    "--api-url", f"http://127.0.0.1:{port}", "--token-file",
                    str(state / "workers" / role / ".arena" / "slot.token"), "--state-dir",
                    str(state / "workers" / role / ".arena" / "client-state"), "job", "--id", job_id,
                    "--wait", "--timeout", "120"]
            result = subprocess.run(call, env=env, cwd=ROOT, check=True, capture_output=True, text=True)
            job = json.loads(result.stdout)
            responses.append({"role": role, "method": "GET", "path": "/jobs/" + job_id,
                              "status": 200, "body": job})
            return job
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = request(role, "/jobs/" + job_id, record=False)
            if job["status"] in ("completed", "error"):
                responses.append({"role": role, "method": "GET", "path": "/jobs/" + job_id,
                                  "status": 200, "body": job})
                return job
            time.sleep(0.1)
        raise AssertionError("Verification did not finish within 120 seconds")

    with (state / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "arena_engine", "serve", "--port", str(port)],
                                  env=env, cwd=ROOT, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    health = request("operator", "/health", record=False)
                    break
                except URLError:
                    if server.poll() is not None or time.monotonic() >= deadline:
                        raise AssertionError("Engine failed to start; inspect " + str(state / "server.log"))
                    time.sleep(0.1)
            assert health["runner_available"] is True, health
            create = mutation(task_id="booking-v1", candidate_budget_minutes=10, max_repair_rounds=2,
                              provider_labels={"a": "Known-good fixture", "b": "Repeat-cancel broken fixture"})
            created = subprocess.run([sys.executable, "-m", "arena_engine", "operator", "--api-url",
                f"http://127.0.0.1:{port}", "create", "--request-id", create["request_id"],
                "--label-a", create["provider_labels"]["a"], "--label-b", create["provider_labels"]["b"],
                "--source-kind", "fixture", "--note", SOURCE["note"]],
                env=env, cwd=ROOT, check=True, capture_output=True, text=True)
            match = json.loads(created.stdout)
            responses.append({"role": "operator", "method": "POST", "path": "/matches", "status": 201, "body": match})
            assert request("operator", "/matches", create, 201, record=False) == match
            match_id = match["match_id"]
            assignments, shas = {}, {}
            for slot in ("a", "b"):
                assignment = request(slot, f"/matches/{match_id}/assignments/{slot}")
                assignments[slot] = assignment
                workspace = Path(assignment["workspace_path"])
                assert workspace == state / f"workers/{slot}/worktree"
                fixture = "known-good/booking.py" if slot == "a" and not args.neither else "known-bad/repeat_cancel.py"
                (workspace / "src/booking.py").write_bytes((ROOT / "fixtures/booking-v1" / fixture).read_bytes())
                subprocess.run(["git", "add", "--", "src/booking.py"], cwd=workspace, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-qm", "Labelled deterministic smoke fixture"],
                               cwd=workspace, check=True, capture_output=True)
                shas[slot] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
            assert assignments["a"]["base_commit"] == assignments["b"]["base_commit"]
            assert assignments["a"]["workspace_path"] != assignments["b"]["workspace_path"]
            practice = request("a", f"/matches/{match_id}/practice", mutation(slot="a", commit_sha=shas["a"]), 202)
            practiced = wait("a", practice["job_id"])
            assert practiced["status"] == "completed" and practiced["result"]["status"] == ("failed" if args.neither else "passed"), practiced
            assert request("a", f"/matches/{match_id}", record=False)["slots"]["a"]["candidate"] is None
            submitted = {}
            for slot in ("a", "b"):
                body = mutation(slot=slot, commit_sha=shas[slot])
                submitted[slot] = request(slot, f"/matches/{match_id}/submissions", body, 202)
                assert request(slot, f"/matches/{match_id}/submissions", body, 202, record=False) == submitted[slot]
            hidden = request("a", f"/matches/{match_id}")
            assert hidden["slots"]["b"]["candidate"] is None
            request("a", "/jobs/" + submitted["b"]["job_id"], expected=403)
            jobs = {slot: wait(slot, submitted[slot]["job_id"]) for slot in ("a", "b")}
            polled = subprocess.run([sys.executable, "-m", "arena_engine", "operator", "--api-url",
                f"http://127.0.0.1:{port}", "job", "--id", submitted["a"]["job_id"]],
                env=env, cwd=ROOT, check=True, capture_output=True, text=True)
            assert json.loads(polled.stdout) == jobs["a"]
            assert jobs["a"]["status"] == jobs["b"]["status"] == "completed", jobs
            assert jobs["a"]["result"]["status"] == ("failed" if args.neither else "passed"), jobs["a"]
            assert jobs["b"]["result"]["status"] == "failed", jobs["b"]
            assert jobs["a"]["result"]["check_count"] > practiced["result"]["check_count"]
            assert practiced["result"]["evidence_key"]["suite_digest"] != match["suite_digest"]
            for job in jobs.values():
                assert job["result"]["evidence_key"]["suite_digest"] == match["suite_digest"]
            artifact_id = jobs["b"]["result"]["log_artifact_id"]
            request("a", "/artifacts/" + artifact_id, expected=403)
            revealed = request("operator", f"/matches/{match_id}/actions", mutation(action="reveal", reason="Fixture checkpoint"))
            assert revealed["phase"] == "reviewing"
            for slot in ("a", "b"):
                assignment = request(slot, f"/matches/{match_id}/assignments/{slot}")
                assert Path(assignment["review_path"]).is_relative_to(state / f"workers/{slot}/review")
                assert (Path(assignment["review_path"]) / "src/booking.py").is_file()
            request("a", "/jobs/" + submitted["b"]["job_id"])
            final = None
            if args.full_match or args.neither or args.runner_recovery:
                final = full_match(request, wait, mutation, match_id, submitted, shas, state, env, port,
                                   args.neither, args.runner_recovery, responses)
            else:
                request("operator", f"/matches/{match_id}/actions", mutation(action="cancel", reason="Sprint 2 fixture smoke finished"))
            if args.snapshot:
                args.snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot = {"label": "Deterministic fixture clients against live HTTP/Docker; no Switch agents",
                            "responses": responses}
                if args.runner_recovery:
                    snapshot["label"] = "Injected Docker start failure recovery verified against live Docker; fixture clients; no Switch agents"
                    snapshot["runner_recovery_checked"] = True
                    snapshot["runner_recovery_evidence"] = "FIXTURE_INJECTED_DOCKER_START_FAILURE: scoped smoke fault"
                args.snapshot.write_text(json.dumps(snapshot, indent=2) + "\n")
            print(json.dumps({"mode": "fixture_smoke_live_engine", "match_id": match_id,
                              "practice_checks": practiced["result"]["check_count"],
                              "official_checks_per_candidate": jobs["a"]["result"]["check_count"],
                              "a": jobs["a"]["result"]["status"], "b": jobs["b"]["result"]["status"],
                              "runner_recovery_checked": bool(args.runner_recovery),
                              "runner_recovery_evidence": ("FIXTURE_INJECTED_DOCKER_START_FAILURE: scoped smoke fault"
                                                            if args.runner_recovery else None),
                              "reveal": "passed", "outcome": final, "state_dir": str(state)}))
        finally:
            server.terminate()
            try:
                server.wait(timeout=25)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def full_match(request, wait, mutation, match_id, submitted, shas, state, env, port, neither,
               runner_recovery=False, responses=None):
    responses = responses if responses is not None else []
    path = f"/matches/{match_id}"
    scenario = json.loads((ROOT / "fixtures/booking-v1/known-bad/scenarios/repeat_cancel.json").read_text())["scenario"]
    report = request("a", path + "/challenges", mutation(target_candidate_id=submitted["b"]["candidate_id"],
        title="Fixture repeated cancellation violates BOOK-04", requirement_ids=["BOOK-04"], scenario=scenario), 202)
    reproduced = wait("a", report["job_id"])
    assert reproduced["result"]["status"] == "reproduced", reproduced
    assert reproduced["result"]["reference_passed"] is True and reproduced["result"]["target_failed_twice"] is True
    invalid = request("a", path + "/challenges", mutation(target_candidate_id=submitted["b"]["candidate_id"],
        title="Deliberately wrong typed expectation fixture", requirement_ids=["BOOK-07"],
        scenario={"capacity": 3, "steps": [{"op": "available", "args": [], "expected": True}]}), 202)
    assert wait("a", invalid["job_id"])["result"]["status"] == "invalid"

    def operator(*args):
        result = subprocess.run([sys.executable, "-m", "arena_engine", "operator", "--api-url",
            f"http://127.0.0.1:{port}", *args], env=env, cwd=ROOT, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    accepted = operator("decision", "--match", match_id, "--challenge", report["challenge_id"],
        "--disposition", "accepted", "--reason", "Fixture operator: BOOK-04 requires second cancellation false without mutation",
        "--source-kind", "fixture")
    assert all(s["candidate"]["verification"]["status"] == "stale" for s in accepted["slots"].values())
    for slot in ("a", "b"):
        request(slot, path + f"/reviews/{slot}/complete", mutation(
            target_candidate_id=submitted["b" if slot == "a" else "a"]["candidate_id"]))
    for round_number in range(1, 3 if neither else 2):
        body = mutation(action="start_repair", reason="Deterministic fixture repair round")
        repairing = request("operator", path + "/actions", body)
        assert request("operator", path + "/actions", body, record=False) == repairing
        assert repairing["repair_round"] == round_number
        if not neither:
            workspace = state / "workers/b/worktree"
            (workspace / "src/booking.py").write_bytes((ROOT / "fixtures/booking-v1/known-good/booking.py").read_bytes())
            subprocess.run(["git", "add", "--", "src/booking.py"], cwd=workspace, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", "Labelled fixture repair"], cwd=workspace, check=True, capture_output=True)
            shas["b"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
        if runner_recovery and round_number == 1:
            marker = state / "inject-runner-start-failure"
            marker.touch(mode=0o600)
            try:
                repaired = {slot: request(slot, path + "/submissions", mutation(slot=slot, commit_sha=shas[slot]), 202)
                            for slot in ("a", "b")}
                failed_jobs = {slot: wait(slot, repaired[slot]["job_id"]) for slot in ("a", "b")}
                assert all(job["status"] == "error" and job["result"]["status"] == "error"
                           for job in failed_jobs.values()), failed_jobs
                evidence_path = marker.with_suffix(".observed")
                evidence = evidence_path.read_text().strip()
                assert evidence == "FIXTURE_INJECTED_DOCKER_START_FAILURE: scoped smoke fault", evidence
                responses.append({"role": "fixture", "method": "INJECT", "path": "docker start",
                                  "status": 125, "body": {"evidence": evidence,
                                  "jobs": {slot: job["job_id"] for slot, job in failed_jobs.items()}}})
            finally:
                marker.unlink(missing_ok=True)
            unknown = request("operator", path)
            assert unknown["phase"] == "decision", unknown["phase"]
            assert all(entry["candidate"]["eligibility"] == "unknown"
                       for entry in unknown["slots"].values()), unknown["slots"]
            assert unknown["repair_round"] == round_number, unknown["repair_round"]
            stable = {slot: {key: unknown["slots"][slot]["candidate"][key]
                             for key in ("candidate_id", "commit_sha", "tree_digest", "revision")}
                      for slot in ("a", "b")}
            finalized = operator("action", "--match", match_id, "--action", "finalize",
                                 "--reason", "Fixture operator reruns unknown candidates after transient runner failure",
                                 "--source-kind", "fixture", "--note", SOURCE["note"])
            responses.append({"role": "operator", "method": "POST", "path": path + "/actions",
                              "status": 200, "body": finalized})
            assert finalized["phase"] == "verifying" and finalized["repair_round"] == round_number, finalized
            rerun_jobs = {slot: wait(slot, finalized["slots"][slot]["candidate"]["verification"]["job_id"])
                          for slot in ("a", "b")}
            assert all(job["status"] == "completed" and job["result"]["status"] == "passed"
                       and job["result"]["check_count"] == 12 for job in rerun_jobs.values()), rerun_jobs
            measured = request("operator", path)
            assert measured["phase"] == "decision" and measured["repair_round"] == round_number, measured
            for slot in ("a", "b"):
                candidate = measured["slots"][slot]["candidate"]
                assert {key: candidate[key] for key in stable[slot]} == stable[slot], (slot, stable[slot], candidate)
            assert all(measured["slots"][slot]["candidate"]["verification"]["status"] == "passed"
                       for slot in ("a", "b")), measured["slots"]
        else:
            repaired = {slot: request(slot, path + "/submissions", mutation(slot=slot, commit_sha=shas[slot]), 202)
                        for slot in ("a", "b")}
            for slot in ("a", "b"):
                job = wait(slot, repaired[slot]["job_id"])
                assert job["result"]["check_count"] == 12, job
                assert job["result"]["status"] == ("failed" if neither else "passed"), job
        measured = request("operator", path)
        assert measured["phase"] == "decision"
    if neither:
        request("operator", path + "/actions", mutation(action="start_repair", reason="Cap must refuse"), 409)
        selected = operator("select", "--match", match_id, "--selection", "neither", "--reason",
                            "Both deterministic fixtures remain broken after the repair cap", "--source-kind", "fixture")
    else:
        candidate = measured["slots"]["b"]["candidate"]
        key = candidate["verification"]["evidence_key"]
        request("operator", path + "/selection", mutation(selection="b", candidate_id=candidate["candidate_id"],
            expected_evidence_key={**key, "suite_digest": "0" * 64}, reason="Stale evidence fixture"), 409)
        evidence_path = state / "selection-key.json"
        evidence_path.write_text(json.dumps(key))
        selected = operator("select", "--match", match_id, "--selection", "b", "--candidate", candidate["candidate_id"],
            "--evidence-key", str(evidence_path), "--reason", "Fixture operator selects the repaired verified candidate", "--source-kind", "fixture")
    assert selected["phase"] == "complete", selected
    downloaded = state / "download"
    operator("export", "--match", match_id, "--output", str(downloaded))
    assert (downloaded / "evidence.json").is_file() and (downloaded / "summary.md").is_file()
    assert (downloaded / "candidate.patch").exists() is (not neither)
    if not neither:
        _verify_patch(state, downloaded / "candidate.patch", selected)
    return {"selection": selected["outcome"]["selection"], "repair_round": selected["repair_round"],
            "evidence_exported": True, "patch_verified": not neither}


def _verify_patch(state, patch, selected):
    target = state / "patch-check"
    subprocess.run(["git", "clone", "-q", str(state / "task-base"), str(target)], check=True, capture_output=True)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "apply", str(patch)], cwd=target, check=True, capture_output=True)
    sys.path.insert(0, str(ROOT / "engine"))
    from arena_engine.runner import DockerRunner
    from arena_engine.runtime import Settings
    cases = json.loads((ROOT / "fixtures/booking-v1/public_cases/public_cases.json").read_text())
    cases += json.loads((ROOT / "fixtures/booking-v1/held_out_cases/held_out_cases.json").read_text())
    regressions = {c["regression_digest"]: c["scenario"] for c in selected["challenges"] if c["disposition"] == "accepted"}
    cases += [{"check_id": "REG-" + key, "scenario": scenario} for key, scenario in sorted(regressions.items())]
    runner = DockerRunner(Settings(state, Settings.from_env().runner_image))
    assert runner.available()
    checked = runner.verify(target / "src/booking.py", cases, include_isolation=True)
    assert checked["failed_check_ids"] == [], checked
    assert checked["check_count"] == 12


if __name__ == "__main__":
    main()
