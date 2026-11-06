# Local setup — Sprint 2

Run from the CodingArena repository root. Tested on Linux with Python 3.12.14 and Docker Engine 29.9.3; Python 3.11+ is the intended baseline, with other versions not yet verified. The default Docker image is pinned by digest; Docker must be accessible to the user running the engine.

Use a fresh runtime directory for the interactive session, separate from fixture smoke states, and keep this environment variable in both server and operator terminals:

```sh
export ARENA_STATE_DIR="$PWD/var/runtime"
```

The engine default remains repository `var/` if the variable is unset; initialization refuses any nonempty unmarked root, including one that already contains smoke subdirectories.

## Install and prepare

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.txt
docker pull python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
PYTHONPATH=engine .venv/bin/python -m arena_engine contract
PYTHONPATH=engine .venv/bin/python -m arena_engine init
PYTHONPATH=engine .venv/bin/python -m arena_engine doctor
```

`contract` verifies the frozen manifest digest. `init` creates the marked state directory, task base, separate `workers/a/worktree` and `workers/b/worktree` clones, and 0600 token files. It prints the operator token file path, not the token. Store the state under the gitignored `var/` by default; do not copy token values into prompts or logs. Repeated initialization reuses state and tokens. Initialization refuses an unmarked nonempty directory and any state with an active match.

`doctor` reports Docker/image readiness and whether state is initialized. It exits 0 when those preflight checks pass and never prints credentials. The running service health endpoint also reflects worker startup failures. Start the API and verification worker with:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine serve
curl http://127.0.0.1:8765/api/v1/health
```

The server defaults to `127.0.0.1:8765`; `serve --host HOST --port PORT` changes the bind address. Only one engine server can own a state directory at a time.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARENA_STATE_DIR` | repository `var/` | Marked runtime root, tokens, workspaces, SQLite, snapshots, artifacts, and operator retry journal |
| `ARENA_RUNNER_IMAGE` | pinned image digest above | Prepared Python runner image; mutable tags are rejected |
| `ARENA_API_URL` | `http://127.0.0.1:8765` | Operator CLI server URL |

Use a separate state directory for each match after either slot has changed its worktree. The engine never silently resets a slot checkout. Existing match history and snapshots remain in their original state directory.

## Operator commands

The CLI uses the operator token at `auth/operator.token` and sends it in memory as a bearer credential:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator create \
  --label-a "Agent A" --label-b "Agent B"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator match --match MATCH_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator job --id JOB_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action reveal --reason "Initial jobs finished"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action cancel --reason "Operator cancellation"
```

Create/action requests are journaled in `operator-requests/<request_id>.json` before sending; the file stores the exact request body and no token. A timeout or connection failure leaves the result unknown. Retry with the same request ID and body:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator retry --request-id REQUEST_UUID
```

Mutations also accept `--request-id UUID`, `--room-id`, `--message-id` and `--note`. Room/message IDs are context, not verified Switch authentication. `--source-kind fixture` explicitly labels scripted fixture operator actions; human CLI actions default to `operator_recorded`. A received error is a conclusive result for that ID; after fixing its cause use a new operation ID. A transport timeout always retries the original ID.

Only `reveal` and `cancel` actions are implemented in Sprint 2. Review, repair, finalize, and selection actions belong to Sprint 3. The API exposes token-scoped assignments and jobs; use the corresponding slot token for each agent. Workspaces are stable under `workers/{a,b}` and candidates must commit their allowed `src/booking.py` changes before submission.

## Checks and live fixture smoke

Run the local suite and optional fixture Docker check:

```sh
.venv/bin/python -m pytest -q engine/tests
ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests/test_runner.py
```

Practice verification executes 7 public checks. Official initial verification executes 11 baseline checks: those 7 public checks, 3 hidden checks, and BOOK-07 instance isolation. Hidden sources stay engine-owned. The official candidate status stays pending until Sprint 3 review and eligibility handling are implemented.

For an end-to-end fixture run through a real local HTTP server and Docker runner:

```sh
.venv/bin/python scripts/smoke_engine.py --snapshot contracts/sprint2-api-snapshot.json
```

The script creates a fresh `var/smoke-*` state, uses known-good and known-bad fixture implementations, checks API projections and request idempotency, runs practice and official jobs, reveals, and cancels. It does not touch existing state, use a Switch session, or exercise B's client. Its non-secret API response snapshot is for B to compare against. This fixture smoke does not count as live native-agent evidence.
