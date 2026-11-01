# Requirements: Trace Store (Roadmap P21)

## Goal

Keep a full, queryable record of every job in PostgreSQL: each model call, tool call and result, with tokens, cost and time (README FR8.1). It is what the dashboard's "job trace and cost" and "live job progress" views (FR8.2, FR8.4), failure analysis (FR11) and the spend counter will read. The recorder on disk (P22) and replay (P23) come next and are separate.

## Scope

**In:**
- A PostgreSQL schema with versioned migrations: `jobs`, `steps`, `model_calls`, `tool_calls`
- `TraceStore`: create the schema, start and finish jobs, write calls, read a job's trace, list jobs
- `TraceRecorder`: an agent-loop observer (P16) that writes to the store as events happen, taking tokens, cost, time and failed attempts from the cost ledger
- Sensitivity stored on every job; full content for all jobs (owner's choice)
- A hook to scrub secrets from everything before it is stored
- Failure isolation: a database problem never stops or changes a job
- A throwaway PostgreSQL 17 container for the real-database tests, started and removed by the tests

**Out (later phases):**
- Wiring it into the single-job runner (`bugbite.local_run`, on hold with P20) and the CLI/API: a follow-up once those are merged
- The on-disk recording format and replay (P22 to P24)
- The final status classification solved / partially solved / failed / aborted (P40); only the agent's own status and error are stored here
- Eval results, benchmark and spend-cap tables (P46 and the eval phases), the dashboard itself, users and permissions
- Retention, export and deleting old traces other than deleting a whole job
- Pooling and concurrency tuning

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Database access | PostgreSQL through `psycopg` 3 (a new dependency), plain SQL, versioned migrations in code, no ORM | The stack names PostgreSQL; the schema is small and fixed; plain SQL is easiest to audit and test (AD-113) |
| What a row is | One `model_calls` row per attempt (from the ledger, including failed and retried ones), one `tool_calls` row per tool call, one `steps` row per step; each step's new content once, never the whole history again | Complete, exact cost and timing without storing the conversation once per call (AD-114) |
| When it is written | As events happen, one short transaction each, so a live run and a crashed run are both visible | The dashboard shows live progress; a crash must not lose everything (AD-115) |
| Private jobs | Full content, with the job's sensitivity stored on the job | The database is local and the owner's; sensitivity lets later views hide private content (AD-116) |

See `specs/decisions.md` AD-113 to AD-116.

## Behaviour

- **Schema:** `schema_migrations(version, applied_at)`; migration 1 creates the four tables with foreign keys (deleting a job deletes its rows), indexes on job id, status and creation time, `timestamptz` times, `numeric` money, `bigint` token counts, `jsonb` for arguments and configuration. Applying migrations is idempotent and safe if two processes try at once (an advisory lock).
- **jobs:** id (UUID), created and finished times, issue URL, repository, commit, model, sensitivity, prompt version, tools version, the task text, the configuration snapshot (limits, retry policy, model settings, pre-step report; never a key), the Bugbite commit if known, status (`running` until finished or aborted, then the agent's status), final text, error code and message, limit detail, totals (tokens by kind, cost, steps, nudges, retries, elapsed seconds, observer errors).
- **steps:** job, step number, the nudge text if any.
- **model_calls:** job, step, order within the step, the model, request id, stop reason, tokens by kind, whether the usage was estimated, latency, cost (null for a failed attempt), error code (null for a success), and for a success the reply text.
- **tool_calls:** job, step, position, call id, tool name, arguments (`jsonb`), output text, error flag, whether it was run, duration.
- **Recorder:** on `ModelCallEvent` it reads the ledger entries added since the last event and stores them as that step's attempts (failed attempts that came first, the successful one last); on `ToolCallEvent` it stores the call; on `FinishEvent` it stores any remaining ledger entries (failed attempts of the final step), the nudges, the totals, and the final status. `abort(reason)` marks a job `aborted` with the reason (for the caller's exception handlers).
- **Reading:** `get_job(id)`, `get_trace(id)` (the job with its steps, each holding its attempts and tool calls in order), `list_jobs(limit, status, repo)` newest first, and `totals()` (jobs, tokens and cost, for the spend counter later).
- **Text safety:** PostgreSQL text cannot hold a NUL character, so NULs are replaced with the visible text `\x00`; very long text is cut at 1,000,000 characters with a marker. Everything goes in as query parameters, never by building SQL strings.
- **Scrubbing:** the recorder takes a `scrub` function applied to every string before storage (the runner will pass one that removes the model key).
- **Failure isolation:** a database error inside the recorder is caught, counted (`recorder.errors`), and remembered by type only; the job continues. Writes after an error keep being attempted.

## Context

- README: FR8.1 (the trace), FR8.2 and FR8.4 (dashboard views), FR10.4 (traceability), FR11 (failure analysis), FR14.9 and P13's open item (private code in traces).
- Builds on P11 (`CostLedger`, `CallRecord`), P16 to P19 (`AgentResult`, `Step`, `ToolRun`, events, the pre-step report) and P13 (`Sensitivity`).
- Other PostgreSQL servers on this machine (Homebrew, the `tablemate` and `reviewcode` containers) belong to other projects and are never used or touched.

## Constraints

- Real-database tests use only their own throwaway container, on a random local port, with a random password, labelled so the existing leftover checks see it, removed afterwards even on failure. Without Docker they are skipped with a visible reason.
- The connection string (it holds a password) is never logged, printed or placed in an error message or in `repr`.
- No SQL is built from model, issue or tool text.
- Default `uv run pytest` needs no Docker, internet or key (recorder logic is tested against a fake store).
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Traces of private jobs hold private code. The label is stored; nothing yet enforces who may read it (dashboard phases).
- No retention or size limits beyond the per-field cap; a long eval will produce many rows.
- The Bugbite commit hash is stored if the caller supplies it; nothing here finds it.
- Jobs whose process dies stay `running` until someone aborts them; a sweeper is not built.
- The ledger has no step numbers; the recorder derives them from event order (AD-114), which holds only if the same ledger serves exactly one job at a time.

## Findings from the build

- **The real database found a bug that every fake-store test missed:** the connection returns rows as dictionaries, and the migration code read `row[0]`. It failed on the first real run and was fixed (`row["version"]`). Reason enough for the real-PostgreSQL tests to exist.
- **Independent of P20.** This branch starts from `main`, which has no retry wrapper, so the tests use a small test-only retrying layer around the metering layer to produce failed and retried attempts. The recorder itself only reads the ledger, so it works with any wrapper chain.
- **Money is an unbounded `numeric`.** The plan said fixed precision; a fixed scale would round a cost silently if prices ever had more decimals, so the column has no scale and a test stores `0.0123456789012` and reads it back identical.
- **Duplicate steps are not an error.** `record_step` is an upsert so a nudge can be added at the end of a run; what the database refuses is a duplicate position of a model call or tool call, and a second `finish_job`.
- **Nudges are stored when the run finishes**, because the loop only reports them in the final result; a run that dies mid-way loses its nudge text (the model calls and tool calls are already stored).
- **The tightened kill test:** a test terminates the recorder's connection in the middle of a run. The result is identical to a run without a recorder, the dead connection is counted, the store reconnects by itself, and the later writes and the finish land.
- **Printed trace (manual check):** one line per model call with tokens and cost and one per tool call under each step; easy to follow how the agent reached its fix.
- **Mutation check:** 22 breakages (step off by one, failed attempts dropped, reply and tool output unscrubbed, NUL not replaced, SQL built from text, the connection string in the repr, a database error escaping, cost not summed, a missing cascade, nudges, duplicated ledger entries, positions, double finish, aborting a finished job, list order, JSON keys, earlier ledger entries, retries, totals, the sensitivity check, an unscrubbed config) are all caught.
- **Merge note:** this branch and the P20 branch both append a section to the end of the README; merging the second one will need a trivial conflict fix.
- Not done: wiring into the runner, access control, retention, a sweeper for stale `running` jobs.
- Full suite (foreground): 2134 passed and 156 skipped with Docker unreachable; 2284 passed and 6 skipped with Docker running (the trace store tests started and removed their own PostgreSQL 17); no leftover containers or volumes. New dependencies in `uv.lock`: `psycopg`, `psycopg-binary`, and `tzdata` (which `psycopg` needs only on Windows).
