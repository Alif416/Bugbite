"""PostgreSQL storage for jobs and traces (README FR8.1). Plain SQL, every value a query parameter (AD-113)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .migrations import apply_migrations

MAX_TEXT_CHARS = 1_000_000
SENSITIVITIES = ("public", "sandbox", "private")


class TraceStoreError(Exception):
    """A database operation failed. The message names the operation, the kind of error and the constraint,
    never the connection string or any stored text."""


def clean_text(text: str) -> str:
    """Text PostgreSQL can store: no NUL characters, valid UTF-8, and no more than MAX_TEXT_CHARS."""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace("\x00", "\\x00").encode("utf-8", "replace").decode("utf-8")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + f"\n[... {len(text) - MAX_TEXT_CHARS} more characters not stored ...]"
    return text


def clean_json(value: Any) -> Any:
    """The same for JSON values (jsonb cannot hold NUL either), keys included."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {clean_text(str(k)): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clean_text(str(value))


def _opt(text: str | None) -> str | None:
    return None if text is None else clean_text(text)


# -- what goes in ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JobStart:
    issue_url: str
    repo: str
    model: str
    sensitivity: str
    ref: str | None = None
    prompt_version: str | None = None
    tools_version: str | None = None
    agent_commit: str | None = None
    task_text: str | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(f"sensitivity must be one of {SENSITIVITIES}, got {self.sensitivity!r}")


@dataclass(frozen=True)
class ModelCallInput:
    model: str
    request_id: str | None = None
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    usage_estimated: bool = False
    latency_s: float = 0.0
    cost_usd: Decimal | None = None  # None for a failed attempt: no cost is invented
    error_code: str | None = None
    response_text: str | None = None
    requested_tools: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ToolCallInput:
    call_id: str
    tool: str
    arguments: dict[str, Any]
    output_text: str
    is_error: bool
    executed: bool
    duration_s: float


@dataclass(frozen=True)
class JobFinish:
    status: str
    final_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    limit_detail: str | None = None
    steps_count: int = 0
    nudges: int = 0
    retries: int = 0
    observer_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    elapsed_s: float = 0.0


# -- what comes out ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JobRow:
    id: uuid.UUID
    created_at: datetime
    finished_at: datetime | None
    issue_url: str
    repo: str
    ref: str | None
    model: str
    sensitivity: str
    prompt_version: str | None
    tools_version: str | None
    agent_commit: str | None
    task_text: str | None
    config: dict[str, Any]
    status: str
    final_text: str | None
    error_code: str | None
    error_message: str | None
    limit_detail: str | None
    steps_count: int | None
    nudges: int | None
    retries: int | None
    observer_errors: int | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    cost_usd: Decimal | None
    elapsed_s: float | None


@dataclass(frozen=True)
class ModelCallRow:
    step: int
    position: int
    model: str
    request_id: str | None
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    usage_estimated: bool
    latency_s: float
    cost_usd: Decimal | None
    error_code: str | None
    response_text: str | None
    requested_tools: list[dict[str, Any]] | None


@dataclass(frozen=True)
class ToolCallRow:
    step: int
    position: int
    call_id: str
    tool: str
    arguments: dict[str, Any]
    output_text: str
    is_error: bool
    executed: bool
    duration_s: float


@dataclass(frozen=True)
class StepTrace:
    step: int
    nudge: str | None
    model_calls: tuple[ModelCallRow, ...]
    tool_calls: tuple[ToolCallRow, ...]


@dataclass(frozen=True)
class Trace:
    job: JobRow
    steps: tuple[StepTrace, ...]


@dataclass(frozen=True)
class Totals:
    jobs: int
    running: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: Decimal


_JOB_COLUMNS = (
    "id, created_at, finished_at, issue_url, repo, ref, model, sensitivity, prompt_version, tools_version, agent_commit, "
    "task_text, config, status, final_text, error_code, error_message, limit_detail, steps_count, nudges, retries, "
    "observer_errors, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, elapsed_s"
)


class TraceStore:
    """One autocommit connection to PostgreSQL. Not for use from several threads at once."""

    def __init__(self, dsn: str) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn must be a non-empty string")
        self.__dsn = dsn  # holds a password: never shown, logged or put in a message
        self._conn: psycopg.Connection[Any] | None = None

    def __repr__(self) -> str:
        return f"TraceStore(connected={self._conn is not None and not self._conn.closed})"

    def __enter__(self) -> "TraceStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- plumbing -------------------------------------------------------------------------------------------------------------

    def _connection(self) -> "psycopg.Connection[Any]":
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg.connect(self.__dsn, autocommit=True, row_factory=dict_row)
            except psycopg.Error as exc:
                raise TraceStoreError(f"could not connect to the database ({type(exc).__name__})") from None
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def _run(self, operation: str, work: Any) -> Any:
        try:
            return work(self._connection())
        except TraceStoreError:
            raise
        except psycopg.Error as exc:
            constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
            detail = f", constraint {constraint}" if constraint else ""
            raise TraceStoreError(f"{operation} failed ({type(exc).__name__}{detail})") from None

    def create_schema(self) -> list[int]:
        """Apply any migrations not yet applied. Safe to call again and from several processes."""
        return self._run("applying migrations", lambda conn: apply_migrations(conn))

    # -- writing ------------------------------------------------------------------------------------------------------------------

    def start_job(self, start: JobStart) -> uuid.UUID:
        job_id = uuid.uuid4()
        self._run("starting a job", lambda conn: conn.execute(
            "INSERT INTO jobs (id, issue_url, repo, ref, model, sensitivity, prompt_version, tools_version, agent_commit, task_text, config) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (job_id, clean_text(start.issue_url), clean_text(start.repo), _opt(start.ref), clean_text(start.model), start.sensitivity,
             _opt(start.prompt_version), _opt(start.tools_version), _opt(start.agent_commit), _opt(start.task_text),
             Jsonb(clean_json(start.config))),
        ))
        return job_id

    def record_step(self, job_id: uuid.UUID, step: int, nudge: str | None = None) -> None:
        """Create the step if needed; a nudge, when given, is set (so this can be called again to add it)."""
        self._run("recording a step", lambda conn: conn.execute(
            "INSERT INTO steps (job_id, step, nudge) VALUES (%s, %s, %s) "
            "ON CONFLICT (job_id, step) DO UPDATE SET nudge = COALESCE(EXCLUDED.nudge, steps.nudge)",
            (job_id, step, _opt(nudge)),
        ))

    def record_model_calls(self, job_id: uuid.UUID, step: int, calls: Iterable[ModelCallInput]) -> None:
        rows = list(calls)

        def work(conn: Any) -> None:
            with conn.transaction():
                conn.execute("INSERT INTO steps (job_id, step) VALUES (%s, %s) ON CONFLICT DO NOTHING", (job_id, step))
                for call in rows:
                    conn.execute(
                        "INSERT INTO model_calls (job_id, step, position, model, request_id, stop_reason, input_tokens, output_tokens, "
                        "cache_read_tokens, cache_write_tokens, usage_estimated, latency_s, cost_usd, error_code, response_text, requested_tools) "
                        "VALUES (%s, %s, (SELECT COALESCE(MAX(position), 0) + 1 FROM model_calls WHERE job_id = %s AND step = %s), "
                        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (job_id, step, job_id, step, clean_text(call.model), _opt(call.request_id), _opt(call.stop_reason),
                         call.input_tokens, call.output_tokens, call.cache_read_tokens, call.cache_write_tokens, call.usage_estimated,
                         call.latency_s, call.cost_usd, _opt(call.error_code), _opt(call.response_text),
                         None if call.requested_tools is None else Jsonb(clean_json(call.requested_tools))),
                    )

        self._run("recording model calls", work)

    def record_tool_call(self, job_id: uuid.UUID, step: int, call: ToolCallInput) -> None:
        def work(conn: Any) -> None:
            with conn.transaction():
                conn.execute("INSERT INTO steps (job_id, step) VALUES (%s, %s) ON CONFLICT DO NOTHING", (job_id, step))
                conn.execute(
                    "INSERT INTO tool_calls (job_id, step, position, call_id, tool, arguments, output_text, is_error, executed, duration_s) "
                    "VALUES (%s, %s, (SELECT COALESCE(MAX(position), 0) + 1 FROM tool_calls WHERE job_id = %s AND step = %s), "
                    "%s, %s, %s, %s, %s, %s, %s)",
                    (job_id, step, job_id, step, clean_text(call.call_id), clean_text(call.tool), Jsonb(clean_json(call.arguments)),
                     clean_text(call.output_text), call.is_error, call.executed, call.duration_s),
                )

        self._run("recording a tool call", work)

    def finish_job(self, job_id: uuid.UUID, finish: JobFinish) -> None:
        def work(conn: Any) -> int:
            return conn.execute(
                "UPDATE jobs SET finished_at = now(), status = %s, final_text = %s, error_code = %s, error_message = %s, limit_detail = %s, "
                "steps_count = %s, nudges = %s, retries = %s, observer_errors = %s, input_tokens = %s, output_tokens = %s, "
                "cache_read_tokens = %s, cache_write_tokens = %s, cost_usd = %s, elapsed_s = %s "
                "WHERE id = %s AND status = 'running'",
                (clean_text(finish.status), _opt(finish.final_text), _opt(finish.error_code), _opt(finish.error_message), _opt(finish.limit_detail),
                 finish.steps_count, finish.nudges, finish.retries, finish.observer_errors, finish.input_tokens, finish.output_tokens,
                 finish.cache_read_tokens, finish.cache_write_tokens, finish.cost_usd, finish.elapsed_s, job_id),
            ).rowcount

        if self._run("finishing a job", work) == 0:
            raise TraceStoreError("finishing a job failed (no running job with that id)")

    def abort_job(self, job_id: uuid.UUID, reason: str) -> bool:
        """Mark a still-running job aborted. Returns False if it was not running."""
        return self._run("aborting a job", lambda conn: conn.execute(
            "UPDATE jobs SET status = 'aborted', error_message = %s, finished_at = now() WHERE id = %s AND status = 'running'",
            (clean_text(reason), job_id),
        ).rowcount) > 0

    def delete_job(self, job_id: uuid.UUID) -> bool:
        return self._run("deleting a job", lambda conn: conn.execute("DELETE FROM jobs WHERE id = %s", (job_id,)).rowcount) > 0

    # -- reading -------------------------------------------------------------------------------------------------------------------

    def get_job(self, job_id: uuid.UUID) -> JobRow | None:
        row = self._run("reading a job", lambda conn: conn.execute(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = %s", (job_id,)).fetchone())
        return None if row is None else JobRow(**row)

    def list_jobs(self, *, limit: int = 50, status: str | None = None, repo: str | None = None) -> list[JobRow]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        rows = self._run("listing jobs", lambda conn: conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE (%s::text IS NULL OR status = %s) AND (%s::text IS NULL OR repo = %s) "
            "ORDER BY created_at DESC, id LIMIT %s",
            (status, status, repo, repo, limit),
        ).fetchall())
        return [JobRow(**row) for row in rows]

    def get_trace(self, job_id: uuid.UUID) -> Trace | None:
        job = self.get_job(job_id)
        if job is None:
            return None

        def work(conn: Any) -> tuple[list[Any], list[Any], list[Any]]:
            steps = conn.execute("SELECT step, nudge FROM steps WHERE job_id = %s ORDER BY step", (job_id,)).fetchall()
            calls = conn.execute(
                "SELECT step, position, model, request_id, stop_reason, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
                "usage_estimated, latency_s, cost_usd, error_code, response_text, requested_tools FROM model_calls "
                "WHERE job_id = %s ORDER BY step, position", (job_id,)).fetchall()
            tools = conn.execute(
                "SELECT step, position, call_id, tool, arguments, output_text, is_error, executed, duration_s FROM tool_calls "
                "WHERE job_id = %s ORDER BY step, position", (job_id,)).fetchall()
            return steps, calls, tools

        steps, calls, tools = self._run("reading a trace", work)
        traces = tuple(
            StepTrace(
                s["step"], s["nudge"],
                tuple(ModelCallRow(**c) for c in calls if c["step"] == s["step"]),
                tuple(ToolCallRow(**t) for t in tools if t["step"] == s["step"]),
            )
            for s in steps
        )
        return Trace(job, traces)

    def totals(self) -> Totals:
        row = self._run("summing jobs", lambda conn: conn.execute(
            "SELECT count(*) AS jobs, count(*) FILTER (WHERE status = 'running') AS running, "
            "COALESCE(sum(input_tokens), 0) AS input_tokens, COALESCE(sum(output_tokens), 0) AS output_tokens, "
            "COALESCE(sum(cache_read_tokens), 0) AS cache_read_tokens, COALESCE(sum(cache_write_tokens), 0) AS cache_write_tokens, "
            "COALESCE(sum(cost_usd), 0) AS cost_usd FROM jobs").fetchone())
        return Totals(**{k: (int(v) if k != "cost_usd" else Decimal(v)) for k, v in row.items()})
