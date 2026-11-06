# Coding Arena

Two coding agents solve the same repository task independently. A human reviews their frozen submissions, decides which executable challenges match the requirements, and selects a verified patch—or neither candidate.

The intended flow is assignment → independent submissions → cross-review → human adjudication → repair → full verification → selection and export. Passing recorded checks does not prove code is bug-free.

**Current status: A's Sprint 1 foundation is verified.** The frozen v1 contract, booking-v1 task pack, scenario driver, health service and Docker fixture checker are available. B's foundation and shared hash confirmation remain pending. Match execution, dashboard integration and a live Switch demonstration are later sprint gates. Development roles A/B are separate from the two runtime contestants.

- [Local setup and verification](docs/setup.md)
- [Engine scope and interface](docs/engine.md)
- [Sprint plan and integration gates](docs/integration.md)
- [Frozen interface v1](contracts/arena-v1.json)

Role A owns the engine; Role B owns `web/`, `switch_bridge/`, `switch/` and their docs. Native Switch setup will be documented in B's [Switch guide](docs/switch.md) when available. Feature branches are integrated after both roles are ready; individual role work does not complete the product.

The MVP is local-first: one active match, two agents, one Python task pack and at most two repair rounds. It uses synthetic task data and restricted Docker execution. Fixture replays are labelled and never presented as live discoveries. Provider identity, timing and cost are shown only when actually known.

Competitive agent review is an existing category; [Agent Arena](https://github.com/JDKrasnick/agentarena) is a related project. This implementation starts from the supplied specification and does not incorporate its code.
