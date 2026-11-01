# Plan: Trace Store (Roadmap P21)

Branch: `2026-11-02-p21-trace-store` (from `main`; the P20 branch is on hold). See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-113 onward).

## 1. Dependency and schema

1. Add `psycopg[binary]` (3.x) to `pyproject.toml`; `uv lock`.
2. `src/bugbite/trace_store/migrations.py`: an ordered list of `(version, sql)`; migration 1 creates the four tables, foreign keys with `ON DELETE CASCADE`, indexes, and `CHECK` constraints (non-negative counts, known step order). `apply_migrations(conn)` takes `pg_advisory_xact_lock`, creates `schema_migrations` if missing, applies the missing versions each in its own transaction, and returns the versions applied.

## 2. The store (`src/bugbite/trace_store/store.py`)

1. `TraceStore(dsn)`: opens one autocommit connection (lazy); `repr` shows no password; `close()`; context manager.
2. Writers: `start_job(JobStart) -> UUID`, `record_step(job, step, nudge)`, `record_model_calls(job, step, records)`, `record_tool_call(job, step, position, run)`, `finish_job(job, result, totals)`, `abort_job(job, reason)`. All values are query parameters; a `clean_text` helper replaces NUL and cuts very long text; JSON values go through `psycopg.types.json.Jsonb`.
3. Readers: `get_job`, `get_trace`, `list_jobs`, `totals`, plus dataclasses `JobRow`, `StepTrace`, `ModelCallRow`, `ToolCallRow`, `Trace`.
4. `delete_job(job)` for cleanup and tests.

## 3. The recorder (`src/bugbite/trace_store/recorder.py`)

`TraceRecorder(store, job_id, ledger, *, scrub=identity)` is an `Observer`. It tracks how many ledger entries it has already stored and the current step, handles the three event types as in `requirements.md`, applies `scrub` to every string, absorbs and counts database errors, and offers `abort(reason)`. `start_trace(store, ...)` is a helper that creates the job row from the runner's facts and returns the recorder.

## 4. Test database helper

`tests/pg_helpers.py`: a session-scoped fixture that starts `postgres:17` with the Docker SDK (random password and port, `tmpfs` data directory, labels `bugbite=trace-store-test`), waits until it accepts connections, yields a DSN, and removes the container in teardown and in an `atexit` backstop. Each test gets a fresh database (create and drop) so tests do not see each other's rows.

## 5. Tests

1. Pure: `clean_text`, row mapping, migration list shape (versions strictly increasing from 1, no gaps), DSN hiding in `repr`.
2. Recorder against a fake store: step assignment from the ledger (success only; failures then success; failures at the end after the last event; text-action repairs giving several entries in one step), scrubbing of every string, error absorption (the store raising on every call; the job result still complete), abort, totals, ordering of writes.
3. Real PostgreSQL (Docker): migrations idempotent and concurrent-safe; full round trip equal to the in-memory result; exact `Decimal` cost; hostile strings (SQL injection text, NUL, emoji, very long); jsonb arguments; foreign keys and cascade; list filtering and order; totals; two jobs interleaved; constraint violations rejected; a crashed run (no finish) visible as `running`; `abort`.
4. Integration (Docker): `run_agent` with scripted models, the real metering and retry wrappers and a `TraceRecorder`: rows match `AgentResult` and the ledger (tokens, cost, step counts, failed attempts, nudges, tool outputs), including a model-error ending and a text-action step with a repair.
5. Mutation check: step off by one, failed attempts dropped, scrub skipped, NUL not replaced, SQL built by string, DSN in repr, errors escaping the recorder, totals not summed, cascade removed, finish not storing the nudges, ledger entries stored twice.

## 6. Docs

README section "Trace store"; roadmap P21 ticked; findings; validation ticked; AD-113 to AD-116.
