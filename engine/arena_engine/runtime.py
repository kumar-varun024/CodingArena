"""Read-only runtime preflight. Never reads or prints runtime credentials."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contract import ROOT

DEFAULT_IMAGE = "python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54"


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    runner_image: str

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.environ.get("ARENA_STATE_DIR", str(ROOT / "var"))).expanduser().resolve(),
            os.environ.get("ARENA_RUNNER_IMAGE", DEFAULT_IMAGE),
        )


def _docker(*args: str) -> bool:
    try:
        completed = subprocess.run(
            ["docker", *args], capture_output=True, timeout=5, check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def runtime_status(settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    pinned = re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}", settings.runner_image) is not None
    docker_available = _docker("info", "--format", "{{.ServerVersion}}")
    image_available = pinned and docker_available and _docker("image", "inspect", settings.runner_image)
    return {
        "docker_available": docker_available,
        "image_pinned": pinned,
        "image_available": image_available,
        "runner_image": settings.runner_image,
        # The production job executor belongs to Sprint 2. Image readiness alone
        # must not be reported as a working official verification runner.
        "runner_available": False,
        "executor_implemented": False,
        "state_initialized": (settings.state_dir / ".arena-state").is_file(),
    }
