# Local setup — Sprint 3

Run from the CodingArena repository root. Tested on Linux with Python 3.12.14 and Docker Engine 29.9.3; Python 3.11+ is the intended baseline, with other versions not yet verified. Docker must be accessible to the user running the engine.

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

`contract` verifies the frozen manifest digest. `init` creates the marked state directory, task base, separate slot worktree clones, and token files with mode `0600`. It prints the operator token file path, not the token. Store runtime state under the gitignored `var/` by default; do not copy token values into prompts or logs. Repeated initialization reuses state and tokens. Initialization refuses an unmarked nonempty directory and any state with an active match.

`doctor` reports Docker/image readiness and whether state is initialized. It exits 0 when those preflight checks pass and never prints credentials. Start the API and verification worker with:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine serve
curl http://127.0.0.1:8765/api/v1/health
```

The server defaults to `127.0.0.1:8765`; `serve --host HOST --port PORT` changes the bind address. Only one engine server can own a state directory at a time.

## Configuration and runtime state

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARENA_STATE_DIR` | repository `var/` | Marked runtime root, tokens, workspaces, SQLite, snapshots, artifacts, and operator retry journal |
| `ARENA_RUNNER_IMAGE` | pinned image digest above | Prepared Python runner image; mutable tags are rejected |
| `ARENA_API_URL` | `http://127.0.0.1:8765` | Operator CLI server URL |
| `ARENA_UI_ORIGIN` | unset | Optional exact UI origin for direct browser access; exposes mode and download headers. B's default Vite proxy needs no CORS setting. |

The declared build budget is advisory; the engine does not measure provider cost or enforce generation quotas. Use a separate state directory for a later match after either slot has changed its worktree. The engine never silently resets a slot checkout. Keep existing state directories when their match history and snapshots are needed.

## Operator workflow

Create a match, read assignments with the respective slot tokens, and have both slots commit and submit their allowed source file. The operator waits for both verification jobs to become terminal before reveal. Once revealed, slots can inspect exact opponent snapshots and submit bounded scenario challenges during review. Each challenge is checked against the private reference and then run against its exact frozen target twice. Invalid or not-reproduced challenges are rejected automatically. Inconclusive challenges remain pending until the operator rejects them with a reason or cancels the match; they can be retried.

Both slots must complete review against the exact opponent candidate. The operator may accept only a reproduced challenge. Acceptance updates the common regression suite and invalidates both candidates' earlier evidence. After every challenge is resolved and both reviews are complete, the operator may start a repair round. Each slot submits once; the queued repair verification waits for both submissions. The match returns to decision when both verifications finish. The repair cap is chosen at creation and cannot exceed two rounds. If verification infrastructure fails, use `finalize` from decision to rerun the unchanged candidate snapshots without spending a repair round.

Example operator commands:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator create \
  --label-a "Agent A" --label-b "Agent B" --budget-minutes 10 --max-repair-rounds 2
PYTHONPATH=engine .venv/bin/python -m arena_engine operator match --match MATCH_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator job --id JOB_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action reveal --reason "Both initial jobs are terminal"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator decision \
  --match MATCH_ID --challenge CHALLENGE_ID --disposition accepted \
  --reason "The reproduced scenario violates the cited requirement"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action start_repair --reason "Review is resolved"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action finalize --reason "Rerun current candidates"
```

Selection from decision requires the latest eligible candidate and its exact current evidence key. Save that key object from the match response as JSON, then pass its file to the CLI:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select \
  --match MATCH_ID --selection a --candidate CANDIDATE_ID \
  --evidence-key var/evidence-key.json --reason "Current evidence supports selection"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select \
  --match MATCH_ID --selection neither --reason "Neither candidate is eligible"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator export --match MATCH_ID
```

`export` downloads `evidence.json`, `summary.md`, and `candidate.patch` when a candidate was selected, by default under `<state_dir>/exports/<match-id>/`. Use `--output DIR` for another destination. It refuses to overwrite different files. The common evidence pack excludes private practice jobs/events. No patch is exported for neither, and the service never applies a patch automatically.

Mutations accept `--request-id UUID`, `--room-id`, `--message-id`, and `--note`. Before sending, the CLI journals the exact canonical request body and endpoint under `operator-requests/<request_id>.json` with mode `0600`; the journal contains no token. A timeout or connection failure leaves the result unknown. Retry with the same ID and body:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator retry --request-id REQUEST_UUID
```

A received error is conclusive for that operation; after fixing its cause use a new request ID. A transport timeout always retries the original request. Source room/message IDs are context, not verified Switch authentication. CLI operator actions default to `operator_recorded`; use `--source-kind fixture` for scripted fixture operations.

## Checks and fixture smoke

Run the deterministic engine fixture workflows against a real local HTTP server and Docker runner:

```sh
.venv/bin/python scripts/smoke_engine.py --snapshot contracts/sprint3-api-snapshot.json
.venv/bin/python scripts/smoke_engine.py --full-match --snapshot contracts/sprint3-api-snapshot.json
.venv/bin/python scripts/smoke_engine.py --neither
```

Each invocation creates an isolated `var/smoke-*` state and does not reset existing state. The full-match fixture covers challenge reproduction and rejection, review, accepted regressions, repair, exact evidence-key selection, and export. The neither fixture keeps both candidates broken through the repair cap and verifies `neither` selection. The snapshot contains non-secret HTTP response samples for API/client comparison. These workflows use labeled fixtures; they are not a live Switch agent match and do not establish B-client integration. Do not report them as native-agent evidence or as final product completion.

The active interface is frozen in `contracts/arena-v1.1.json`, canonical SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. The historical 1.0 manifest remains unchanged. `contract` and health report 1.1; the HTTP base remains `/api/v1`. Every API response carries `X-Arena-Mode: live`, including errors and artifact downloads. Match/Assignment include the original operator-recorded provider labels; unknown labels are null. The operator CLI defaults omitted labels to null.

Existing initialized 1.0 state can be served without resetting workspaces, tokens, jobs or matches: 1.1 preserves the task and layout. New state records 1.1. Do not reinitialize an active match to upgrade it.

## Verify the unchanged experience branch

`scripts/smoke_experience.py` runs B's actual dashboard in Chromium and B's contestant CLI against a fresh live engine and restricted Docker runner. Supply a checkout/export of the experience branch with `web/` dependencies installed (`npm --prefix /path/to/experience/web ci`). The script never edits B's source. It creates a new `var/experience-smoke-*` runtime and stops its servers afterward.

With system Chromium installed, prepare a separate browser-test environment:

```sh
python3 -m venv var/browser-tools
var/browser-tools/bin/python -m pip install playwright==1.64.1
var/browser-tools/bin/python scripts/smoke_experience.py \
  --experience-root /path/to/experience --chromium /usr/bin/chromium
```

The engine interpreter defaults to `.venv/bin/python`; override with `--engine-python PATH` if needed. The browser uses direct API access with an exact-origin CORS setting on temporary ports. The dashboard creates a match with unknown labels, reveals submissions, accepts the reproduced requirement violation, starts repair, selects an eligible candidate, and inspects/downloads patch and JSON evidence. The unchanged CLI exercises all contestant commands and identical-request retries. Deterministic known-good/broken modules supply candidates, executed only by Docker. The selected patch is applied to a fresh disposable task base and rechecked against the full suite plus the accepted regression and BOOK-07 isolation. `summary.json`, `dashboard.png` and server logs stay under the new runtime directory. This is a fixture compatibility check, not a native Switch match.

Run all checks, including the actual Docker tests, with `ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests`. Tests without this variable explicitly skip Docker tests; a skip is not execution evidence.
