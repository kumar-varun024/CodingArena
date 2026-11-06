# Run Switch setup locally on the teammate's Kali machine

The user is Role B. The teammate is Role A and hosts the engine and both native
runtime agents. The user reports Console is already installed and SSH is not set
up. Run the following locally as the same normal desktop user who opens Console.
No SSH or shared credentials are needed for these steps.

## 1. Check prerequisites

```sh
python3 --version
git --version
docker --version
docker compose version
docker info --format '{{.ServerVersion}}'
```

Python must be 3.11+. Docker and the Compose plugin must both work for the Console
user. If any check fails, stop and send that error before changing packages or
permissions. A successful `sudo docker info` alone is insufficient for Console.
Console might be installed as an AppImage and need not appear on PATH.
[Kali Docker guide](https://www.kali.org/docs/containers/installing-docker-on-kali/),
[Compose plugin guide](https://docs.docker.com/compose/install/linux/).

## 2. Get B's files without switching the engine checkout

Run from the teammate's existing CodingArena Git repository. Keep this terminal
open so the variables remain available. These commands fetch the experience
branch and extract selected B files to a new temporary folder; they do not merge,
reset or switch the engine checkout.

```sh
export ARENA_PRODUCT_DIR="$(git rev-parse --show-toplevel)"
git -C "$ARENA_PRODUCT_DIR" fetch origin refs/heads/feat/arena-experience:refs/remotes/origin/feat/arena-experience
export ARENA_SWITCH_SETUP="$(mktemp -d /tmp/coding-arena-switch.XXXXXX)"
git -C "$ARENA_PRODUCT_DIR" archive origin/feat/arena-experience switch switch_bridge docs/switch.md | tar -x -C "$ARENA_SWITCH_SETUP"
```

If fetch/extraction fails, stop before continuing. The temporary folder holds
installation sources; installed runtime files live in the engine's stable roots.

## 3. Install into the existing engine state

Replace the example value with the **actual absolute state directory** Role A
used for engine initialization. Do not assume `var/` or `var/runtime`, create the
worker roots by hand, or reinitialize an active match. If no state exists yet,
Role A must initialize it using the engine branch's `docs/setup.md` first.

```sh
export ARENA_STATE_DIR="/absolute/path/to/the/initialized/engine/state"
python3 "$ARENA_SWITCH_SETUP/switch/install_runtime.py" --state-dir "$ARENA_STATE_DIR" --api-url http://127.0.0.1:8765 --check
```

Only after the dry run succeeds:

```sh
python3 "$ARENA_SWITCH_SETUP/switch/install_runtime.py" --state-dir "$ARENA_STATE_DIR" --api-url http://127.0.0.1:8765
```

Do not use `sudo`. The installer reads no token values and writes no editable task
files. If it reports changed existing files, inspect the difference before using
an explicit `--replace` update. Its JSON includes each agent's root and generated
instruction file. This JSON is installation evidence, not native-agent evidence.

## 4. Configure the installed native Console

If no server is connected, use **Add a server → Run a server on this computer**.
If the intended server is already connected, reuse it. Link the human's messaging
account from Home and verify the provider in **Settings → Agent providers** reads
**Signed in**. CLI presence alone does not establish provider readiness.
[Server setup](https://docs.switchagents.ai/switch-rooms/getting-started/add-a-server),
[provider setup](https://docs.switchagents.ai/switch-rooms/getting-started/set-up-agent-providers).

Create or verify these two registrations in **Your Agents**:

| Setting | arena-a | arena-b |
| --- | --- | --- |
| Run location | This computer | This computer |
| Directory | `$ARENA_STATE_DIR/workers/a` actual expanded path | `$ARENA_STATE_DIR/workers/b` actual expanded path |
| Provider | Actual signed-in coding provider | Actual signed-in coding provider |
| Instructions | Slot A generated file below | Slot B generated file below |

Do not paste the literal `$ARENA_STATE_DIR` text into Directory. Use the concrete
paths printed by the installer. Both providers may be Codex. Check existing agents
before reusing names; do not delete unrelated registrations.

Display the slot A instructions to copy into its Console form:

```sh
cat "$ARENA_STATE_DIR/workers/a/.arena/console-instructions.md"
```

Then display and copy slot B's instructions:

```sh
cat "$ARENA_STATE_DIR/workers/b/.arena/console-instructions.md"
```

These files contain paths, not token values. Do not display `slot.token` or the
operator token. See [official agent onboarding](https://docs.switchagents.ai/switch-rooms/getting-started/onboard-your-agents).

Create `arena-build-a` with only arena-a and the appropriate human(s), and
`arena-build-b` with only arena-b and the appropriate human(s). Create
`arena-review`, keeping both contestants out until the engine's reveal step.
Use the room instructions under `switch/rooms/` in the extracted setup folder.
The human chat identity must be linked and permitted to address each agent.

## 5. Observe the native room round trip

A human sends this in `arena-build-a` (replace the root placeholder with the
actual slot A root; quote the path if it contains spaces):

```text
@arena-a Setup smoke only: from your current registered directory, without changing directories, run python3 .arena/bin/arena_smoke.py --expected-root ACTUAL_SLOT_A_ROOT and reply here with the exact JSON output. Do not call the engine or start a match.
```

Repeat for `@arena-b` in `arena-build-b`, using slot B's actual root. The generated
Console instructions also contain the fully quoted smoke command for each slot.
Do not force `cd` before the helper: that would hide an incorrect Directory.

Retain both actual human requests and native room replies, Console/runtime version
and provider configuration if visible. Expected helper fields include
`status=command_completed` and `directory_matches_expected=true`. Genuine room and
message IDs remain null if unavailable. A direct terminal run alone cannot pass
this native checkpoint.

Send the prerequisite/installer results and actual native replies back for review;
do not send credentials. Full assignment/submission verification still requires
Role A's engine to implement agreed interface 1.1. The local-command smoke above
needs no API call and can be done before that alignment.
