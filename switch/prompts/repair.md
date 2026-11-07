# Repair phase

Follow `common.md`. Return to your own build room only after the current native turn has finished. Fetch your assignment again and require `phase=repairing`. Record the `repair_round`, current suite/spec digests and accepted challenges.

Repair only your own implementation in the returned `workspace_path`, against the unchanged specification and accepted common regressions. Never copy a rival patch into a combined candidate or edit the rival snapshot. If your existing code is already adequate, resubmit the unchanged clean commit; both slots still need a submission for this round.

1. Run the permitted public tests and accepted scenarios. The challenge DSL remains single-instance; do not claim it proves multi-instance isolation.
2. Inspect and explicitly stage only `src/booking.py`, commit any repair, and verify the checkout is clean. Store notes/proof files outside the editable worktree.
3. Run `check --match MATCH_ID --slot SLOT --commit FULL_SHA` and poll its job. Label that result public practice.
4. Run `submit --match MATCH_ID --slot SLOT --commit FULL_SHA` once for this round and poll the returned job. Keep the exact request ID/body for ambiguous timeout recovery. The engine waits for both current submissions before completing shared verification; report a timeout as pending, not failure/success.
5. Report your new candidate ID, revision/commit/tree digest, actual official job/result and remaining blockers. No frozen candidate is rewritten. Await the operator's decision, rerun or next repair action.

The cap is two repair rounds and there is no second challenge phase. If both candidates remain flawed, say so with exact evidence. Selection of A, B or neither belongs to the human. A passing result covers the recorded checks only.
