# Switch runtime materials

These files configure two **runtime contestants**. The Codex development chats that build Coding Arena are separate from those contestants.

- [Setup and smoke procedure](../docs/switch.md)
- [Live demo and labelled replay](../docs/demo.md)
- [Standing agent instructions](prompts/common.md)
- Phase instructions: [build](prompts/build.md), [review](prompts/review.md), [repair](prompts/repair.md)
- Room instructions: [independent build rooms](rooms/build.md), [shared review room](rooms/review.md)
- [Native smoke evidence record](smoke-record.json)

Use the native Switch Console agent runtime. No custom Switch protocol adapter, model-provider SDK, webhook, or framework is supplied here. Manual setup is the baseline; this directory does not claim to contain importable Switch templates.

The harmless `arena_smoke.py` command checks the current directory and reports its own digest. Running it directly tests only that local command. A native smoke passes only when an actual human addresses a registered agent, that agent executes it, and an actual room reply contains its output.
