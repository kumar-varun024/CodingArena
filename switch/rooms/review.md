# Shared review room instructions

Room: `arena-review`. Members: authorized humans and both contestants, **added only after the operator reveals both frozen initial submissions**. Do not include independent build content here before reveal.

Fetch the current assignment and follow `common.md` plus the review prompt. Each contestant reviews only its exact frozen opponent snapshot and submits bounded JSON scenarios through the trusted driver. It cannot edit the opponent copy, run arbitrary uploaded test code, change the oracle, accept a challenge or select a winner.

Challenge claims cite frozen requirement IDs and include state assertions when claiming no mutation. Actual reproduction requires reference success and two failures of the exact target; a human then decides whether the expectation follows the requirement. The operator records that decision in the dashboard. A room statement is contextual discussion, not authenticated approval.

Suggested human review kickoff, one addressed agent at a time:

```text
@arena-a Fetch your current assignment and review candidate TARGET_B. Find at most two concrete requirement violations, submit JSON reproductions, poll each actual job, and mark your review complete even if you found none. Report exact artifacts and uncertainty.
```

Repeat for `@arena-b` against `TARGET_A`. Human semantic decision example, used only after observing a reproduced result:

```text
The expected cancellation behavior follows BOOK-04. I accept this reproduced claim; I will record the decision in the operator dashboard.
```

After both reviews and all human dispositions resolve, the human records `start_repair` or `finalize`. Return agents to their own build rooms for repair after their review turns finish. The final discussion may compare measured evidence and tradeoffs; the dashboard records A/B/neither. No automatic winner, numeric quality score or model ranking is produced.
