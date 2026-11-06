# Delivery sprints

The two development roles build one product. Runtime contestants are separate native Switch agents. Sprint gates are shared; A cannot confirm B's client or Switch work independently.

| Sprint | A: engine owner | B: experience owner | Exit evidence |
| --- | --- | --- | --- |
| 1 — Foundation | Publish frozen contract, task pack, engine skeleton and setup commands | Client skeleton and harmless native Switch smoke | Both confirm canonical contract hash; A foundation tests pass; B reports smoke evidence |
| 2 — First working flow | Init, scoped auth, create/assignment/submission endpoints, immutable snapshots and official Docker jobs | Wire real API client, assignment/submission/results screens and retry journal | B's real client creates a match and submits both candidates against A's engine; projections and idempotency tested |
| 3 — Full match | Reproduction, adjudication, shared suite, repair, recovery, guarded selection and exports | Review/repair/decision UI, bridge commands, errors and fixture scenarios | Automated fixture match passes; invalid claims, stale evidence, runner errors and neither outcomes tested |
| 4 — Integration and demo | Combine ready branches, run shared checks, verify exported patch on fresh task base | Complete native Switch setup, demo and experience docs | Genuine human + two-agent match recorded; patch applies and passes recorded suite; limitations documented |

Current checkpoint: **interface 1.1 and combined fixture workflow verified**. A's engine now uses B's exact 1.1 manifest/hash. B's unchanged dashboard and contestant CLI completed a live HTTP/Docker fixture match. The feature branches were not merged for this check; the genuine native Switch demonstration remains a Sprint 4 requirement. Earlier sprint evidence below records the versions tested at the time.

## Interface 1.1 compatibility evidence (2026-11-06)

- Added `contracts/arena-v1.1.json` matching B's embedded normative JSON, canonical SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. The original 1.0 manifest/hash is unchanged. Base path stays `/api/v1`.
- Updated health, response-mode headers on all API paths/errors/artifacts, optional exact-origin CORS exposure, nullable nonblank provider labels in Match/Assignment, and unique challenge requirement IDs. Existing 1.0 runtime/token/retry state is compatible without reset. Trusted multi-instance isolation remains in every official full suite.
- Engine regression suite: **104 passed, 2 opt-in Docker tests skipped**, one upstream Starlette HTTPX deprecation warning. Dedicated 1.1 tests cover old-state/retry compatibility, label validation/persistence and mode headers on errors, artifacts and CORS preflight.
- B snapshot `73e70e0` (`origin/feat/arena-experience`): all **41 exported source files** verified unchanged by Git blob identity. B tests passed: **29 bridge + 10 mock + 10 web**, and the web production build passed.
- `var/compat-v11/tools/bin/python scripts/smoke_experience.py --experience-root var/compat-v11/experience` passed with real Chromium, HTTP, SQLite and restricted Docker. Browser actions created a null-label match, revealed candidates, accepted the reproduced cancellation violation, started repair, selected contender A and inspected/downloaded patch and JSON evidence. B's CLI exercised assignment, practice, submit, identical retry, job polling, challenge, review-done and match projections.
- Both repaired candidates passed 12 official checks. The downloaded selected patch applied to a fresh disposable task base and passed all 12 checks there (baseline/held-out, accepted regression and BOOK-07 isolation). Browser had no application errors; observed API responses carried live mode. Direct browser/API access exercised CORS exposure.
- Local evidence: `var/experience-smoke-da6c3467fe0e4bd586d812c30889f898/{summary.json,dashboard.png,server.log,web.log}`. Reproduction instructions are in [setup](setup.md#verify-the-unchanged-experience-branch). This is deterministic fixture evidence against the live engine, not a native Switch discovery or completed human/two-agent demo. Changes stay in A-owned paths; B's earlier incompatibility notes describe old engine snapshots and are superseded by this checkpoint.

## Sprint 1 scope

- Preserve canonical v1 content and SHA-256 `3e6a106d89e05d323d5fe280117d63e937fde6e134e8dda7ae65fcc914eeec80`.
- Bundle sanitized starter, public scenarios, frozen specification, engine-only reference/held-out cases and explicitly labelled known-bad fixtures.
- Provide a trusted bounded scenario driver, engine health/doctor/serve skeleton and reproducible checks.
- Do not claim match execution, candidate eligibility or live Switch integration before those features exist.

## Sprint 1 evidence (2026-11-06)

- Canonical contract hash verified and published on `feat/arena-engine` in bootstrap commit `df9d8b6`.
- Frozen public task distribution, engine-only reference/held-out cases, known-good and two known-bad fixtures are bundled. Private BOOK-07 instance isolation is checked inside Docker.
- Foundation/driver unit tests and snapshot-copy independence test pass. Docker fixture checker executed 24 fresh containers: 22 expected passes and 2 expected known-bad failures, with no unexpected outcomes.
- `contract` and `doctor` CLI checks pass. Docker and pinned image are available; the production executor is explicitly reported as unimplemented.
- A real HTTP request to the running health service returned the exact v1 shape. [Generated response snapshot](../contracts/sprint1-api-snapshot.json) is available for B; it covers health only.
- No live Switch session was exercised. B's client skeleton, native smoke and matching hash confirmation must be supplied by B. The real create/assignment/submission client checkpoint belongs to Sprint 2.

## Sprint 2 engine evidence (2026-11-06)

- `init` provisions marked state, independent sanitized Git clones, fixed slot roots and scoped 0600 tokens. Clean HEAD/ancestry/allowed-file validation creates source snapshots independent of later edits.
- The v1 create/assignment/practice/submission/match/events/job/artifact endpoints are implemented with bearer role checks and persisted actor/endpoint/request-ID retries. Operator reveal/cancel and a journalled operator CLI are available.
- The serialized Docker executor records source/spec/suite/runner digests, public-only practice (7 checks) and official initial verification (11 checks). Errors, cancellation and interrupted jobs produce no successful eligibility.
- `ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests`: **56 passed**, no skips; one upstream Starlette HTTPX deprecation warning.
- `.venv/bin/python scripts/smoke_engine.py --snapshot contracts/sprint2-api-snapshot.json`: actual HTTP/operator-CLI/Docker flow passed. Known-good fixture passed, repeat-cancel fixture failed, private projections/idempotency/reveal/cancel behaved as expected. [Observed API samples](../contracts/sprint2-api-snapshot.json) are labelled fixture clients against the live engine.
- Startup marks interrupted running jobs error, resumes queued work only after successful state-scoped orphan cleanup, and holds an exclusive server lock. Same-snapshot recovery finalization remains Sprint 3.
- Contract version/hash and dependencies are unchanged. No B-owned files, native Switch runtime or B client were exercised. A's engine is ready for B's Sprint 2 API checkpoint; this is not the complete arena workflow.

## Sprint 3 engine evidence (2026-11-06)

- All v1 challenge, review-complete, adjudication, repair/finalize and selection endpoints are implemented. Operator CLI decisions/selections are journalled; exports download exact evidence/summary/patch bytes without applying code.
- Reproduction checks the pinned reference and exact frozen opponent twice. Infrastructure uncertainty remains inconclusive/pending. Acceptance adds a deduplicated shared regression and marks both old candidate results stale.
- Repairs accept one snapshot per slot per round, including unchanged code, and defer full verification until both arrive. Finalization from decision reruns unchanged candidates without another repair round. Latest exact evidence and eligible status guard selection.
- `ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests`: **99 passed**, no skips; one upstream Starlette HTTPX deprecation warning.
- Real HTTP/operator-CLI/Docker selected fixture smoke passed: reproduced BOOK-04, rejected a boolean/integer expectation mismatch against reference, accepted regression, one repair, 12 full checks per latest candidate, stale selection refusal and export. The exported patch applied to a fresh disposable task base and passed all 12 checks there.
- Real `--neither` smoke kept both candidates broken through two repair rounds, enforced the cap, and exported evidence/summary with no patch. No mandatory winner was introduced.
- [Sprint 3 API samples](../contracts/sprint3-api-snapshot.json) record labelled fixture interactions against the live engine. Shared exports exclude private practice jobs/events; tokens, private reference source and held-out source are not included.
- Canonical contract and dependencies are unchanged. No B-owned files or live Switch agents were used. The engine side is ready for the combined integration checkpoint; the product remains incomplete until both branches and the genuine native-agent workflow are verified in Sprint 4.

## Integration sequence (Sprint 4 only)

1. Collect both pushed feature SHAs, test evidence, draft PRs and matching canonical contract hashes. Freeze optional additions.
2. In a clean checkout/worktree create `feat/arena-integration` from `origin/main`; merge engine then experience feature branches. Resolve conflicts with the relevant owner; coordinate any contract change.
3. Install each component's dependencies and run engine, bridge, frontend and real-API checks. Keep lockfiles with their owners.
4. On one demo machine initialize both stable slot roots, prepare Docker, start engine/UI and verify both native Switch agents' paths, API reachability, connectivity and addressing permissions.
5. Run a labelled fixture match through challenge acceptance, repair, full verification and export. Exercise invalid claims, stale selection, runner error and neither.
6. Run the genuine human + two-native-agent flow and preserve actual message/context IDs when available. Do not promise a discovery or winner.
7. Apply the exported patch to a fresh disposable task base and run the entire accepted suite. Never apply contestant patches to this product repository.
8. Complete README/demo docs and record evidence/video. Push integration branch and open the final PR. Merge only after verified integration and explicit user initiation; individual role draft PRs are not merged separately.

Reserve the final work block for integration and demo; cut optional polish before verification.
