# Contract 1.1 fixture replay service

This stdlib Python service supplies **synthetic replay data** for the dashboard and
contestant CLI. It does not inspect Git checkouts, execute candidate code, run
tests, register Switch agents, or produce a usable selected patch. It must never
be presented as a live engine result.

Run from the repository root:

```sh
python3 web/mock/server.py --port 8766
python3 -m unittest discover -s web/mock -p 'test_*.py'
```

Use the deliberately public mock-only tokens `fixture-operator`, `fixture-a`, and
`fixture-b`. They have no authority on the live engine. The UI asks for a token at
runtime; do not put live credentials into frontend environment variables.

Seeded match IDs:

| ID | Recorded state |
| --- | --- |
| `fixture-building` | No initial submissions; private slot views |
| `fixture-reviewing` | Frozen snapshots, no findings yet |
| `fixture-pending` | Reproduced cancellation finding awaiting operator decision |
| `fixture-repair` | Accepted finding, first repair round |
| `fixture-decision` | Both current fixture candidates eligible |
| `fixture-neither` | Neither candidate eligible |
| `fixture-stale` | Selection receives `409 STALE_SNAPSHOT` |
| `fixture-error` | Recorded runner errors and unknown eligibility |

These independent seeded states coexist for UI development. The single-active
match guard applies to new matches created through `POST /matches`, separately
from the seeded examples.

Every HTTP response, including errors and artifacts, has `X-Arena-Mode: fixture`.
Only health and Match JSON bodies have a top-level `mode` field. The fixture server
allows browser access from localhost/127.0.0.1 port 5173 and exposes the mode and
download-filename headers. Vite can instead proxy `/api` to port 8766.

Mutation results are idempotent by actor, endpoint and UUID; changed bodies return
`409 IDEMPOTENCY_CONFLICT`. Without `--state-file`, restarting resets all fixture
states. To exercise restart recovery with non-secret fixture data, use:

```sh
python3 web/mock/server.py --state-file web/mock/.state/state.json
```

Practice and verification jobs complete immediately with explicitly synthetic
counts. Practice never changes a Candidate's official verification. Challenges
replay only the exact scenario in `task_spec.json`'s `challenge_example`: initial
slot A has the recorded defect and slot B passes. Other well-formed scenarios
become inconclusive with an explanation that no result has been recorded.
Invalid schemas return 422. Repair revisions are recorded as healthy fixture
snapshots. No outcome is inferred from arbitrary contestant code.

`task_spec.json` is a fixture copy of the booking task from the handoff. It is not
the canonical manifest and does not replace A's contracts, tests, reference
implementation or restricted runner. Assignment paths begin with `/fixture/` and
are illustrative; this service does not provision actual workspaces.
