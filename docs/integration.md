# Delivery sprints

The two development roles build one product. Runtime contestants are separate native Switch agents. Sprint gates are shared; A cannot confirm B's client or Switch work independently.

| Sprint | A: engine owner | B: experience owner | Exit evidence |
| --- | --- | --- | --- |
| 1 — Foundation | Publish frozen contract, task pack, engine skeleton and setup commands | Client skeleton and harmless native Switch smoke | Both confirm canonical contract hash; A foundation tests pass; B reports smoke evidence |
| 2 — First working flow | Init, scoped auth, create/assignment/submission endpoints, immutable snapshots and official Docker jobs | Wire real API client, assignment/submission/results screens and retry journal | B's real client creates a match and submits both candidates against A's engine; projections and idempotency tested |
| 3 — Full match | Reproduction, adjudication, shared suite, repair, recovery, guarded selection and exports | Review/repair/decision UI, bridge commands, errors and fixture scenarios | Automated fixture match passes; invalid claims, stale evidence, runner errors and neither outcomes tested |
| 4 — Integration and demo | Combine ready branches, run shared checks, verify exported patch on fresh task base | Complete native Switch setup, demo and experience docs | Genuine human + two-agent match recorded; patch applies and passes recorded suite; limitations documented |

Current sprint: **1 — Foundation**. A's foundation is implemented and verified. B's work and shared hash confirmation remain pending; the shared sprint gate is not yet complete.

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
