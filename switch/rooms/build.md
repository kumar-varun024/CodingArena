# Independent build room instructions

Create one room named `arena-build-a` for `arena-a`, and another named `arena-build-b` for `arena-b`. Substitute the appropriate slot in these instructions. Each room includes only its own contestant and authorized humans. Keep the rival agent out throughout the match.

This room is the independent build and later repair workspace for slot SLOT. Read the installed `common.md` and phase prompt before work. The frozen task card must be identical in both build rooms, including task/spec digest, allowed file, public checks and declared budget. Fetch the assignment before every phase. The engine is the source of paths, snapshots, test evidence and phase state.

Before reveal, do not post rival approaches, diffs, code, private tests or results from another slot. Submit only your own clean commit through the arena client and report the returned evidence. Independent build ends when both initial candidates are frozen and the operator reveals them.

Only after reveal may the human bring both contestants into `arena-review`. Await completion of the native turn before addressing an agent in another room. After the human records `start_repair`, address this room's contestant here with the repair prompt. Room discussion alone does not advance engine state.

Suggested human kickoff (substitute actual values):

```text
@arena-a Fetch your assignment for MATCH_ID in slot a. Follow the build prompt, implement booking-v1 in your assigned checkout, run public checks, make a clean allowed-file commit, submit it, poll the actual job, and report the returned candidate and evidence IDs.
```

Use `@arena-b` and slot `b` in the other room. Provider/model identity must come from actual configuration; Unknown is valid.
