# Coding Arena ownership and workflow

Read `/home/varun/.codex/RTK.md` when available; prefix shell commands with `rtk`.

- Role A owns `engine/`, `fixtures/`, `contracts/`, `scripts/`, `docs/engine.md`, `docs/setup.md`, `docs/integration.md`, `README.md`, `AGENTS.md`, `.gitignore`, `.github/`.
- Role B owns `web/`, `switch_bridge/`, `switch/`, `docs/switch.md`, `docs/experience.md`, `docs/demo.md`. Do not edit the other role's paths.
- Active frozen interface: `contracts/arena-v1.1.json`; preserve historical `contracts/arena-v1.json` unchanged. No unilateral interface changes. Both consumers use `/api/v1`; never import engine internals into the client.
- Development branch for A: `feat/arena-engine`. Stage explicit owned paths; never force-push or merge to main during role implementation.
- Follow the sprint gates in `docs/integration.md`. Sprint completion requires evidence; fixture tests are not a live Switch match.
- Never execute contestant code in the product process or checkout. Only the trusted runner may load candidate modules inside restricted Docker containers.
- Runtime state, tokens, snapshots and logs belong under gitignored `var/`. Never commit secrets or expose held-out/reference content through contestant assignments.
- Search before reading; read relevant ranges, keep output concise and run focused tests.
- For substantial independent tasks, delegate narrow work with explicit file ownership and acceptance criteria. Keep the main agent's selected configuration; use an available lower-cost model with low/medium effort for suitable bounded subtasks. Main agent reviews changes and test evidence.
