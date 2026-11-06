# Engine scope and interface

The engine owns the trusted state of a match: task assignments, isolated slot workspaces, candidate snapshots, verification jobs, challenge adjudication, phase transitions, eligibility, and evidence/patch exports. The web dashboard and Switch client are consumers of the same HTTP API. The engine never imports or executes contestant code in its service process; a trusted driver loads candidate modules only inside the restricted Docker runner.

## Interface

The active API is **1.1**, served at `/api/v1`. Its canonical manifest is [contracts/arena-v1.1.json](../contracts/arena-v1.1.json), SHA-256 `c09582b2f82ee5ce5148f1701bbfcc8f8e93f31f18acb0863d6f5d717041708f`. [The original v1.0 manifest](../contracts/arena-v1.json) is retained unchanged as an archive. Both clients require the 1.1 version and response-mode header; do not change or relax either client to mask a server mismatch.

Health is public. Match, assignment, event, job, and artifact reads use an operator or slot token. Writes carry a UUID request ID and source context. The engine returns `X-Arena-Mode: live` on API responses; the fixture service labels its responses `fixture`. The dashboard rejects missing, invalid, or contradictory mode metadata. See the manifest for exact request fields, role visibility, response shapes, and error semantics.

## Match lifecycle

Two slots work independently from engine-provisioned task checkouts. After submissions, the operator reveals frozen candidate snapshots. Each slot reviews the other snapshot and can submit bounded JSON challenges tied to requirements. The runner checks the reference first, then runs the exact frozen target twice. Only a reproduced challenge may be accepted. Accepted challenges become shared regressions and invalidate both candidates' earlier verification evidence.

Once reviews and challenge decisions are resolved, the operator may request up to two repair rounds or finalize directly. A full verification includes the task baseline and all accepted regressions. Candidate selection requires current eligibility and the exact current evidence key. **Neither** is a valid selection from the decision phase and produces an evidence pack without a patch. The engine does not merge or apply a patch automatically.

For setup, CLI examples, and focused checks, see [Local setup](setup.md). The web guide covers dashboard use; the [Switch guide](switch.md) describes native agent setup and its separate evidence gate.

## Human operator CLI

Use the same `ARENA_STATE_DIR` as the server and run from the repository root. Omitted provider labels remain null/Unknown; record actual configuration only when known.

```sh
PYTHONPATH=engine .venv/bin/python -m arena_engine operator create
PYTHONPATH=engine .venv/bin/python -m arena_engine operator match --match MATCH_ID
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action --match MATCH_ID --action reveal --reason "Both initial jobs are terminal"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator decision --match MATCH_ID --challenge CHALLENGE_ID --disposition accepted --reason "The reproduced scenario violates the cited requirement"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action --match MATCH_ID --action start_repair --reason "Both reviews and all challenge decisions are resolved"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator action --match MATCH_ID --action finalize --reason "Run the unchanged current candidates against the complete suite"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select --match MATCH_ID --selection a --candidate CANDIDATE_ID --evidence-key var/evidence-key.json --reason "Current evidence supports this choice"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator select --match MATCH_ID --selection neither --reason "Neither candidate is acceptable"
PYTHONPATH=engine .venv/bin/python -m arena_engine operator export --match MATCH_ID
```

The selection examples are alternatives. Save the four-field `verification.evidence_key` from the latest match response as the JSON file supplied to `--evidence-key`. Export downloads evidence/summary and an eligible selected patch; neither exports no patch. To cancel a nonterminal match use `operator action --match MATCH_ID --action cancel --reason "..."`.

Mutations persist their UUID and canonical non-secret body before dispatch. After an ambiguous transport failure use `operator retry --request-id UUID`; never replace the ID/body merely because the response was lost. After a conclusive rejected operation, fix its cause and start a new operation with a new ID. Source flags accept actual room/message IDs as contextual provenance, not verified Switch authentication. Use `--source-kind fixture` for scripted fixture actions. A native agent's statement that a human approved has no operator authority.

## Runner and persisted state

The runner uses the pinned Python image digest, disposable containers, no network, read-only source/test mounts, a read-only root filesystem, a non-root user, dropped capabilities, bounded CPU/memory/processes, and a timeout. No candidate dependencies are installed. Practice jobs run public checks and accepted regressions only; they cannot establish eligibility. Full verification evidence is tied to candidate, runner, spec, and suite digests.

SQLite stores matches, jobs, events, artifacts, and idempotency records under the marked runtime directory. Interrupted running jobs become errors on restart; require an explicit rerun when appropriate. Runtime tokens, snapshots, logs, and exports belong under gitignored `var/`. Keep the existing state directory when its history or workspaces matter; initialization is not a reset operation.

## Verification boundary

The integration branch has passed 108 engine tests with Docker enabled. The actual bridge completed selected and neither fixture matches through HTTP; a selected patch applied and passed 12 checks on a fresh task base. An explicitly injected runner-failure fixture also recovered through finalization without changing candidate snapshots or consuming a repair round. The dashboard's actual API client passed read-only live checks. Separately, user-supplied native room screenshots and live engine records confirm both initial contestant submissions passed 11/11 checks; user dashboard screenshots and engine state confirm reveal. The remaining full native-match gate covers cross-review, adjudication, final verification, selection, and export validation. See [Sprint gates](integration.md).
