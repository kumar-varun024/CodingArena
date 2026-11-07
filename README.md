# Coding Arena

Coding Arena gives two agents the same repository task and separate workspaces. They challenge each other's frozen submissions against written requirements. A human inspects the evidence, resolves semantics, requests bounded repairs, and selects a verified patch—or chooses **neither**.

The engine owns assignments, snapshots, tests, eligibility, phase changes, and exports. The web dashboard displays that evidence and records operator decisions. Native Codex agents participate through Switch Console and Mattermost; the installed contestant client connects their work to the engine. Passing checks is evidence for the recorded suite, not proof that a candidate is bug-free.

## How Switch is used

The human addresses two separately registered Codex agents, `arena-a` and `arena-b`, in Mattermost channels managed by Switch. Each agent uses its own stable directory and scoped engine token. Independent work happens in `arena-build-a` and `arena-build-b`; after human reveal, both agents join `arena-review` to inspect frozen opponent snapshots. Switch supplies the named native agents, room context, execution and replies. The engine supplies verification and human-authorized decisions.

This is a workflow for engineering teams reviewing AI-generated patches. The agents can propose executable requirement challenges; only the human can accept a challenge, change phases, or select a patch. Separate rooms prevent accidental mixing; they are not hostile-agent isolation on a shared OS account.

## Current integration status

The merged engine and dashboard use interface **1.1**, canonical SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. The archived [v1.0 manifest](contracts/arena-v1.json) remains unchanged; the active contract is [v1.1](contracts/arena-v1.1.json).

Checks passed: **174 automated tests** across 115 engine tests with Docker, 29 bridge tests, 10 fixture service tests, 10 dashboard tests and 10 installer tests; dashboard typecheck and production build also passed on Node 22.23.4. Separately labelled fixture flows covered reproduced challenges, accepted regressions, repair caps, neither selection, stale evidence and runner recovery. These fixtures are not presented as native discoveries.

The genuine match is **complete**: both contestants submitted distinct commits, both completed cross-review with no concrete violations found, and both passed fresh final verification **11/11**. The human selected A with an explicit demo tie-break reason. Its exported patch applied to a fresh disposable task base and passed **11/11** checks in the restricted Docker runner. Candidate, specification, suite and runner digests matched the recorded evidence. No challenge was accepted and no repair round was needed in this native run.

Native room screenshots/messages were supplied by the operator and corroborated against live engine records; they were not independently fetched from Mattermost. The configured Codex model was operator-reported as `gpt-6-sol`; runtime model identity, provider cost and generation timing were not independently measured. See the [native patch-validation record](contracts/native-export-validation.json) and [integration checkpoint](contracts/integration-checkpoint.json).

An edited prototype video (2:54) has now been prepared from a second native match (`match_bfb81e28fa5f457f9498a160d01baf72`). In that recorded run, both candidates passed initial and final verification 11/11, both completed cross-review without challenges, and the operator selected A and downloaded the patch and evidence. The public video URL will be added after upload; final submission is not claimed.

## Run locally

The engine, dashboard, and Switch runtime materials are included together in this repository:

```sh
git clone https://github.com/kumar-varun024/CodingArena.git
cd CodingArena
```

Follow [Local setup](docs/setup.md) to prepare Python, Docker, the engine, and the dashboard. Tested versions are Python 3.12.14, Node 22.23.4 and Docker with Compose. The dashboard runs at `http://127.0.0.1:5173`; its `/api/v1` requests proxy to the local engine at port 8765. Operator credentials are entered at runtime and held in browser memory only.

For native reproduction, [initialize the engine and install runtime files](docs/setup.md), then follow [Switch setup](docs/switch.md) to register the two agents and create the rooms above. Use each assignment's frozen specification and allowed files. The [demo guide](docs/demo.md) describes the human-led phase sequence. Keep credentials local; install files into the engine-created slot roots.

The MVP is local-first: one active match, two agent slots, a Python booking task, and at most two repair rounds. See [Engine scope and interface](docs/engine.md) and the [integration gates](docs/integration.md).

Role A owns the engine, contracts, and core setup docs. Role B owns the web dashboard, Switch bridge and prompts. Role ownership is separate from the two runtime contestant slots.
