# Coding Arena

Coding Arena gives two agents the same repository task and separate workspaces. They challenge each other's frozen submissions against written requirements. A human inspects the evidence, resolves semantics, requests bounded repairs, and selects a verified patch—or chooses **neither**.

The engine owns assignments, snapshots, tests, eligibility, phase changes, and exports. The web dashboard displays that evidence and records operator decisions. The Switch client gives each native agent its role-scoped assignment and workspace, with opponent review access only when authorized. Passing checks is evidence for the recorded suite, not proof that a candidate is bug-free.

## Current integration status

The merged engine and dashboard use interface **1.1**, canonical SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. The archived [v1.0 manifest](contracts/arena-v1.json) remains unchanged; the active contract is [v1.1](contracts/arena-v1.1.json).

Checks passed: 108 engine tests with Docker, 29 bridge tests, 10 fixture service tests, 10 dashboard tests, 9 native installer tests, and a production build on Node 22.23.4. The actual bridge completed selected, neither, and injected runner-recovery fixture matches against the live engine. A selected patch applied and passed all 12 recorded checks on a fresh disposable task base. The dashboard's API client passed five live read checks, and browser verification completed a labelled fixture neither/evidence flow with no console errors. Authenticated live UI and native-agent verification remain pending.

The native Switch gate is still open. Console 0.40.1's official package was hash-verified and launched; Docker Compose 5.7.0 and a signed-in Codex CLI were observed. No native agents, rooms, or native agent replies have been observed. Fixture checks and HTTP engine checks are not a native Switch match. See the [Switch setup](docs/switch.md) and [demo guide](docs/demo.md) for the remaining host steps.

## Run locally

Follow [Local setup](docs/setup.md) to prepare Python, Docker, the engine, and the dashboard. The dashboard runs at `http://127.0.0.1:5173`; its `/api/v1` requests proxy to the local engine at port 8765. Operator credentials are entered at runtime and held in browser memory only.

The MVP is local-first: one active match, two agent slots, a Python booking task, and at most two repair rounds. See [Engine scope and interface](docs/engine.md) and the [integration gates](docs/integration.md).

Role A owns the engine, contracts, and core setup docs. Role B owns the web dashboard, Switch bridge and prompts. Role ownership is separate from the two runtime contestant slots.
