# Coding Arena ownership and workflow

Read `/home/varun/.codex/RTK.md` when available; prefix shell commands with `rtk`.

- Role A owns `engine/`, `fixtures/`, `contracts/`, `scripts/`, `docs/engine.md`, `docs/setup.md`, `docs/integration.md`, `README.md`, `AGENTS.md`, `.gitignore`, `.github/`.
- Role B owns `web/`, `switch_bridge/`, `switch/`, `docs/switch.md`, `docs/experience.md`, `docs/demo.md`. Do not edit the other role's paths.
- Current interface: `contracts/arena-v1.1.json`, matching the experience branch's supplied 1.1 manifest. Original `contracts/arena-v1.json` is immutable historical 1.0; do not rewrite it. Both consumers use `/api/v1`; never import engine internals into the client.
- Role branches are `feat/arena-engine` and `feat/arena-experience`; user-initiated integration is on `feat/arena-integration` in a separate worktree. Stage explicit owned paths; never force-push. Main merging requires the final integration gates and a user-initiated repository merge action.
- Follow the sprint gates in `docs/integration.md`. Sprint completion requires evidence; fixture tests are not a live Switch match.
- Never execute contestant code in the product process or checkout. Only the trusted runner may load candidate modules inside restricted Docker containers.
- Runtime state, tokens, snapshots and logs belong under gitignored `var/`. Never commit secrets or expose held-out/reference content through contestant assignments.
- Search before reading; read relevant ranges, keep output concise and run focused tests.
- For substantial independent tasks, delegate narrow work with explicit file ownership and acceptance criteria. Keep the main agent's selected configuration; use an available lower-cost model with low/medium effort for suitable bounded subtasks. Main agent reviews changes and test evidence.
