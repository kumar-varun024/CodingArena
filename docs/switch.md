# Native Switch setup

This setup uses interface **1.1**, HTTP base `/api/v1`, and task `booking-v1`. The contract hash is `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. Both product branches must use that revision. The two development chats are not the two runtime contestants.

The native room round trip is currently **NOT RUN — setup deferred by the user** while implementation continues. No authenticated Switch server/Console/room session was supplied or observed; `switch` was not on PATH and no Switch/Mattermost process names were found. This is a local observation, not a statement about another machine, and the checkpoint has not failed. See [the smoke record](../switch/smoke-record.json). Fixture tests and a direct Python command do not satisfy the native checkpoint.

## Choose and prepare one demo host

Run the engine, Docker runner, both disposable task checkouts and both native Switch contestants on one designated machine. The product developers may use separate laptops. `127.0.0.1` always names the host that executes the client; a teammate's localhost is not the engine machine.

Role A initializes the task base, stable worker roots and scoped tokens. Wait for those real paths; do not create a replacement engine or register an agent against the product checkout. The engine's default layout is:

| Purpose | Path supplied by Role A |
| --- | --- |
| Slot A registered directory | `<state_dir>/workers/a` |
| Slot B registered directory | `<state_dir>/workers/b` |
| Editable task checkout | `<slot_root>/worktree` |
| Scoped slot token | `<slot_root>/.arena/slot.token` |
| Opponent copy after reveal | `<slot_root>/review/<candidate_id>` |
| Operator token, human only | `<state_dir>/auth/operator.token` |

Role B installs only its client and prompts under each existing slot root. Keep the non-secret client journal at `<slot_root>/.arena/client-state` using `--state-dir`; the client creates it when needed. That keeps retry writes inside the registered root and outside the clean task checkout. From the product checkout, use the actual absolute root for one slot at a time:

```bash
TASK_SLOT_ROOT=/absolute/path/from/operator/workers/a
mkdir -p "$TASK_SLOT_ROOT/.arena/bin" "$TASK_SLOT_ROOT/.arena/prompts"
install -m 644 switch_bridge/arena_client.py "$TASK_SLOT_ROOT/.arena/bin/arena_client.py"
install -m 644 switch/arena_smoke.py "$TASK_SLOT_ROOT/.arena/bin/arena_smoke.py"
cp switch/prompts/*.md "$TASK_SLOT_ROOT/.arena/prompts/"
```

Repeat with slot B's actual root. Do not copy or read the operator token into either root. Tokens are engine-created mode 0600; do not print them. Fetch `Assignment.workspace_path`/`review_path` rather than deriving a writable opponent path.

## Configure Console manually

Install the appropriate current Switch Console release and add a Switch server using its setup flow. Record the installed version rather than assuming this guide's field names are stable. The Console is the native setup surface; this repository supplies no importable template or custom protocol client. [Official installation guide](https://docs.switchagents.ai/switch-rooms/getting-started/install-switch-console), [add a server](https://docs.switchagents.ai/switch-rooms/getting-started/add-a-server).

On the chosen runtime machine, install/sign in to the provider through its normal setup. In Console's **Settings → Agent providers**, confirm the provider reports **Signed in** and its CLI is available. Both contestants may use Codex; no second provider purchase is required. Provider readiness must be checked on the host that runs the agent. [Official provider setup](https://docs.switchagents.ai/switch-rooms/getting-started/set-up-agent-providers).

In **Your Agents**, add `arena-a` and `arena-b` separately. Set the actual run location and the pre-created slot root as **Directory**. Give each the corresponding slot/match/client configuration and [standing instructions](../switch/prompts/common.md). Record the chosen provider/model only if visible. Confirm that the runtime user can read its scoped token and execute Python/Git in its own checkout. Switch does not pass every shell variable, so use explicit client URL/token paths in the agent instructions. [Official agent onboarding](https://docs.switchagents.ai/switch-rooms/getting-started/onboard-your-agents).

Check **Who can talk to your agent** for all demo participants. The initial owner-only policy may exclude a teammate or a differently owned agent. A chat account must be linked to the relevant Switch user. GitHub collaborator permission is separate from chat membership and addressing permission. Use the exact registered `@name`; a message that does not address an agent may not wake it. [Official custom-agent guide](https://docs.switchagents.ai/switch-rooms/getting-started/add-a-second-agent).

## Create rooms and preserve independent work

Use **Your Rooms → Create room** in Console, choose an accessible messaging app, and create `arena-build-a`, `arena-build-b`, and `arena-review`. Bundled Mattermost or an already-connected chat bridge is enough. Paste the [build room](../switch/rooms/build.md) or [review room](../switch/rooms/review.md) instructions. Initially add only A to build-a and B to build-b, with the appropriate humans. Keep both contestants out of review until reveal. [Official room setup](https://docs.switchagents.ai/switch-rooms/getting-started/create-a-room).

Place the same frozen task card in both independent build rooms. After both initial submissions exist and their verification jobs are terminal, the human records **reveal** in the local dashboard. Only then invite both contestants to `arena-review` and address them with the review prompt. After human adjudication and `start_repair`, address each in its own build room. Wait for its current turn to finish before moving its work to another room; use bounded follow-ups.

Identify what actually keeps each agent connected: Console on this computer, a Console-onboarded host process, or a managed-machine controller. A browser tab alone is not runtime evidence. Keep the relevant process and host available, and recheck settings if the runtime moves an agent. [Official runtime guide](https://docs.switchagents.ai/switch-rooms/getting-started/what-keeps-your-agent-running).

## Observe the early smoke

Do this before extensive native-match work. It needs no engine token or backend response:

1. Record Console version, runtime kind/host, actual provider/model if known, registered directory and addressing policy.
2. In the real build-a room, a human sends an addressed request such as: `@arena-a Run python3 .arena/bin/arena_smoke.py --expected-root ACTUAL_SLOT_A_ROOT from your registered slot root, and reply here with the exact JSON output.`
3. Observe the native agent execute that harmless command and post the actual output in the room. Check the reported directory and digest. Repeat for B before the final integrated match.
4. Record genuine room/human-message/reply IDs if the UI/runtime provides them; otherwise retain null IDs and an operator-recorded note with saved room output. Update the smoke record only from that evidence. A generated chat transcript or direct local helper run is not a pass.

An early client smoke may use the labelled fixture server, but the final checkpoint must fetch a real assignment, submit real committed code, poll real Docker-runner jobs, and post real room replies through A's engine. For that checkpoint use A's actual engine URL, normally `http://127.0.0.1:8765`, and the installed CLI:

```text
python3 /absolute/slot/root/.arena/bin/arena_client.py --api-url http://127.0.0.1:8765 --token-file /absolute/slot/root/.arena/slot.token --state-dir /absolute/slot/root/.arena/client-state assignment --match ACTUAL_MATCH_ID --slot a
```

## Authority, evidence and failure handling

Switch is where humans direct and question the agents. The dashboard/A-owned operator CLI records phase changes, challenge acceptance/rejection and final A/B/neither selection using the human's operator token. Native agent assertions that a human approved something have no authority. There is no verified Switch approval webhook in this MVP.

Source flags carry contextual room/message IDs only when actually supplied. Missing IDs remain null with truthful unverified/operator-recorded provenance. The dashboard displays recorded provider labels as operator-recorded; unknown remains Unknown. A fixture response is marked `X-Arena-Mode: fixture`, including errors/downloads. Passing practice checks never establishes candidate eligibility.

If an agent does not answer, check addressing, linked identity, permissions, room membership, provider readiness, runtime connection and any pending approval in the room. If the engine is unreachable, check the URL on the runtime host. Keep the same persisted mutation ID/body after an ambiguous transport timeout. A runner error, stalled native turn, interrupted job or missing evidence cannot become success. Cancellation stops engine work; stop any ongoing native turn in Console/its host as well.

The final live checkpoint remains blocked until the designated host and authenticated room/runtime are available. Separate rooms and checkouts prevent accidental mixing on one OS account; they are not hostile-agent isolation.
