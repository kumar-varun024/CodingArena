# Coding Arena experience

Role B supplies a local evidence dashboard, a slot-scoped stdlib Python client,
and an explicitly synthetic HTTP fixture service. Switch is where people direct
and question their native agents; the engine owns snapshots, tests, eligibility,
phase changes and exported patches. The UI does not score models or choose a winner.

This implementation targets **interface 1.1**, base path `/api/v1`, canonical SHA-256
`c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`.
The normative manifest remains the one embedded in the updated handoff until A
publishes its identical canonical copy. The fixture task copy is not a replacement
for A's contract or runner.

## Start the fixture experience

Use Node **22.22.2 or newer** and Python **3.11 or newer**. Tested here with Node
22.23.4 and Python 3.12.3. Versions are pinned in `web/package-lock.json` and
`web/.node-version`; there is no root JavaScript package.

From the product repository, install once:

```sh
npm --prefix web ci
```

Start these in separate terminals:

```sh
npm --prefix web run mock
```

```sh
npm --prefix web run dev:fixture
```

Open `http://127.0.0.1:5173`. In **Connection & match controls**, enter the public
mock-only token `fixture-operator` and click **Connect / refresh**. The default
match is `fixture-decision`; the fixture selector also offers building, pending
human decision, repair, neither eligible, stale selection and runner error states.
All routes use the same browser API client as live mode, through Vite's proxy to
`127.0.0.1:8766`. The amber **FIXTURE REPLAY** banner stays visible.

Fixture evidence, snapshots, paths, counts and downloads are synthetic. The server
runs no contestant code, registers no Switch agents and produces no usable task
patch. The seeded states coexist only for development. See the
[fixture service guide](../web/mock/README.md) for optional restart persistence.
Restarting a fixture service without a state file resets its seeded state.

## Connect the live engine

After A provides an engine implementing the exact 1.1 contract and runtime tokens:

```sh
npm --prefix web run dev
```

This proxies `/api/v1` to `http://127.0.0.1:8765`. Enter the operator token at
runtime and paste the actual match ID, or create a booking-v1 match. Both provider
labels can be left blank: they are sent as null and displayed as Unknown.
Provided labels remain operator-recorded, not engine-verified identities.

For a different API host, set only the non-secret URL in `web/.env.local`:

```dotenv
VITE_ARENA_API_BASE=http://actual-demo-host:8765/api/v1
```

Restart Vite after changing configuration. The engine must permit the configured
UI origin for direct cross-origin access and expose `X-Arena-Mode`. Never put an
operator/slot token in a `VITE_` variable, source file, prompt or browser storage.
The token input and API instance retain it only in memory; re-enter it after a
reload. The operation journal persists only non-secret bodies, IDs and recovery
metadata. It scopes retries to the same API origin and observed live/fixture mode.

All HTTP successes, errors and artifacts require `X-Arena-Mode: live|fixture`.
Only health and Match bodies also have a top-level mode. Missing/invalid or
contradictory modes are protocol errors; they cannot silently become live results.
The health interface version must be 1.1. A polling/connection failure disables
new decisions until evidence is refreshed.

## Operate the match

- The task card shows frozen requirements; each contender panel shows its exact
  candidate, commit, snapshot, server eligibility and official check counts.
- Challenge cards show strict JSON expected values, the recorded actual summary,
  requirement IDs, reference outcome and repeated target failure. Inspect logs
  before deciding semantics. Enter a reason before accept/reject or phase actions.
- Reveal is available after both initial submissions and terminal verification
  jobs. Review completion belongs to the slot client. Start repair/finalize uses
  resolved reviews and reports; at most two repair rounds are allowed.
- A/B selection sends the current candidate ID and exact evidence key. Pending,
  failed, stale or unknown candidates are disabled. A server 409 refreshes the
  actual match and remains visible as an error. There is no optimistic success.
- Neither is a valid decision. It exports an evidence pack with no selected patch.
  A selected eligible candidate exposes the server's patch/evidence artifacts for
  inspection and download. Code/logs are displayed as text, never executable HTML.
- Job inspection visibly distinguishes public practice from full verification.
  Practice cannot establish eligibility. Activity displays engine events.
- Cancellation is an explicit operator action with a reason. It does not promise
  to stop an ongoing native agent turn; stop that in its actual host/Console.

Each POST is saved before sending. If its response is lost, **Operation recovery
journal** shows the request ID and offers **Retry same request**. Retry the saved
body rather than clicking an action again and creating a new operation. A changed
body with the same ID is refused. Browser storage failure prevents dispatch. The
journal can be downloaded for recovery; do not add credentials to reasons or labels.

## Contestant client

The client has no operator commands. A supplies each slot's actual token and stable
root; agents fetch their current Assignment and use its paths. The prompts keep
challenge files and client retry state outside the clean editable worktree.

```sh
python3 switch_bridge/arena_client.py --api-url http://127.0.0.1:8765 --token-file /actual/slot/root/.arena/slot.token --state-dir /actual/slot/root/.arena/client-state assignment --match MATCH_ID --slot a
python3 switch_bridge/arena_client.py --api-url http://127.0.0.1:8765 --token-file /actual/slot/root/.arena/slot.token --state-dir /actual/slot/root/.arena/client-state check --match MATCH_ID --slot a --commit CLEAN_COMMIT_SHA
python3 switch_bridge/arena_client.py --api-url http://127.0.0.1:8765 --token-file /actual/slot/root/.arena/slot.token job --id RETURNED_JOB_ID --wait --timeout 120
```

The remaining commands are `submit`, `challenge`, `review-done` and `match`; use
`--help` for their required arguments. Global/source flags work before or after
the command. `challenge --file` requires exactly `title`, `requirement_ids`, and
`scenario`; see [the review prompt](../switch/prompts/review.md). Business-invalid
booking input is permitted so BOOK-06 can be challenged; malformed scenarios are
rejected. Multi-instance isolation stays in A's trusted full suite.

Every mutation prints its request ID to stderr and saves its canonical body before
sending. Use `--request-id THE_SAME_UUID` and the identical command/body after an
ambiguous timeout. Default state is `~/.local/state/coding-arena-client`, overridden
by `ARENA_CLIENT_STATE_DIR` or `--state-dir`; native agents use a location inside
their registered slot root. Token contents never enter the journal or output.
`ARENA_API_URL` and `ARENA_TOKEN_FILE` are also supported. Genuine room/message IDs
may be supplied with source flags; they are context, not human authorization.

Stdout is JSON. Stderr reports mode, request IDs and concise diagnostics. Exit 0
means a valid response, including a failed verification or error job; inspect the
returned status. Exit 1 is a transport/API/configuration error. Exit 2 means a job
wait timed out; poll the same job again. Read [Switch setup](switch.md) and
[the demo script](demo.md) before a native run.

## Verification and integration boundary

```sh
python3 -m unittest discover -s switch_bridge/tests -v
python3 -m unittest discover -s web/mock -p 'test_*.py' -v
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
```

The Python and frontend HTTP tests bind temporary loopback ports. No provider
credentials, Docker runner or cloud account are needed for these fixture checks.
They exercise CLI routes, role visibility, jobs, exact retries, API errors,
selection/neither, real stale 409 refresh, mode validation and storage failure.
Native Switch setup is deferred at the user's request; see the honest
[smoke record](../switch/smoke-record.json). These checks are not a completed live
hackathon workflow.

The inspected engine snapshot on `feat/arena-engine` is
`9a1cf647570d0c50aeb0ed8a68af1bdae848b80b`: its manifest is still 1.0, hash
`3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80`, with no
response-mode header convention or returned provider labels. A must adopt the
agreed 1.1 revision before the shared client can complete the real-API checkpoint.
Do not relax client validation or edit A's files to hide this mismatch. Role A owns
final branch integration, actual Docker/agent runs and applying the exported patch
to a fresh task base for full-suite verification.

The early API checkpoint was also executed against an isolated export of that
immutable engine commit, served on a temporary loopback port and then stopped:

| Probe | Observed result | Required by the agreed interface |
| --- | --- | --- |
| `GET /api/v1/health` | HTTP 200; `api_version=1.0`, `mode=live`, `runner_available=false`; no mode header | `api_version=1.1`, `X-Arena-Mode: live` |
| `GET /api/v1/matches/probe-uncreated/assignments/a` | HTTP 404 `NOT_FOUND`; no mode header | Implemented assignment route with the required mode header |
| Actual bridge assignment command | Exit 1; no JSON result; missing-header protocol error | A valid role-scoped assignment from a compatible engine |

The engine snapshot documents health-only Sprint 1 functionality. The probe used
a synthetic temporary token because genuine match/bootstrap/token APIs were not
available. It did not establish authentication behavior, run contestant code or
execute Docker jobs. The client intentionally refuses this incompatible response.
No engine implementation or contract files were changed on the experience branch.

## Sprint gates

| Sprint | Delivered | Gate |
| --- | --- | --- |
| 1 — client and fixtures | All contestant commands; durable retries; scoped mock HTTP service | 29 CLI tests and 10 fixture tests passed |
| 2 — dashboard | Task, snapshots, challenges, decisions, jobs, timeline, downloads and journal | 10 HTTP/client/UI tests and production build passed; browser stale-selection recovery observed |
| 3 — Switch preparation | Three-room instructions; build/review/repair prompts; manual setup and truthful demo | Documented commands validated against the actual CLI; native smoke intentionally deferred |
| 4 — verification and integration checkpoint | Reviewed recovery boundaries, responsive browser UI and actual A-engine probe | Fixture checks pass; live integration awaits A's 1.1 implementation and user-provided Switch setup |

A successful fixture gate is not a live workflow pass. Both runtime agents, the
restricted Docker runner and fresh exported-patch verification remain final
integration requirements owned jointly with A on the designated demo machine.

A later fetch observed engine Sprint 2 commit
`d376bd5c5a1ecc879ca990e8f19d29fec1c4b44d`. Static inspection confirms its
canonical manifest still declares 1.0 with the original hash and no response-mode
header convention. The HTTP probe above remains specifically evidence for the
earlier immutable Sprint 1 snapshot; it is not a claim that the newer assignment
implementation is absent. Both owners still need to align on 1.1 before live QA.
