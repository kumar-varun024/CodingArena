# Engine — Sprint 3 first-match workflow

The engine provisions stable slot workspaces, persists matches and jobs in SQLite, freezes candidate source, and runs practice, official verification, and challenge reproduction in restricted Docker containers. Sprint 3 adds review, operator adjudication, repair rounds, fresh final verification, selection, and downloadable evidence. This is fixture-backed engine functionality; it is not evidence of a live Switch match or B-client integration, and the product is not complete. Sprint 4 requires the user to initiate integration of both ready branches.

## Run locally

From the repository root:

```sh
export ARENA_STATE_DIR="$PWD/var/runtime"
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

## Match, review, and repair

The operator creates a match and receives two isolated slot workspaces. Each slot commits its allowed source file and submits a commit SHA. The engine freezes that source and runs public practice or the full baseline verification. After both initial verification jobs are terminal, the operator reveals the candidates. Slots can then inspect the exact frozen opponent snapshot and submit challenges against that candidate.

A challenge carries a bounded JSON scenario and requirement IDs. The trusted runner executes that exact scenario against the private reference first. The reference must pass before the target is run, and the target must fail in two fresh verification environments for the challenge to be `reproduced`. A reference mismatch or invalid scenario is `invalid` and auto-rejected; a target pass is `not_reproduced` and auto-rejected. Runner failure, cancellation, malformed results, or inconsistent target attempts are `inconclusive`: the disposition stays pending until the operator explicitly rejects it with a reason or cancels the match. An inconclusive attempt may be retried. Exact conclusive duplicates for the same frozen target are reused.

Both slots must explicitly complete review against the exact opponent candidate before review can advance. The operator may accept only a reproduced challenge and must give a reason. Acceptance adds that scenario to the common regression suite and invalidates both candidates' prior verification evidence. Rejected challenges do not change the suite.

The operator can start a repair round only after every challenge has a resolved disposition and both reviews are complete. Each slot may submit once in the round; queued repair verification waits until both submissions arrive. The round cap is set at match creation and is at most two. Once both new candidates are verified, the match returns to decision. If verification infrastructure fails, the operator can finalize again against the same frozen candidate snapshots without spending a repair round.

When no repair is needed, `finalize` also advances resolved review directly to verification without consuming a repair round. New matches pin their specification text, baseline cases and private reference. A legacy Sprint 2 match without a frozen reference must be cancelled and recreated before submitting challenges; changed legacy baselines are refused rather than silently substituted.

From decision, the operator can finalize for a fresh full-suite run or select a candidate or `neither`. Selection of a candidate requires the current eligible candidate revision and its exact latest evidence key (candidate, spec, suite, and runner digests). This prevents stale or mismatched verification from being selected. `neither` is available from decision without a candidate or evidence key.

## Operator CLI and retries

The CLI reads the operator token from the state directory and sends requests to `ARENA_API_URL`:

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
  --match MATCH_ID --action finalize --reason "Run the current candidates against the full suite"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select \
  --match MATCH_ID --selection a --candidate CANDIDATE_ID \
  --evidence-key var/evidence-key.json --reason "Current evidence supports selection"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select \
  --match MATCH_ID --selection neither --reason "Neither candidate is eligible"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator export --match MATCH_ID
```

For candidate selection, `--evidence-key` names a JSON file containing the exact `EvidenceKey` returned with the candidate's latest verification. After completion, `export` downloads `evidence.json`, `summary.md`, and, when a candidate was selected, `candidate.patch` under the state directory's `exports/<match-id>/` by default. Supply `--output DIR` to choose another destination; existing different files are not overwritten.

Every mutation takes a caller-visible UUID `request_id`. The CLI writes the exact canonical body and endpoint to `operator-requests/<request_id>.json` with mode `0600`; the journal contains no token. If transport fails, the outcome is unknown. Retry the saved operation with the same identifier:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator retry --request-id REQUEST_UUID
```

Successful writes and deliberate operation errors are persisted under that ID. A received error is conclusive for that operation; after correcting its cause, initiate a new operation with a new ID. Ambiguous transport failures always retry the original ID/body. Provider labels are operator-supplied context, recorded in the common `match.created` event.

## HTTP and trusted execution

The API is under `/api/v1`. `GET /health` is public. Match, assignment, submission, practice, events, jobs, artifacts, challenge, review, decision, selection, and action endpoints use `Authorization: Bearer <token>`. Writes require a UUID `request_id` and a `source` object. The operator controls phases and decisions; a slot can submit or practice only for itself. Challenge schemas are validated before job creation (HTTP 422 for malformed requests). APIs expose concise results and logs, not private reference source or held-out test source.

Practice runs the public cases plus all accepted regressions. Initial and final candidate verification run the configured full baseline and accepted challenge regressions, including the separate BOOK-07 instance-isolation check. Passing verification records an evidence key tied to the frozen candidate, task specification, suite, and runner. Only evidence matching the current values can make a candidate eligible for selection. Practice results never establish eligibility; private practice jobs/events are excluded from the common exported evidence.

The Docker runner uses the pinned image by image ID, fresh disposable containers, `--network none`, a read-only root filesystem, read-only candidate and trusted-driver mounts, non-root UID/GID 65534, dropped capabilities, `no-new-privileges`, one CPU, 128 MiB memory, 32 process limit, and a 16 MiB no-exec temporary filesystem. Each case has a bounded wall-clock limit and captured output is capped. No candidate dependencies are installed. Candidate modules are imported only by the trusted driver inside these containers, never by the service process.

SQLite persists matches, jobs, events, artifacts, and idempotency records. At startup, interrupted jobs are marked as errors; queued work resumes when runner startup cleanup succeeds. Interrupted challenge reproduction becomes inconclusive and requires operator resolution. Failed cleanup blocks the worker and records queued work as errors. The engine removes abandoned labeled runner containers for its state root. The state lock prevents a second server from using the same directory.

## Fixture evidence and interface

The deterministic HTTP plus Docker fixture smoke can exercise the short reveal/cancel path or the full challenge, repair, selection, and export flow:

```sh
.venv/bin/python scripts/smoke_engine.py --snapshot contracts/sprint3-api-snapshot.json
.venv/bin/python scripts/smoke_engine.py --full-match --snapshot contracts/sprint3-api-snapshot.json
.venv/bin/python scripts/smoke_engine.py --neither
```

The script provisions a fresh `var/smoke-*` state and uses labeled fixtures. `--full-match` exercises reference-pass/target-fail-twice reproduction, invalid challenge rejection, acceptance and shared-suite invalidation, repair verification, exact-key selection, and artifact export. `--neither` keeps both fixtures broken through the repair cap and selects neither. These runs do not exercise a native Switch agent or B's client, and fixture results are not live match evidence.

The active manifest is [arena-v1.1.json](../contracts/arena-v1.1.json), canonical SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`, identical to B's embedded 1.1 specification. The historical [arena-v1.json](../contracts/arena-v1.json) remains unchanged. Health advertises 1.1 on the existing `/api/v1` base.

Every API response carries `X-Arena-Mode: live`, including framework/auth errors and text/JSON artifacts. Only Health and Match bodies have a top-level mode. Optional `ARENA_UI_ORIGIN` enables exact-origin CORS and exposes mode/download headers; the default Vite proxy preserves them without CORS configuration. Match and Assignment return the persisted operator labels unchanged, including nulls, before reveal and across restart. Older saved Match retry responses gain the same labels without changing retry identity. Existing 1.0 task workspaces remain readable; new state records 1.1.

Challenge requests reject duplicate requirement IDs. The single-instance scenario DSL is unchanged; every official full verification still includes the trusted BOOK-07 multi-instance check, including repair and recovery reruns.
