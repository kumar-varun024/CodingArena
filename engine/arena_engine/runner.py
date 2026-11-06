"""Restricted Docker runner for official booking-v1 verification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any

from .runtime import Settings

DRIVER = Path(__file__).with_name("driver.py")
_POLICY = b"arena-docker-policy-v1;network=none;readonly;nonroot;caps=drop-all;no-new-privileges;tmpfs=16m;cpu=1;memory=128m;pids=32;timeout=10"
_DOCKER_TIMEOUT = 15
_CASE_TIMEOUT = 10
_OUTPUT_LIMIT = 64 * 1024


class RunnerError(Exception):
    """Docker or trusted runner infrastructure failed."""


class DockerRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._image_id: str | None = None
        self._digest: str | None = None
        self._cancelled = threading.Event()
        self._active_lock = threading.Lock()
        self._active_name: str | None = None
        self._state_label = hashlib.sha256(str(settings.state_dir.resolve()).encode("utf-8")).hexdigest()

    def cancel(self) -> None:
        """Stop this runner's active job and prevent its remaining checks."""
        self._cancelled.set()
        with self._active_lock:
            name = self._active_name
        if name:
            try:
                subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=_DOCKER_TIMEOUT, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass

    @property
    def digest(self) -> str:
        if self._image_id is None:
            self._refresh_image()
        assert self._image_id is not None
        return hashlib.sha256(self._image_id.encode() + b"\0" + DRIVER.read_bytes() + b"\0" + _POLICY).hexdigest()

    def _run(self, args: list[str], *, timeout: int = _DOCKER_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RunnerError("Docker command unavailable or timed out") from exc

    def cleanup_interrupted(self) -> bool:
        """Remove containers left by this state root's previous process."""
        label = f"coding-arena.state={self._state_label}"
        listed = self._run(["ps", "--all", "--quiet", "--filter", f"label={label}"])
        if listed.returncode:
            raise RunnerError("Could not list interrupted runner containers")
        containers = listed.stdout.decode("utf-8", "replace").split()
        if not containers:
            return True
        removed = self._run(["rm", "--force", *containers])
        if removed.returncode:
            raise RunnerError("Could not remove interrupted runner containers")
        return True

    def _refresh_image(self) -> str:
        if re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}", self.settings.runner_image) is None:
            raise RunnerError("Runner image must be pinned by sha256")
        daemon = self._run(["info", "--format", "{{.ServerVersion}}"])
        if daemon.returncode:
            raise RunnerError("Docker daemon unavailable")
        image = self._run(["image", "inspect", "--format", "{{.Id}}", self.settings.runner_image])
        if image.returncode:
            raise RunnerError("Pinned runner image unavailable")
        image_id = image.stdout.decode("utf-8", "replace").strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise RunnerError("Docker returned an invalid image identity")
        self._image_id = image_id
        self._digest = hashlib.sha256(image_id.encode() + b"\0" + DRIVER.read_bytes() + b"\0" + _POLICY).hexdigest()
        return image_id

    def available(self) -> bool:
        try:
            self._refresh_image()
            return True
        except (RunnerError, OSError):
            return False

    @staticmethod
    def _reader(stream: Any, output: bytearray, overflow: threading.Event) -> None:
        while True:
            block = stream.read(8192)
            if not block:
                return
            remaining = _OUTPUT_LIMIT - len(output)
            if remaining > 0:
                output.extend(block[:remaining])
            if len(block) > remaining:
                overflow.set()

    def _case(self, candidate: Path, driver_dir: Path, scenario: dict | None,
              cancel_event: threading.Event) -> dict:
        image_id = self._image_id or self._refresh_image()
        name = "arena-run-" + uuid.uuid4().hex
        interactive = scenario is not None
        create_args = ["create", "--name", name, "--network", "none", "--read-only",
                       "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--user", "65534:65534",
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--cpus", "1",
                       "--memory", "128m", "--pids-limit", "32",
                       "--mount", f"type=bind,src={driver_dir},dst=/trusted,readonly",
                       "--mount", f"type=bind,src={candidate.parent},dst=/candidate,readonly",
                       "--label", f"coding-arena.state={self._state_label}",
                       "--pull=never"]
        if interactive:
            create_args.append("--interactive")
        create_args += [image_id, "python", "-I", "/trusted/driver.py",
                       "/candidate/booking.py"]
        if not interactive:
            create_args.append("--check-instance-isolation")
        created = False
        try:
            if cancel_event.is_set() or self._cancelled.is_set():
                raise RunnerError("Verification cancelled")
            created_result = self._run(create_args)
            if created_result.returncode:
                raise RunnerError("Could not create verification container")
            created = True
            with self._active_lock:
                self._active_name = name
            if cancel_event.is_set() or self._cancelled.is_set():
                raise RunnerError("Verification cancelled")
            start_args = ["start", "--attach"] + (["--interactive"] if interactive else []) + [name]
            try:
                process = subprocess.Popen(["docker", *start_args], stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError as exc:
                raise RunnerError("Could not start verification container") from exc
            stdout, stderr = bytearray(), bytearray()
            overflow = threading.Event()
            threads = [threading.Thread(target=self._reader, args=(process.stdout, stdout, overflow), daemon=True),
                       threading.Thread(target=self._reader, args=(process.stderr, stderr, overflow), daemon=True)]
            for thread in threads:
                thread.start()
            try:
                if interactive:
                    assert process.stdin is not None
                    process.stdin.write((json.dumps(scenario, separators=(",", ":")) + "\n").encode())
                    process.stdin.close()
                deadline = time.monotonic() + _CASE_TIMEOUT
                while True:
                    if cancel_event.is_set() or self._cancelled.is_set():
                        process.kill()
                        process.wait()
                        raise RunnerError("Verification cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        process.kill()
                        process.wait()
                        raise RunnerError("Verification container timed out")
                    try:
                        code = process.wait(timeout=min(0.1, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BrokenPipeError as exc:
                process.kill()
                process.wait()
                raise RunnerError("Verification container timed out or stopped accepting input") from exc
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for thread in threads:
                    thread.join(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            if overflow.is_set():
                raise RunnerError("Verification output exceeded limit")
            if code not in (0, 1):
                raise RunnerError("Verification container execution failed")
            try:
                # Candidate prints may precede the trusted driver's final JSON line.
                lines = stdout.decode("utf-8").splitlines()
                if not lines:
                    raise ValueError("empty driver output")
                result = json.loads(lines[-1])
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise RunnerError("Trusted driver returned malformed output") from exc
            if (type(result) is not dict or set(result) != {"passed", "failed_step", "summary"}
                    or type(result["passed"]) is not bool
                    or (result["failed_step"] is not None and type(result["failed_step"]) is not int)
                    or type(result["summary"]) is not str or code != (0 if result["passed"] else 1)):
                raise RunnerError("Trusted driver returned an invalid result")
            return result
        finally:
            try:
                if created:
                    try:
                        removed = self._run(["rm", "--force", name])
                    except RunnerError:
                        raise
                    if removed.returncode:
                        raise RunnerError("Could not clean up verification container")
            finally:
                with self._active_lock:
                    if self._active_name == name:
                        self._active_name = None

    def verify(self, source: Path, scenarios: list[dict], include_isolation: bool,
               cancel_event: threading.Event | None = None) -> dict:
        self._cancelled.clear()
        cancellation = cancel_event or threading.Event()
        source = Path(source)
        try:
            if cancellation.is_set():
                raise RunnerError("Verification cancelled")
            if not source.is_file() or source.is_symlink():
                raise RunnerError("Candidate snapshot is not a regular file")
            with tempfile.TemporaryDirectory(prefix="arena-run-") as temp:
                root = Path(temp)
                cand_dir, drv_dir = root / "candidate", root / "trusted"
                cand_dir.mkdir(mode=0o700)
                drv_dir.mkdir(mode=0o700)
                with source.open("rb") as src, (cand_dir / "booking.py").open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                shutil.copyfile(DRIVER, drv_dir / "driver.py")
                os.chmod(cand_dir, 0o755)
                os.chmod(drv_dir, 0o755)
                checks: list[tuple[str, dict | None]] = []
                for item in scenarios:
                    if (type(item) is not dict or type(item.get("check_id")) is not str
                            or type(item.get("scenario")) is not dict):
                        raise RunnerError("Invalid trusted verification case")
                    checks.append((item["check_id"], item["scenario"]))
                if include_isolation:
                    checks.append(("HELD-BOOK-07-ISOLATION", None))
                failed: list[str] = []
                lines: list[str] = []
                for check_id, scenario in checks:
                    if cancellation.is_set() or self._cancelled.is_set():
                        raise RunnerError("Verification cancelled")
                    result = self._case(cand_dir / "booking.py", drv_dir, scenario, cancellation)
                    passed = result["passed"]
                    lines.append(f"{check_id}: {'PASS' if passed else 'FAIL'}")
                    if not passed:
                        failed.append(check_id)
                return {"check_count": len(checks), "passed_count": len(checks) - len(failed),
                        "failed_check_ids": failed, "log": "\n".join(lines)}
        except RunnerError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise RunnerError("Could not prepare verification snapshot") from exc
