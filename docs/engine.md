# Engine — Sprint 2 first-match flow

Sprint 2 provisions stable slot workspaces, scopes bearer tokens, persists matches and jobs in SQLite, freezes submitted source, and runs practice and official verification in Docker. The implemented match path covers creation, assignment, practice, one initial submission per slot, job/artifact polling, reveal, and cancellation. Review adjudication, repair, finalization, selection, and export are Sprint 3 work. Passing official checks leaves eligibility `pending` until review is resolved.

## Run locally

From the repository root:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine init
PYTHONPATH=engine .venv/bin/python -m arena_engine doctor
PYTHONPATH=engine .venv/bin/python -m arena_engine serve
```

`init` prints non-secret runtime metadata and the operator token file path. Read that file locally when needed; never put token values in logs, prompts, request journals, or client bundles. Re-running `init` reuses existing tokens and state. It refuses an unrelated nonempty directory and refuses to initialize while a match is active. It never resets an existing marked tree.

`doctor` checks Docker, the pinned image, and initialized state without printing credentials. It exits 0 when these preflight checks pass and 1 otherwise; the running service's health endpoint also reflects worker startup failures. `serve` binds to `127.0.0.1:8765` by default; use `serve --host HOST --port PORT` to override. One server process may hold a state directory at a time.

| Variable | Default | Use |
| --- | --- | --- |
| `ARENA_STATE_DIR` | repository `var/` | Runtime state root |
| `ARENA_RUNNER_IMAGE` | `python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54` | Docker runner image; must be pinned by digest |
| `ARENA_API_URL` | `http://127.0.0.1:8765` | Base URL for `operator` CLI commands |

## State and workspaces

The marked state root contains `.arena-state`, non-secret `runtime.json`, `arena.sqlite3`, `auth/operator.token`, and `workers/{a,b}`. The stable registered roots are `workers/a` and `workers/b`; each has a disposable Git clone at `worktree`, a private `.arena/slot.token`, and a `review` directory. Both clones start at the same commit built from the sanitized `booking-v1` starter: `SPEC.md`, public checks/cases, and `src/booking.py`. Reference code and held-out cases are excluded.

Token files have mode `0600`. The service reads credentials into memory at startup. Use the operator token only for operator actions and each slot token only for that slot. Submissions name a commit SHA; the engine derives the workspace from the authenticated role, verifies a clean allowed-file commit, and freezes `src/booking.py` under `snapshots/`. The caller cannot supply a path or test result. A slot cannot inspect the opponent candidate before reveal; assignment and job projections are role-scoped.

The engine permits one active match. A later match can start only if both worktrees are still clean at the pinned base. Sprint 2 does not reset used workspaces: after committing or otherwise changing a slot, provision a fresh state directory for the next match. Keep the old state if its records are needed. The declared build budget is advisory; the engine does not measure provider cost or enforce generation quotas. Provider labels are operator-supplied context.

## Operator CLI and retries

The CLI reads the operator token from the state directory and sends requests to `ARENA_API_URL`:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator create \
  --label-a "Agent A" --label-b "Agent B" --budget-minutes 10 --max-repair-rounds 2
PYTHONPATH=engine .venv/bin/python -m arena_engine operator match --match MATCH_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator job --id JOB_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action reveal --reason "Both initial verification jobs are terminal"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action \
  --match MATCH_ID --action cancel --reason "Operator cancellation"
```

Create and action mutations use a caller-visible UUID `request_id`. Before sending, the CLI writes the exact canonical body and endpoint to `operator-requests/<request_id>.json` with mode `0600`; the journal contains no token. If transport fails, the outcome is unknown. Retry the saved operation with the same identifier:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator retry --request-id REQUEST_UUID
```

Successful writes and deliberate operation errors are persisted under that ID. A received error is a conclusive result for that operation: after correcting its cause, initiate a new operation with a new ID. Ambiguous transport failures always retry the original ID/body. Provider labels are recorded in the common `match.created` event; v1 does not add a labels field to Match.

`operator action` accepts `reveal` and `cancel` in Sprint 2. Although `start_repair` and `finalize` are listed in the CLI parser and v1 contract, the service defers them with review, adjudication, and selection to Sprint 3.

## HTTP and verification

The API is under `/api/v1`. `GET /health` is public. Match, assignment, submission, practice, events, jobs, artifacts, and actions use `Authorization: Bearer <token>`. Writes require a UUID `request_id` and a `source` object. The operator creates matches and acts; a slot can submit or practice only for itself. `POST /matches/{id}/submissions` freezes an initial candidate once per slot; `POST /matches/{id}/practice` queues a public-only run that never creates a candidate or eligibility evidence. `GET /jobs/{id}` reports asynchronous job status; poll until `completed` or `error`.

Practice runs the 7 public cases. Official initial verification runs 11 baseline checks: 7 public, 3 held-out, and the separate BOOK-07 instance-isolation check. The API reports check IDs and results, not held-out test source. Passing all 11 checks records a passed verification, but the candidate remains `pending` until Sprint 3 review resolution and eligibility logic.

The Docker runner uses the pinned image by image ID, fresh disposable containers, `--network none`, a read-only root filesystem, read-only candidate and trusted-driver mounts, non-root UID/GID 65534, dropped capabilities, `no-new-privileges`, one CPU, 128 MiB memory, 32 process limit, and a 16 MiB no-exec temporary filesystem. Each check has a 10-second wall-clock limit and captured output is capped at 64 KiB. No candidate dependencies are installed. Candidate modules are imported only by the trusted driver inside these containers, never by the service process.

SQLite persists matches, jobs, events, artifacts, and idempotency records. At startup, a job left `running` is recorded as an error; queued jobs resume when runner startup cleanup succeeds. Failed cleanup blocks the worker and records queued work as error. The engine removes abandoned labeled runner containers for its state root. The state lock prevents a second server from using the same directory. In Sprint 2 an errored official submission requires cancelling this match and using fresh state; same-snapshot recovery finalization is Sprint 3 work.

## Smoke evidence and interface

Run the deterministic HTTP plus Docker fixture smoke with:

```sh
.venv/bin/python scripts/smoke_engine.py --snapshot contracts/sprint2-api-snapshot.json
```

It provisions a new `var/smoke-*` state, starts a local server, runs known-good and known-bad fixtures through practice and official jobs, checks projections/idempotency, reveals, and cancels. It does not reset existing state and does not exercise a native Switch agent or B's client. The saved snapshot contains non-secret HTTP response examples for B to compare with the client; it is not live Switch evidence.

The normative v1 manifest remains [arena-v1.json](../contracts/arena-v1.json), SHA-256 `3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80`. Sprint 2 does not change that contract.
