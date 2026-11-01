# Validation: Trace Store (Roadmap P21)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable (run in the foreground): only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Pure parts:** `clean_text` replaces NUL with the visible text `\x00` and cuts text over 1,000,000 characters with a marker; the migration list starts at 1 with no gaps; `repr` of the store and of any error shows no password.
- [x] **Recorder, step assignment:** against a fake store, each model-call event stores the ledger entries added since the last event under that step (failed attempts first, the success last); a text-action step with a repair stores both entries; failed attempts after the last event are stored at finish under the next step; no ledger entry is stored twice or lost.
- [x] **Recorder, content:** tool calls are stored with arguments, output, error flag, executed flag and duration; nudges are stored on their step; the final status, error, limit detail and totals come from the `AgentResult` and the ledger.
- [x] **Scrubbing:** with a sentinel secret, every string handed to the store (task, replies, arguments, outputs, error messages, nudges) has passed through `scrub`.
- [x] **Failure isolation:** with a store that raises on every call, `run_agent` still returns the same result as without a recorder, `recorder.errors` counts the failures, and no database text appears in any exception message that escapes.
- [x] **No SQL from text:** a scan of the store module finds no f-string, `%` or `+` building SQL from variables (only fixed SQL with parameters), and a test feeds injection text through every writer.
- [x] **Mutation check:** each of these breakages makes at least one test fail: step off by one, failed attempts dropped, scrubbing skipped, NUL not replaced, SQL built from a string, the DSN in `repr`, a database error escaping the recorder, totals not summed, cascade delete removed, nudges not stored, ledger entries stored twice.

## Real PostgreSQL (opt-in, Docker; run once before merge)

- [x] The tests start their own `postgres:17` container and remove it; no other database on the machine is contacted (a test checks the DSN host is the container's local port); no labelled containers or volumes are left.
- [x] **Migrations:** applying twice changes nothing; two concurrent appliers both succeed and the version is recorded once; the schema has the four tables, the foreign keys, the indexes and the checks.
- [x] **Round trip:** a job written through the recorder reads back identical in `get_trace`, with `Decimal` cost exact to the last digit, tokens by kind, times, `jsonb` arguments equal, and calls in order.
- [x] **Hostile and odd data:** SQL injection strings, NUL characters, emoji, right-to-left text and a 2 MB string are stored and read back safely (the long one cut with its marker); the tables still exist afterwards.
- [x] **Constraints:** an unknown job, a negative count or step, a duplicate position and a second finish are rejected with a clear error naming the constraint; deleting a job deletes its steps, calls and tool calls.
- [x] **Queries:** `list_jobs` is newest first and filters by status and repository; `totals` sums tokens and cost across jobs exactly; two jobs written in an interleaved way do not mix.
- [x] **Crash and abort:** a job with no finish reads as `running`; `abort_job` sets `aborted` and the reason.
- [x] **Integration:** `run_agent` with scripted models, the real metering and retry wrappers and the recorder leaves rows that match the `AgentResult` and the ledger exactly, for a finished run, a model-error ending (with retried attempts), a loop-detection run (nudge stored) and a text-action run with a repair.

## Manual checks

- [x] Print one complete trace for a scripted run and read it as the dashboard author would: can you follow how the agent reached its fix, step by step, with cost per step?
- [x] `git grep -nE "os.environ|getenv" src/bugbite/trace_store` returns nothing.
- [x] `pyproject.toml` and `uv.lock` change only by `psycopg` and its own dependencies.

## Docs and process

- [x] `specs/decisions.md` has AD-113 to AD-116 with reasons.
- [x] `specs/roadmap.md` has P21 ticked.
- [x] README explains the tables, the recorder, the test database and what is not stored or enforced yet.
- [x] Commits are small and logical on branch `2026-11-02-p21-trace-store`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (the P20 runner is untouched; no dashboard, no disk recorder).

## Definition of done

All boxes ticked, tests green locally (run in the foreground) with Docker both running and unreachable, and the branch ready for review and merge into `main`.
