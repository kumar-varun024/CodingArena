# Coding Arena demo

Show the operator's real evidence view and the actual Switch conversation. A fixture replay demonstrates interface behavior only. It does not establish that a model found a bug, that the Docker runner executed code, or that the native Switch loop passed.

## Genuine live run

Prerequisites: A's engine and Docker runner initialized on the designated demo host; both registered native contestants using their separate stable roots; actual provider readiness; human chat access/addressing permission; both product branches integrated against contract 1.1. Follow [Switch setup](switch.md). The development chats that built the product are separate from the two runtime contestants.

1. Open the live dashboard connected to the actual engine (normally `http://127.0.0.1:8765`) and enter the operator token at runtime. Confirm **Live**, actual runner availability and contract version. Record provider labels only from known configuration; Unknown is valid. Create a `booking-v1` match with the chosen advisory build budget and repair cap.
2. Put the identical frozen task card in `arena-build-a` and `arena-build-b`. A human addresses each contestant using the build prompt. Each fetches its assignment, implements only its allowed file, runs public practice, commits its own code, submits and polls the returned official job. Show the two actual frozen candidate IDs, commit/tree digests and measured check counts. Do not expose the rival's work before reveal.
3. When both initial verification jobs are terminal, the human records **Reveal**. Bring both agents into `arena-review` and address each with the review prompt. Show actual frozen review copies and submitted JSON proof files with cited requirement IDs. Poll the real reproduction jobs: a reproduced claim needs reference success and two failures of the exact target.
4. If there is a reproduced claim, discuss its expected behavior in Switch. The human records accept/reject with a requirement-valid reason in the dashboard. Show that accepted claims become common regressions and stale evidence is invalidated for both candidates. Never narrate a rejection, inconclusive run, pending job or fixture event as a successful live discovery.
5. After both reviews are complete and dispositions resolved, the human records **Start repair** (or **Finalize** when no repair is needed). Address each contestant in its own build room after its review turn ends. Each repairs its own implementation or resubmits an unchanged clean commit. Show full fresh verification against baseline, held-out and all accepted regressions.
6. At **Decision**, compare the server's current eligibility and exact evidence keys. The human selects A, B or neither with a reason. An eligible selection exports a patch and evidence pack. In a fresh disposable task base, Role A applies the downloaded patch and runs the full accepted suite. Record what actually happened and what was measured.

If neither contestant finds a bug, say that explicitly, mark both reviews complete and finalize. If both remain ineligible after the cap, select neither and show the blockers. A live bug discovery and a winner are not mandatory. If the runner fails, show unknown/error eligibility and rerun after recovery; do not bypass the guard. No universal model ranking, fabricated cost/time, or bug-free claim belongs in the demo.

Suggested narration: “Two independent snapshots, cross-review through bounded executable evidence, human semantic decisions, and fresh verification before selection. These results cover the recorded checks.”

## Labelled fixture replay

Say **“Fixture replay: deterministic synthetic snapshots and pre-seeded results; no live model discovery or protected-runner execution.”** Keep the dashboard's fixture banner visible. This fallback is available even when the native setup or A's engine is unavailable.

From the product checkout in separate terminals, use Node 22.22.2+ and Python 3.11+:

```bash
npm --prefix web run mock
```

```bash
npm --prefix web ci
npm --prefix web run dev:fixture
```

Open `http://127.0.0.1:5173`. The mock-only operator token is `fixture-operator`; slot tokens are `fixture-a` and `fixture-b`. These are documented mock values, not real credentials. Never use them as live tokens. The actual API client must observe `X-Arena-Mode: fixture` for reads, mutations, errors and downloads.

Use the fixture match IDs to inspect the seeded states:

| Match ID | What to show |
| --- | --- |
| `fixture-building` | Independent candidate/build state |
| `fixture-pending` | Reproduced claim awaiting human disposition |
| `fixture-repair` | Accepted regression and repair state |
| `fixture-decision` | Current eligible candidate and guarded selection |
| `fixture-neither` | Neither candidate eligible; neither outcome remains valid |
| `fixture-stale` | Selection receives 409 and the dashboard refreshes actual state |
| `fixture-error` | Infrastructure failure/unknown eligibility |

Walk through the states or use mock controls, identifying synthetic transitions each time. Demonstrate one accept/reject, a repair state, successful guarded selection/evidence download, stale 409 recovery, and a neither outcome. A text patch/log from this server is a fixture artifact, not a verified contestant deliverable.

The contestant CLI can also read the fixture through the same HTTP interface without real credentials. Store its mock-only token outside the product checkout:

```bash
TASK_FIXTURE_TOKEN=$(mktemp)
chmod 600 "$TASK_FIXTURE_TOKEN"
printf '%s\n' fixture-a > "$TASK_FIXTURE_TOKEN"
python3 switch_bridge/arena_client.py --api-url http://127.0.0.1:8766 --token-file "$TASK_FIXTURE_TOKEN" assignment --match fixture-building --slot a
rm -- "$TASK_FIXTURE_TOKEN"
```

No model or Switch participation is implied by that direct CLI call. Keep the final live checkpoint marked **NOT RUN** until the human → native agent → CLI → real engine/runner → native room reply chain is observed. Retain genuine artifact IDs and room output when it is.
