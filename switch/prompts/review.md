# Review phase

Follow `common.md`. Fetch the current assignment after the human reveals both candidates and addresses you in `arena-review`. Require `phase=reviewing`, a non-null `target_candidate_id`, and the engine-supplied read-only `review_path`. Read only that frozen opponent copy. Never patch it.

Find at most two concrete requirement violations. Do not submit speculation as reproduced evidence. The JSON driver creates one fresh `BookingSystem` per scenario; it cannot demonstrate isolation between multiple instances. Trusted baseline/held-out checks cover that BOOK-07 property. Do not add new operations or arbitrary executable tests.

Write each proof as a separate UTF-8 JSON file outside your editable worktree. It must have exactly `title`, `requirement_ids`, and `scenario`; use real requirement IDs. Include `available` and/or `reservations` assertions when claiming no state mutation. Business-invalid inputs can test BOOK-06; expected values use strict JSON types.

```json
{
  "title": "Repeated cancellation preserves available capacity and reservations",
  "requirement_ids": ["BOOK-03", "BOOK-04"],
  "scenario": {
    "capacity": 3,
    "steps": [
      {"op": "book", "args": ["family", 2], "expected": true},
      {"op": "cancel", "args": ["family"], "expected": true},
      {"op": "cancel", "args": ["family"], "expected": false},
      {"op": "available", "args": [], "expected": 3},
      {"op": "reservations", "args": [], "expected": {}}
    ]
  }
}
```

This is an example of the file format, not a claim that an opponent has this bug.

```text
python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR challenge --match MATCH_ID --target TARGET_CANDIDATE_ID --file PROOF_FILE
python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR job --id CHALLENGE_JOB_ID --wait --timeout 120
```

Count a reproduction only when the actual runner reports that the reference passed and the exact target failed twice. Report `invalid`, `not_reproduced`, `inconclusive`, errors and timeouts honestly. A reproduced challenge still needs the human's semantic decision; you cannot accept it yourself. A fresh inconclusive retry needs a fresh operation ID and is allowed only while reviewing; a retry after an ambiguous transport timeout reuses the original ID/body.

When all your attempts are terminal, mark your review complete, including when you found no issues:

```text
python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR review-done --match MATCH_ID --slot SLOT --target TARGET_CANDIDATE_ID
```

If a reproduction remains queued/running, report the job and wait; do not announce that the review is done. Finish with target ID, challenge/job IDs and statuses, evidence IDs, and an explicit no-findings statement when appropriate. After review completion, submit no more challenges. Await the human's phase action; do not start repair early.
