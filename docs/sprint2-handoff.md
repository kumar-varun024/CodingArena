# Sprint 2 and Sprint 3 client integration handoff

Role A supplies the engine; Role B connects the dashboard, API client and Switch bridge. The engine now implements the complete Sprint 3 match workflow. B should first verify the Sprint 2 connection flow, then wire review, challenges, repair, selection and export against the same pinned engine.

Updated 6 November 2026. A's Sprint 3 engine is implemented, committed and verified with labelled fixtures. B's real-client checkpoint and shared contract-hash confirmation remain pending. The genuine human plus two-native-agent demonstration and combined branch integration remain Sprint 4 work.

## Get the pinned engine

Repository access is required. Use the existing shared repository's `origin` remote.

| Item | Value |
| --- | --- |
| Published branch | `feat/arena-engine` |
| Pinned commit | `dffecf4829f851074254d919ec4e21a577dd639c` |
| Commit subject | `feat: complete sprint 3 engine review repair and export workflow` |
| API contract | `contracts/arena-v1.json`, version `1.0` |
| Canonical contract SHA-256 | `3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80` |

From an existing clone, create a separate engine checkout so B can keep working on the experience branch:

```sh
git fetch origin feat/arena-engine
git worktree add --detach ../CodingArena-engine-sprint3 dffecf4829f851074254d919ec4e21a577dd639c
cd ../CodingArena-engine-sprint3
git rev-parse HEAD
```

The last command must print the full pinned commit above. Choose a different unused checkout path if this one already exists. Keep both feature branches separate until the planned integration sprint.

The pinned checkout includes `docs/setup.md`, `docs/engine.md`, `docs/integration.md` and `contracts/sprint3-api-snapshot.json`. Use the Sprint 3 snapshot for current full-match response examples; `contracts/sprint2-api-snapshot.json` remains the earlier connection-flow reference. Both contain labelled fixture-client responses from real HTTP/Docker runs. The v1 contract and its canonical hash are unchanged.

## Install and start the engine

Prerequisites: Git, Python, and a running Docker daemon accessible to the current user. The recorded baseline used Linux, Python 3.12.14 and Docker Engine 29.9.3. Python 3.11+ is the intended baseline; other versions were not verified in that checkpoint.

Run from the pinned engine checkout. Use an unused state directory for this integration session:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.txt
docker pull python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54

export PYTHONPATH="$PWD/engine"
export ARENA_STATE_DIR="$PWD/var/sprint3-client"

.venv/bin/python -m arena_engine contract
.venv/bin/python -m arena_engine init
.venv/bin/python -m arena_engine doctor
.venv/bin/python -m arena_engine serve
```

`contract` must report version `1.0` and the canonical hash above. Use this command for hash confirmation: hashing the raw file bytes is a different operation. `doctor` must exit successfully. `serve` stays in the foreground; use another terminal for the client and HTTP checks.

In a second terminal:

```sh
curl --fail-with-body http://127.0.0.1:8765/api/v1/health
```

Expected response:

```json
{"api_version":"1.0","mode":"live","runner_available":true,"status":"ok"}
```

If running operator commands in another terminal, first enter the same engine checkout and repeat both `export` lines. One server can own a state directory at a time. Initialization reuses an existing valid state; it does not reset workspaces. After either slot changes its worktree, use a new state directory for the next match and restart the engine with that directory. Preserve the old state for its records.

Start a fresh match for this checkpoint. A legacy Sprint 2 match without a frozen reference must be cancelled and recreated before challenges can run.

## Connect the client and agents

For the first checkpoint, run the engine, client dev server, bridge and native agents on one integration machine. The engine freezes commits from its own task worktrees; a commit that exists only on another laptop cannot be submitted by SHA alone. `127.0.0.1` refers to the machine making the connection.

| Setting | Value |
| --- | --- |
| Engine origin | `http://127.0.0.1:8765` |
| API prefix | `/api/v1` |
| Dashboard development URL | `http://127.0.0.1:5173` |
| Browser request path | `/api/v1/...`, through the client dev-server proxy |
| Bridge request URL | `http://127.0.0.1:8765/api/v1/...` |
| Request body format | UTF-8 JSON; `Content-Type: application/json` |
| Authentication | `Authorization: Bearer <runtime token>` |
| Job polling | Every 2 seconds; show an unresolved outcome after the 120-second client timeout |

The engine has no CORS middleware. Configure the client dev server to forward `/api` to the engine while preserving the path and authorization header. For a Vite client, add this property to the existing configuration:

```ts
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8765',
      changeOrigin: true,
    },
  },
},
```

`ARENA_API_URL` configures the engine's operator CLI. B must configure the browser client and bridge URLs in their respective components.

Initialization creates these paths under `ARENA_STATE_DIR`:

| Consumer | Credential file | Workspace configuration |
| --- | --- | --- |
| Human dashboard/operator | `auth/operator.token` | Controls match creation, phases, challenge decisions and selection |
| Agent A | `workers/a/.arena/slot.token` | Register `workers/a`; edit its `worktree` directory |
| Agent B | `workers/b/.arena/slot.token` | Register `workers/b`; edit its `worktree` directory |

Enter the operator token at runtime and keep it in dashboard memory. Each agent/bridge reads only its own slot credential locally. Keep token values out of source, prompts, build variables such as `VITE_*`, logs, screenshots and operation journals. Token files have mode `0600`.

Use the absolute `workspace_path` returned by each assignment. Candidates must commit their own changes to `src/booking.py` in that task checkout. Submission requires the current lowercase 40-character HEAD SHA, a clean worktree, ancestry from the assigned base, and changes confined to the allowed file. Keep contestant execution inside the engine's restricted Docker runner.

## Connect the Sprint 2 API flow

All paths below are relative to `/api/v1`. The contract defines the complete shapes and error envelope.

| Step | Request | Credential and result |
| --- | --- | --- |
| Check readiness | `GET /health` | Public; require `runner_available: true` |
| Create match | `POST /matches` | Operator; `201` with Match and `match_id` |
| Fetch assignments | `GET /matches/{id}/assignments/{slot}` | Operator or matching slot; Assignment |
| Read match and events | `GET /matches/{id}` and `GET /matches/{id}/events?after={seq}` | Operator or participating slot; role-filtered data |
| Optional practice | `POST /matches/{id}/practice` | Matching slot; public cases plus accepted regressions; `202` with `job_id` |
| Submit each candidate | `POST /matches/{id}/submissions` | Matching slot; `202` with `candidate_id`, `job_id`, `tree_digest` |
| Poll work | `GET /jobs/{job_id}` | Operator or authorized slot; wait for `completed` or `error` |
| Read permitted logs | `GET /artifacts/{artifact_id}` | Operator or authorized slot; use returned artifact IDs |
| Change phase or cancel | `POST /matches/{id}/actions` | Operator; `reveal`, `start_repair`, `finalize` or `cancel`; updated Match |

Generate a fresh UUID for each logical POST. The UUIDs below illustrate distinct operations; replace them for a new run. A human dashboard create request has this shape:

```json
{
  "request_id": "11111111-1111-4111-8111-111111111111",
  "task_id": "booking-v1",
  "provider_labels": {"a": "Agent A", "b": "Agent B"},
  "candidate_budget_minutes": 10,
  "max_repair_rounds": 2,
  "source": {
    "kind": "operator_recorded",
    "room_id": null,
    "message_id": null,
    "note": "Sprint 2 and Sprint 3 client checkpoint"
  }
}
```

Practice and submission accept the same body shape. Replace `commit_sha` with the actual HEAD from slot A's assigned worktree. Use slot A's token; repeat for B with its own slot, SHA, UUID and token:

```json
{
  "request_id": "22222222-2222-4222-8222-222222222222",
  "slot": "a",
  "commit_sha": "<actual lowercase 40-character HEAD SHA>",
  "source": {
    "kind": "unverified_context",
    "room_id": null,
    "message_id": null,
    "note": "Client integration submission"
  }
}
```

Use `source.kind: "fixture"` for scripted fixture actions. Use `switch_context` only with actual Switch context; keep unknown IDs null. Assign separate request IDs to practice and official submission. Callers submit a commit SHA; the engine derives paths and computes results and digests.

For phase actions, send `request_id`, `action`, a nonempty `reason`, and the same human `source` shape as the create example. Reveal requires both initial candidates and both verification jobs to be terminal. Failed checks and runner errors may enter review; a runner error never establishes success. Continue into review for the full checkpoint, or cancel to end a short connection-only run. Cancellation is available from any nonterminal phase.

Journal the exact endpoint, request ID and canonical non-secret body before sending each POST. After a transport timeout, the outcome is unknown: retry the same ID and body. The same actor, endpoint and ID must return the original result; changing that body's content returns `409 IDEMPOTENCY_CONFLICT`. After a conclusive operation error, correct the cause and use a new operation ID. Keep the journal across browser reloads and request the token again after reload.

Treat `Job.status: completed` as execution completion, then inspect `result.status` for verification success or failure. The baseline contains 7 public checks and 11 official checks. Accepted challenge regressions add to practice and official verification suites; show the returned check counts. Practice establishes no eligibility. Initial official passes remain pending until review resolution and fresh full verification establish eligibility.

## Connect the Sprint 3 match workflow

All additional POSTs require a fresh `request_id` and the appropriate `source`, with the same journalling and retry rules above. All paths below are relative to `/api/v1`.

| Operation | Request | Additional body fields and role |
| --- | --- | --- |
| Submit a challenge | `POST /matches/{id}/challenges` | Slot: `target_candidate_id`, `requirement_ids`, `title`, `scenario`; returns `202` with `challenge_id` and `job_id` |
| Complete each review | `POST /matches/{id}/reviews/{slot}/complete` | Matching slot: `target_candidate_id` for the exact frozen opponent |
| Adjudicate a challenge | `POST /matches/{id}/challenges/{challenge_id}/decision` | Operator: `disposition` (`accepted` or `rejected`) and `reason` |
| Repair or finalize | `POST /matches/{id}/actions` | Operator: `action` (`start_repair` or `finalize`) and `reason` |
| Select a candidate or neither | `POST /matches/{id}/selection` | Operator: `selection` (`a`, `b` or `neither`), `candidate_id`, `expected_evidence_key`, `reason` |

1. **Reveal and inspect.** The match enters `reviewing`. Fetch each slot's Assignment again: `review_path` points to its read-only frozen opponent copy and `target_candidate_id` identifies that candidate. Submit challenges before marking that slot's review complete.
2. **Reproduce and adjudicate.** Challenge scenarios are JSON data: `capacity` is 1–20 and `steps` has 1–30 entries, each with `op`, positional `args` and an exact `expected` value. Cite the frozen requirement IDs. Poll the challenge job, then inspect `result.status` and the Match's challenge disposition. The runner first checks the private reference, then requires the exact target to fail twice. A reproduced challenge awaits a human decision about whether it matches the cited requirement. Only the operator can accept it.
3. **Resolve review.** Invalid and not-reproduced challenges are auto-rejected. Inconclusive reproduction remains pending; retry while that slot's review is open, reject with an operator reason, or cancel. Both slots must explicitly complete review against their exact opponent candidate. All challenge jobs and dispositions must be resolved before advancing.
4. **Refresh the shared suite.** Accepting a challenge adds its deduplicated regression to the common suite, changes `suite_digest` and makes both candidates' earlier verification stale. Refresh Match data and discard cached selection evidence.
5. **Repair or finalize.** `start_repair` moves to `repairing` and consumes one of the configured repair rounds, up to two. Each slot submits once through the existing submissions endpoint; unchanged code may be resubmitted if already adequate. Verification waits for both submissions, then the phase becomes `verifying`. Alternatively, `finalize` from resolved review runs the current candidates against the full suite without consuming a repair round.
6. **Handle decision and recovery.** Once both full verification jobs are terminal, the match enters `decision`. Infrastructure failures produce unknown eligibility. From decision, `finalize` reruns the unchanged frozen candidates against the same suite after recovery; `start_repair` is available if rounds remain. Review does not reopen in this MVP.
7. **Select and export.** Candidate selection requires the current candidate to be `eligible`. Send its latest `candidate_id` and copy the complete `verification.evidence_key` into `expected_evidence_key`: `candidate_digest`, `spec_digest`, `suite_digest` and `runner_digest`. A stale or mismatched selection is refused with `409`; refresh and require a new human decision. For `selection: "neither"`, send `candidate_id: null` and `expected_evidence_key: null`, with a reason. Successful selection moves the match to `complete`.

For example, a repeated-cancellation challenge can cite `BOOK-04` with this `scenario` value. Its outcome depends on the exact frozen target:

```json
{
  "capacity": 3,
  "steps": [
    {"op": "book", "args": ["family", 2], "expected": true},
    {"op": "cancel", "args": ["family"], "expected": true},
    {"op": "cancel", "args": ["family"], "expected": false},
    {"op": "available", "args": [], "expected": 3},
    {"op": "reservations", "args": [], "expected": {}}
  ]
}
```

The dashboard downloads exports with `GET /artifacts/{artifact_id}`. Outcome supplies `evidence_artifact_id` and `patch_artifact_id`; the `match.selected` event's `data.artifacts` maps filenames to IDs, including `summary.md`. Render/download the returned content according to its content type. There is no separate POST export endpoint.

The operator CLI can also download the completed outcome. In the configured engine terminal, replace `MATCH_ID` with the completed match ID:

```sh
.venv/bin/python -m arena_engine operator export --match MATCH_ID
```

It writes `evidence.json`, `summary.md` and, for a selected eligible candidate, `candidate.patch` under `<state_dir>/exports/<match-id>/`. Neither produces evidence and summary with no patch. Common evidence excludes private practice jobs/events. Verify an exported patch only on a fresh disposable task base, using the recorded accepted suite; keep contestant code execution inside the trusted Docker runner.

## Sprint 2 connection checklist

- [ ] Record the pinned engine SHA and confirm the canonical contract hash on both sides.
- [ ] `doctor` succeeds and the running health endpoint reports an available runner.
- [ ] B's real browser client reaches the engine through its proxy and sends the correct bearer credentials.
- [ ] B's client creates a match and records its `match_id`.
- [ ] Fetch both assignments and show the correct task, slot and assigned workspace.
- [ ] Commit an allowed candidate in each assigned task worktree; submit both through B's real client/bridge using the matching slot credentials.
- [ ] Poll both official jobs and display their verification results and authorized logs. Show practice separately if exercised.
- [ ] Before reveal, check slot-scoped match, events, jobs and artifacts: opponent candidate content, private paths and artifact IDs remain hidden. Confirm cross-slot assignment and submission attempts are denied.
- [ ] Retry a saved successful POST with the same ID/body and confirm no duplicate match, candidate or job. Repeat after a simulated lost response. Confirm changing the body under the same ID returns `409`.
- [ ] Confirm a premature reveal is rejected; reveal through the operator client once both initial jobs are terminal. Confirm the opponent review copy is then available through Assignment.
- [ ] Show authentication, phase and runner errors clearly using the contract's `{ "error": { "code", "message", "details" } }` envelope. Keep a polling timeout unresolved rather than reporting success or failure.
- [ ] Continue into the full-match checklist below, or cancel a connection-only run and confirm its final phase is `cancelled`. Use a fresh state directory for later runs after worktrees have changed.

## Sprint 3 client checklist

- [ ] Fetch and display the exact opponent review snapshot after reveal, and send challenges against its candidate ID using the submitting slot's token.
- [ ] Display challenge reproduction separately from operator acceptance. Exercise reproduced, invalid/not-reproduced and inconclusive/error results; only a human operator accepts a semantically valid reproduced claim.
- [ ] Accept a reproduced challenge and confirm both candidates' earlier results become stale and the shared suite changes. Complete both reviews; confirm pending decisions block repair/finalization.
- [ ] Start repair, submit both candidates, poll fresh full verification and show current eligibility and evidence. Check the configured repair cap and that one repair submission alone does not start the paired verification.
- [ ] Exercise `finalize` without repair from resolved review and recovery reruns from decision. Runner errors must remain visible and must not establish eligibility.
- [ ] Refuse stale or mismatched selection evidence. Select an eligible current candidate using the exact latest evidence key and download its evidence, summary and patch.
- [ ] In a separate fresh match, reach decision and select `neither`; confirm evidence and summary are available with no patch.
- [ ] Exercise cancellation of a nonterminal match and retain a clear cancelled/error state for interrupted execution.
- [ ] Return the evidence below. Fixture implementations may be used for these client checks when clearly labelled; the genuine native-agent demonstration remains the Sprint 4 gate.

## Evidence to send back to Role A

Send B's branch and commit SHA, the engine SHA, the canonical contract hash confirmation, and a short recording or test report covering both checklists. Include match IDs, candidate/revision IDs, challenge IDs, job IDs, relevant request IDs for retries, and exported outcome/evidence. Identify fixture and native runs explicitly. Keep tokens and held-out/reference content out of the evidence. Store local runtime records under the gitignored `var/` directory.

The pinned Sprint 3 baseline records **99 passing tests with Docker enabled**, successful selected-candidate and neither HTTP/operator-CLI/Docker fixture flows, and a selected patch applied to a fresh task base and passing all 12 checks in that recorded suite. See `docs/integration.md` for the evidence. B's actual client checks and the combined native workflow remain separate delivery gates.

To reproduce the engine-only fixture flows, use a separate terminal in the pinned checkout with the same environment exports. These commands create independent `var/smoke-*` states; keep new snapshots under `var/`:

```sh
.venv/bin/python scripts/smoke_engine.py --full-match --snapshot var/sprint3-client-smoke.json
.venv/bin/python scripts/smoke_engine.py --neither
```

When both owners are ready, Sprint 4 combines the feature branches on the integration branch and verifies the genuine human plus two-native-agent match. The user initiates that integration phase.
