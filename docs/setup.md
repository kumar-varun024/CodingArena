# Local setup

These steps run the interface 1.1 engine and dashboard on one Linux host. Tested versions are Python 3.12.14, Node 22.23.4, Docker Engine 29.9.3, and Docker Compose 5.7.0. Docker must be usable by the same account that runs the engine. The engine uses the pinned runner image below.

Use a dedicated runtime directory under ignored `var/`. Keep it for match history and artifacts; do not reset or reinitialize the product repository to clear a match.

```sh
export ARENA_STATE_DIR="$PWD/var/runtime"
python3 -m venv .venv
.venv/bin/python -m pip install -r engine/requirements.txt
docker pull python@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
PYTHONPATH=engine .venv/bin/python -m arena_engine contract
PYTHONPATH=engine .venv/bin/python -m arena_engine init
PYTHONPATH=engine .venv/bin/python -m arena_engine doctor
```

`contract` checks the active manifest digest. `init` provisions the marked state, task base, slot worktrees, and operator/slot token files. The operator token is at `$ARENA_STATE_DIR/auth/operator.token`; read it locally to enter it in the dashboard. `init` prints token paths, not values. Initialization reuses an existing marked state and refuses an unrelated nonempty directory or initialization while a match is active. It does not reset existing workspaces. Keep token values private; the dashboard holds its operator token in memory only.

## Start the engine and dashboard

In a terminal with `ARENA_STATE_DIR` set, start the engine:

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine serve
```

In a second terminal from the repository root, install and start the web app with Node 22.23.4:

```sh
npm --prefix web ci
npm --prefix web run dev
```

Open `http://127.0.0.1:5173`. The Vite proxy sends `/api/v1` to `http://127.0.0.1:8765`. Enter the operator token from the initialized state when prompted. Do not put credentials into `.env`, a `VITE_` variable, prompts, or browser storage. For a non-default engine host, set only the non-secret `VITE_ARENA_API_BASE` URL in `web/.env.local` and restart Vite; the engine must permit the UI origin and return `X-Arena-Mode`.

The default proxy needs no CORS configuration. For direct cross-origin requests, set `ARENA_UI_ORIGIN` to the exact UI origin (for example `http://127.0.0.1:5173`) before starting the engine; it exposes the response-mode and download headers for that origin. The dashboard connects to the engine and creates or opens a match. For operator CLI workflows and phase rules, see [Engine scope](engine.md). For a synthetic UI-only experience, see [the fixture guide](../web/mock/README.md); fixtures do not create native agents or usable patches.

## Prepare native Switch slots

Only install runtime files into the existing slot roots created by engine initialization. First review the dry run, then install:

```sh
python3 switch/install_runtime.py --state-dir "$ARENA_STATE_DIR" --api-url http://127.0.0.1:8765 --check
python3 switch/install_runtime.py --state-dir "$ARENA_STATE_DIR" --api-url http://127.0.0.1:8765
```

The installer checks both slot roots before writing. It does not provision or reset engine state, read token contents, start providers, or register agents. Set each native agent's Directory to its printed slot root, and follow [Switch setup](switch.md) and the [demo guide](demo.md). The integration host's UI must complete the human-led Console, provider, agent, and room setup; none of those native steps are proven by local fixtures or CLI checks.

## Verification evidence

The following checks have passed on the merged integration tree:

| Check | Evidence |
| --- | --- |
| Engine | 108 tests with Docker enabled; selected patch applied to a fresh task base and passed 12 checks; separate neither result exported no patch |
| Switch bridge | 29 tests |
| HTTP fixture service | 10 tests |
| Dashboard | 10 tests and production build on Node 22.23.4 |
| Native runtime installer | 10 tests |
| Live dashboard client | Five read-only checks against the actual `ArenaApi`: health/version/mode, match labels, events, unknown-job 404, invalid-token 401 |
| Browser fixture | Connected, selected neither, inspected labelled synthetic evidence; no console errors |
| Runner recovery fixture | Injected Docker-start failures yielded unknown eligibility; finalize kept the same snapshots and repair round, then real Docker reruns passed |

Run focused local suites with:

```sh
ARENA_DOCKER_TESTS=1 .venv/bin/python -m pytest -q engine/tests
python3 -m unittest discover -s switch_bridge/tests -q
python3 -m unittest discover -s web/mock -p 'test_*.py' -q
npm --prefix web test
npm --prefix web run build
python3 -m unittest discover -s switch/tests -q
```

Run the combined client/engine fixture flows without native agents:

```sh
.venv/bin/python scripts/smoke_engine.py --full-match --bridge-cli
.venv/bin/python scripts/smoke_engine.py --neither --bridge-cli
.venv/bin/python scripts/smoke_engine.py --runner-recovery --bridge-cli
```

Each uses new disposable state. Recovery injects a labelled Docker-start transport failure only into its own process environment, then verifies unchanged candidates against real Docker after the fault is removed. It does not stop the shared Docker daemon or manufacture passing job results.

To repeat the read-only client check against a prepared match, use the operator state directory and match ID. The script reads the operator token directly into memory and does not print it or perform mutations:

```sh
node --experimental-transform-types \
  scripts/check_dashboard_client.mjs \
  --api-url http://127.0.0.1:8765/api/v1 \
  --state-dir "$ARENA_STATE_DIR" --match MATCH_ID
```

Use the Node 22.23.4 baseline for this helper; its TypeScript-transform flag is experimental and confined to validation. The check does not interact with a browser or native agents. Browser health at interface 1.1 and a labelled fixture UI flow have been observed; later user-supplied screenshots show native contestant submissions and authenticated dashboard reveal, corroborated by live engine records. See the [Sprint gates](integration.md); do not report the native gate as complete until that evidence exists.
