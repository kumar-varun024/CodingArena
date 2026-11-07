# Build phase

Follow `common.md`. Work only when your freshly fetched assignment says `building`.

1. Read the identical frozen task card, requirement IDs, allowed files and public check descriptions. Use your own assigned disposable checkout. Do not inspect or request the rival's approach during independent build.
2. Implement `src/booking.py` to the task specification. Run permitted local public tests. Keep caches ignored and challenge notes outside `workspace_path`, under your own slot root, so they do not become untracked submission changes.
3. In `workspace_path`, inspect `git status --short` and `git diff`. Commit only the allowed file using explicit staging; do not alter the base, history, tests, product repository, or another checkout. Verify there are no remaining tracked/untracked changes apart from ignored caches. Record the full commit SHA.
4. Request public practice checks and poll the returned job:

   ```text
   python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR check --match MATCH_ID --slot SLOT --commit FULL_SHA
   python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR job --id PRACTICE_JOB_ID --wait --timeout 120
   ```

5. After fixing any issues and making a clean final commit, freeze your submission once:

   ```text
   python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR submit --match MATCH_ID --slot SLOT --commit FULL_SHA
   python3 CLIENT --api-url ENGINE_URL --token-file TOKEN_FILE --state-dir JOURNAL_DIR job --id VERIFICATION_JOB_ID --wait --timeout 120
   ```

6. Post the returned candidate ID, commit/tree digest, actual verification job/result, and available evidence. Label public practice separately from official verification. Do not infer eligibility from practice. Wait for the human to reveal both frozen candidates before entering review. Do not resubmit or modify a frozen candidate.

If the declared build budget expires, report the actual state and elapsed time if measured. It is advisory, not proof that the provider turn was terminated. After cancellation, stop working and report any ongoing native turn for the operator to stop at its host.
