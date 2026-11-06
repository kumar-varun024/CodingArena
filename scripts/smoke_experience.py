#!/usr/bin/env python3
"""Exercise unchanged Role B clients against live HTTP/Docker with labelled fixtures.

Requires Playwright for this Python interpreter, Chromium, and installed web deps.
All runtime state and evidence stay in a fresh var/ directory. No native Switch run.
"""

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from smoke_engine import _verify_patch

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=25)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experience-root", type=Path, required=True,
                        help="unchanged B checkout/export containing web/ and switch_bridge/")
    parser.add_argument("--engine-python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright, expect

    experience = args.experience_root.resolve()
    state = ROOT / "var" / ("experience-smoke-" + uuid4().hex)
    api_port, web_port = free_port(), free_port()
    api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    env = {**os.environ, "ARENA_STATE_DIR": str(state), "PYTHONPATH": str(ROOT / "engine"),
           "ARENA_UI_ORIGIN": web_url}
    # Preserve the venv executable path; resolving its symlink loses site-packages.
    python = str(args.engine_python.absolute())
    subprocess.run([python, "-m", "arena_engine", "init"], env=env, cwd=ROOT,
                   check=True, capture_output=True)
    token = (state / "auth/operator.token").read_text().strip()

    def get(path, authorized=True, expected=200):
        headers = {"Authorization": "Bearer " + token} if authorized else {}
        try:
            response = urlopen(Request(api_url + "/api/v1" + path, headers=headers), timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            assert response.status == expected, (path, response.status)
            assert response.headers["X-Arena-Mode"] == "live"
            return json.loads(response.read())

    def bridge(slot, *command):
        result = subprocess.run([python, str(experience / "switch_bridge/arena_client.py"),
            "--api-url", api_url, "--token-file", str(state / f"workers/{slot}/.arena/slot.token"),
            "--state-dir", str(state / f"workers/{slot}/.arena/client-state"),
            "--source-kind", "fixture", "--source-note", "Deterministic integration fixture; no Switch agent",
            *command], cwd=ROOT, capture_output=True, text=True, timeout=150)
        assert result.returncode == 0, (command[0], result.stderr)
        return json.loads(result.stdout)

    def commit(slot, fixture, message):
        workspace = state / f"workers/{slot}/worktree"
        (workspace / "src/booking.py").write_bytes((ROOT / "fixtures/booking-v1" / fixture).read_bytes())
        subprocess.run(["git", "add", "--", "src/booking.py"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-qm", message],
                       cwd=workspace, check=True, capture_output=True)
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()

    with ExitStack() as stack:
        server_log = stack.enter_context((state / "server.log").open("w"))
        server = subprocess.Popen([python, "-m", "arena_engine", "serve", "--port", str(api_port)],
            cwd=ROOT, env=env, stdout=server_log, stderr=server_log)
        stack.callback(stop, server)
        deadline = time.monotonic() + 20
        while True:
            try:
                health = get("/health", authorized=False)
                break
            except URLError:
                assert server.poll() is None and time.monotonic() < deadline, "Engine startup failed; see " + str(state / "server.log")
                time.sleep(.1)
        assert health["api_version"] == "1.1" and health["runner_available"]
        get("/matches/missing", authorized=False, expected=401)
        web_log = stack.enter_context((state / "web.log").open("w"))
        # Direct-origin mode deliberately exercises CORS exposure as well as the API.
        web = subprocess.Popen(["node", str(experience / "web/node_modules/vite/bin/vite.js"),
            "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"],
            cwd=experience / "web", env={**os.environ, "VITE_ARENA_API_BASE": api_url + "/api/v1"},
            stdout=web_log, stderr=web_log)
        stack.callback(stop, web)
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(web_url, timeout=2) as response:
                    assert response.status == 200
                break
            except URLError:
                assert web.poll() is None and time.monotonic() < deadline, "Vite startup failed"
                time.sleep(.1)
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True)
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors, api_responses = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("response", lambda response: api_responses.append((response.status, response.headers.get("x-arena-mode")))
                if response.url.startswith(api_url + "/api/v1/") else None)
        page.goto(web_url)
        page.get_by_label("Operator token").fill(token)
        page.get_by_role("button", name="Connect / refresh").click()
        page.get_by_text("Create a new booking-v1 match", exact=True).click()
        # Blank labels are intentionally sent as null by B's actual dashboard.
        with page.expect_response(lambda r: r.url == api_url + "/api/v1/matches" and r.request.method == "POST") as created:
            page.get_by_role("button", name="Create match", exact=True).click()
        match = created.value.json()
        assert created.value.status == 201, match
        mid = match["match_id"]
        assert match["provider_labels"] == {"a": None, "b": None}
        expect(page.get_by_role("article", name="Contender A")).to_contain_text("Unknown provider / model")
        shas, submitted = {}, {}
        for slot in ("a", "b"):
            assignment = bridge(slot, "assignment", "--match", mid, "--slot", slot)
            assert assignment["provider_labels"] == match["provider_labels"]
            shas[slot] = commit(slot, "known-good/booking.py" if slot == "a" else "known-bad/repeat_cancel.py",
                                "Labelled deterministic initial fixture")
            if slot == "a":
                job = bridge(slot, "check", "--match", mid, "--slot", slot, "--commit", shas[slot])
                practiced = bridge(slot, "job", "--id", job["job_id"], "--wait", "--timeout", "120")
                assert practiced["kind"] == "practice" and practiced["result"]["status"] == "passed"
            request_id = str(uuid4())
            command = ("submit", "--match", mid, "--slot", slot, "--commit", shas[slot], "--request-id", request_id)
            submitted[slot] = bridge(slot, *command)
            assert bridge(slot, *command) == submitted[slot]
        for slot in ("a", "b"):
            job = bridge(slot, "job", "--id", submitted[slot]["job_id"], "--wait", "--timeout", "120")
            assert job["result"]["status"] == ("passed" if slot == "a" else "failed")
        hidden = bridge("a", "match", "--id", mid)
        assert hidden["slots"]["b"]["candidate"] is None

        def click_action(name):
            page.get_by_label("Decision / action reason").fill("Labelled fixture compatibility check; no native Switch agents")
            button = page.get_by_role("button", name=name, exact=True)
            expect(button).to_be_enabled(timeout=15000)
            with page.expect_response(lambda r: r.request.method == "POST" and r.url.startswith(api_url + "/api/v1/matches/")) as result:
                button.click()
            assert result.value.status == 200, result.value.text()
            return result.value.json()

        revealed = click_action("Reveal both submissions")
        assert revealed["phase"] == "reviewing"
        assignments = {s: bridge(s, "assignment", "--match", mid, "--slot", s) for s in ("a", "b")}
        assert all((Path(a["review_path"]) / "src/booking.py").is_file()
                   for a in assignments.values())
        scenario = json.loads((ROOT / "contracts/arena-v1.1.json").read_text())["cli_surface"]["challenge_file"]["example"]
        challenge_file = state / "challenge.json"
        challenge_file.write_text(json.dumps(scenario))
        challenge = bridge("a", "challenge", "--match", mid, "--target", assignments["a"]["target_candidate_id"],
                           "--file", str(challenge_file))
        reproduced = bridge("a", "job", "--id", challenge["job_id"], "--wait", "--timeout", "120")
        assert reproduced["result"]["status"] == "reproduced", reproduced
        for slot in ("a", "b"):
            bridge(slot, "review-done", "--match", mid, "--slot", slot, "--target", assignments[slot]["target_candidate_id"])
        click_action("Accept requirement violation")
        repairing = click_action("Start repair round")
        assert repairing["phase"] == "repairing"
        for slot in ("a", "b"):
            sha = commit(slot, "known-good/booking.py", "Labelled deterministic repaired fixture")
            submitted[slot] = bridge(slot, "submit", "--match", mid, "--slot", slot, "--commit", sha)
        for slot in ("a", "b"):
            job = bridge(slot, "job", "--id", submitted[slot]["job_id"], "--wait", "--timeout", "120")
            assert job["result"]["status"] == "passed" and job["result"]["check_count"] == 12
        selected = click_action("Select contender A")
        assert selected["phase"] == "complete" and selected["outcome"]["selection"] == "a"
        artifacts = {}
        for name, button in (("patch", "Open selected patch ↗"), ("evidence", "Open evidence pack ↗")):
            page.get_by_role("button", name=button, exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            expect(dialog.locator("pre")).not_to_have_text("")
            with page.expect_download() as download:
                dialog.get_by_role("button", name="Download artifact ↓").click()
            artifacts[name] = state / download.value.suggested_filename
            download.value.save_as(artifacts[name])
            page.get_by_role("button", name="Close artifact").click()
        _verify_patch(state, artifacts["patch"], selected)
        assert json.loads(artifacts["evidence"].read_text())["match"]["outcome"]["selection"] == "a"
        page.screenshot(path=str(state / "dashboard.png"), full_page=True)
        assert not errors, errors
        assert api_responses and all(mode == "live" for _, mode in api_responses), api_responses
        assert all(status < 400 for status, _ in api_responses), api_responses
        summary = {"kind": "labelled_fixtures_live_engine_unchanged_B_clients", "native_switch": False,
                   "contract_version": "1.1", "match_id": mid, "state_dir": str(state),
                   "dashboard": "create/reveal/adjudicate/repair/select/inspect/download passed",
                   "bridge": "assignment/practice/submit/retry/job/challenge/review-done/match passed",
                   "patch": "applied on fresh task base; 12 Docker checks passed", "browser_errors": errors}
        (state / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary))


if __name__ == "__main__":
    main()
