# Local setup — Sprint 1

Run from the CodingArena repository root. Tested with Python 3.12.14 on Linux and Docker Engine 29.9.3. Python 3.11+ is the intended baseline; other interpreter versions have not yet been verified. Docker must run on the same machine and be accessible to your user.

## Install

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.txt
```

Alternatively, if `uv` is installed:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r engine/requirements.txt
```

Dependencies and transitives are pinned in `engine/requirements.txt` to the versions installed during Sprint 1 verification. FastAPI, Uvicorn, pytest and HTTPX are the direct dependencies.

## Prepare the fixture runtime

```sh
docker pull python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
PYTHONPATH=engine .venv/bin/python -m arena_engine contract
PYTHONPATH=engine .venv/bin/python -m arena_engine doctor
```

Doctor exits 0 when Docker and the pinned image are available, 1 otherwise. It reports image readiness separately from the unimplemented production executor, whose `runner_available` remains false. It does not read tokens or initialize/overwrite paths. The real fixture check below verifies that containers can actually execute.

## Verify

```sh
.venv/bin/python -m pytest -q engine/tests
ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests/test_task_pack.py
```

The default test run explicitly skips Docker integration unless enabled. A skipped test is not runner evidence. The opt-in run must pass on the demo machine. For compact fixture-check diagnostics:

```sh
.venv/bin/python scripts/check_task_pack.py
```

## Start the foundation service

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine serve
curl http://127.0.0.1:8765/api/v1/health
```

`serve` accepts `--host` and `--port`, defaulting to `127.0.0.1:8765`. Sprint 1 exposes health only. Match creation, init, operator actions, tokens and persistent jobs are not implemented yet.

Configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARENA_STATE_DIR` | repository `var/` | Future runtime state root; doctor only checks its marker |
| `ARENA_RUNNER_IMAGE` | pinned digest above | Doctor image override; mutable tags are rejected as unprepared |
| `ARENA_DOCKER_TESTS` | unset | Set to `1` to execute Docker integration tests |

The fixture checker accepts `--image` explicitly; it does not install contestant dependencies. No cloud account or provider SDK is needed. Two real native Switch agents and B's client/UI will be configured later on one demo machine. See B-owned `docs/switch.md` when that branch is ready; Sprint 1 here has not exercised live Switch.
