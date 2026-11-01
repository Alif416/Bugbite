"""The database schema, as an ordered list of migrations (AD-113).

Add a new migration at the end; never edit one that has been released. `apply_migrations` is safe to call
from several processes at once.
"""

from __future__ import annotations

from typing import Any

LOCK_KEY = 7_212_021_001  # an arbitrary number that identifies "Bugbite schema changes" to pg_advisory_xact_lock

_V1 = """
CREATE TABLE jobs (
    id              uuid PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    issue_url       text NOT NULL,
    repo            text NOT NULL,
    ref             text,
    model           text NOT NULL,
    sensitivity     text NOT NULL CHECK (sensitivity IN ('public', 'sandbox', 'private')),
    prompt_version  text,
    tools_version   text,
    agent_commit    text,
    task_text       text,
    config          jsonb NOT NULL DEFAULT '{}'::jsonb,
    status          text NOT NULL DEFAULT 'running',
    final_text      text,
    error_code      text,
    error_message   text,
    limit_detail    text,
    steps_count     integer CHECK (steps_count >= 0),
    nudges          integer CHECK (nudges >= 0),
    retries         integer CHECK (retries >= 0),
    observer_errors integer CHECK (observer_errors >= 0),
    input_tokens        bigint CHECK (input_tokens >= 0),
    output_tokens       bigint CHECK (output_tokens >= 0),
    cache_read_tokens   bigint CHECK (cache_read_tokens >= 0),
    cache_write_tokens  bigint CHECK (cache_write_tokens >= 0),
    cost_usd        numeric CHECK (cost_usd >= 0),
    elapsed_s       double precision CHECK (elapsed_s >= 0)
);
CREATE INDEX jobs_created_idx ON jobs (created_at DESC, id);
CREATE INDEX jobs_status_idx ON jobs (status);
CREATE INDEX jobs_repo_idx ON jobs (repo);

CREATE TABLE steps (
    job_id  uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    step    integer NOT NULL CHECK (step >= 1),
    nudge   text,
    PRIMARY KEY (job_id, step)
);

CREATE TABLE model_calls (
    id                  bigserial PRIMARY KEY,
    job_id              uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    step                integer NOT NULL CHECK (step >= 1),
    position            integer NOT NULL CHECK (position >= 1),
    model               text NOT NULL,
    request_id          text,
    stop_reason         text,
    input_tokens        bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens       bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens   bigint NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_write_tokens  bigint NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    usage_estimated     boolean NOT NULL DEFAULT false,
    latency_s           double precision NOT NULL DEFAULT 0 CHECK (latency_s >= 0),
    cost_usd            numeric CHECK (cost_usd >= 0),
    error_code          text,
    response_text       text,
    requested_tools     jsonb,
    UNIQUE (job_id, step, position)
);
CREATE INDEX model_calls_job_idx ON model_calls (job_id, step, position);

CREATE TABLE tool_calls (
    id          bigserial PRIMARY KEY,
    job_id      uuid NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    step        integer NOT NULL CHECK (step >= 1),
    position    integer NOT NULL CHECK (position >= 1),
    call_id     text NOT NULL,
    tool        text NOT NULL,
    arguments   jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_text text NOT NULL,
    is_error    boolean NOT NULL,
    executed    boolean NOT NULL,
    duration_s  double precision NOT NULL DEFAULT 0 CHECK (duration_s >= 0),
    UNIQUE (job_id, step, position)
);
CREATE INDEX tool_calls_job_idx ON tool_calls (job_id, step, position);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, _V1)]


def apply_migrations(conn: Any) -> list[int]:
    """Apply the migrations that have not been applied yet. Returns the versions applied by this call."""
    applied: list[int] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))  # one applier at a time
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}  # rows are dicts
        for version, sql in MIGRATIONS:
            if version in done:
                continue
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied
