"""The trace store against a real PostgreSQL 17 (a throwaway container; see conftest.py)."""

import threading
import uuid
from decimal import Decimal

import psycopg
import pytest

from bugbite.trace_store import (
    MIGRATIONS, JobFinish, JobStart, ModelCallInput, ToolCallInput, TraceStore, TraceStoreError,
)
from bugbite.trace_store.store import MAX_TEXT_CHARS

pytestmark = pytest.mark.docker

INJECTION = "x'); DROP TABLE jobs; --"


def start(store, **kw):
    fields = dict(issue_url="https://github.com/o/r/issues/1", repo="o/r", model="m", sensitivity="public")
    fields.update(kw)
    return store.start_job(JobStart(**fields))


def table_names(store):
    rows = store._connection().execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
    return {r["table_name"] for r in rows}


# -- the server and the migrations ---------------------------------------------------------------------------------------------------


def test_the_tests_use_only_their_own_database_server(pg_server):
    assert pg_server.host == "127.0.0.1" and pg_server.port not in (5432, 54322, 5434)  # not the machine's other databases
    assert pg_server.container_name.startswith("bugbite-trace-test-")


def test_migrations_apply_once_and_again_do_nothing(pg_dsn):
    with TraceStore(pg_dsn) as store:
        assert store.create_schema() == [v for v, _ in MIGRATIONS]
        assert store.create_schema() == []
        assert {"jobs", "steps", "model_calls", "tool_calls", "schema_migrations"} <= table_names(store)
        rows = store._connection().execute("SELECT version FROM schema_migrations").fetchall()
        assert [r["version"] for r in rows] == [v for v, _ in MIGRATIONS]


def test_two_processes_applying_at_once_both_succeed(pg_dsn):
    results, errors = [], []

    def apply():
        try:
            with TraceStore(pg_dsn) as store:
                results.append(store.create_schema())
        except Exception as exc:  # pragma: no cover - the test fails below
            errors.append(exc)

    threads = [threading.Thread(target=apply) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and sorted(map(tuple, results)).count((1,)) == 1 and sum(1 for r in results if r == []) == 5
    with TraceStore(pg_dsn) as store:
        assert len(store._connection().execute("SELECT * FROM schema_migrations").fetchall()) == 1


def test_the_schema_has_the_foreign_keys_checks_and_indexes(store):
    conn = store._connection()
    cascades = conn.execute("SELECT count(*) AS n FROM pg_constraint WHERE contype = 'f' AND confdeltype = 'c'").fetchone()["n"]
    checks = conn.execute("SELECT count(*) AS n FROM pg_constraint WHERE contype = 'c'").fetchone()["n"]
    indexes = {r["indexname"] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'").fetchall()}
    assert cascades == 3 and checks >= 20
    assert {"jobs_created_idx", "jobs_status_idx", "jobs_repo_idx", "model_calls_job_idx", "tool_calls_job_idx"} <= indexes
    types = {r["column_name"]: r["data_type"] for r in conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'jobs'").fetchall()}
    assert types["cost_usd"] == "numeric" and types["created_at"] == "timestamp with time zone" and types["config"] == "jsonb"
    assert types["input_tokens"] == "bigint"


def test_a_wrong_password_is_an_error_that_does_not_show_it(pg_server):
    dsn = pg_server.dsn().replace(pg_server.password, "WRONG-PASSWORD-XYZ")
    with pytest.raises(TraceStoreError) as info:
        TraceStore(dsn).create_schema()
    assert "WRONG-PASSWORD" not in str(info.value) and pg_server.password not in str(info.value)


# -- a full round trip ------------------------------------------------------------------------------------------------------------------


def test_a_job_round_trips_exactly(store):
    job = start(store, ref="a" * 40, prompt_version="1", tools_version="2", agent_commit="b" * 40, task_text="Fix it\nplease",
                sensitivity="private", config={"limits": {"max_steps": 30, "max_cost_usd": "0.10"}, "prestep": {"tracebacks": 1}})
    store.record_model_calls(job, 1, [
        ModelCallInput("m", None, None, 0, 0, 0, 0, False, 1.5, None, "rate_limited"),
        ModelCallInput("m", "req_1", "tool_use", 100, 20, 5, 2, True, 0.75, Decimal("0.0123456789012"), None, "thinking",
                       [{"id": "call_1", "name": "read_file", "arguments": {"path": "a.py"}}]),
    ])
    store.record_tool_call(job, 1, ToolCallInput("call_1", "read_file", {"path": "a.py", "start_line": 1}, "     1| x = 1", False, True, 0.25))
    store.record_tool_call(job, 1, ToolCallInput("call_2", "run_command", {"command": "ls"}, "Not run: time", True, False, 0.0))
    store.record_model_calls(job, 2, [ModelCallInput("m", "req_2", "end_turn", 10, 5, response_text="done", cost_usd=Decimal("0.02"))])
    store.record_step(job, 1, "note to the model")
    store.finish_job(job, JobFinish("finished", "All done.", None, None, "a detail", 2, 1, 1, 0, 110, 25, 5, 2, Decimal("0.0323456789012"), 12.5))

    trace = store.get_trace(job)
    j = trace.job
    assert (j.id, j.issue_url, j.repo, j.ref, j.model, j.sensitivity) == (job, "https://github.com/o/r/issues/1", "o/r", "a" * 40, "m", "private")
    assert (j.prompt_version, j.tools_version, j.agent_commit, j.task_text) == ("1", "2", "b" * 40, "Fix it\nplease")
    assert j.config == {"limits": {"max_steps": 30, "max_cost_usd": "0.10"}, "prestep": {"tracebacks": 1}}
    assert (j.status, j.final_text, j.limit_detail, j.steps_count, j.nudges, j.retries) == ("finished", "All done.", "a detail", 2, 1, 1)
    assert (j.input_tokens, j.output_tokens, j.cache_read_tokens, j.cache_write_tokens, j.elapsed_s) == (110, 25, 5, 2, 12.5)
    assert j.cost_usd == Decimal("0.0323456789012") and j.created_at is not None and j.finished_at >= j.created_at
    assert [s.step for s in trace.steps] == [1, 2] and trace.steps[0].nudge == "note to the model" and trace.steps[1].nudge is None
    first, second = trace.steps[0].model_calls
    assert (first.position, first.error_code, first.cost_usd, first.latency_s) == (1, "rate_limited", None, 1.5)
    assert (second.position, second.request_id, second.stop_reason, second.usage_estimated) == (2, "req_1", "tool_use", True)
    assert (second.input_tokens, second.output_tokens, second.cache_read_tokens, second.cache_write_tokens) == (100, 20, 5, 2)
    assert second.cost_usd == Decimal("0.0123456789012") and second.response_text == "thinking"
    assert second.requested_tools == [{"id": "call_1", "name": "read_file", "arguments": {"path": "a.py"}}]
    t1, t2 = trace.steps[0].tool_calls
    assert (t1.position, t1.tool, t1.arguments, t1.output_text, t1.is_error, t1.executed, t1.duration_s) == (1, "read_file", {"path": "a.py", "start_line": 1}, "     1| x = 1", False, True, 0.25)
    assert (t2.position, t2.call_id, t2.is_error, t2.executed) == (2, "call_2", True, False)
    assert trace.steps[1].model_calls[0].response_text == "done" and trace.steps[1].tool_calls == ()


def test_positions_continue_across_calls(store):
    job = start(store)
    store.record_model_calls(job, 1, [ModelCallInput("m"), ModelCallInput("m")])
    store.record_model_calls(job, 1, [ModelCallInput("m")])
    store.record_model_calls(job, 2, [ModelCallInput("m")])
    trace = store.get_trace(job)
    assert [c.position for c in trace.steps[0].model_calls] == [1, 2, 3] and [c.position for c in trace.steps[1].model_calls] == [1]


def test_unknown_jobs_read_as_none(store):
    assert store.get_job(uuid.uuid4()) is None and store.get_trace(uuid.uuid4()) is None


# -- hostile and odd data -----------------------------------------------------------------------------------------------------------------


def test_hostile_and_odd_text_is_stored_safely(store):
    odd = ["emoji 🙂", "עברית ←→", "tab\tnewline\nreturn\r", "nul\x00inside", "surrogate \ud800 here", INJECTION, "\\x00 literal", "'; --", '"quotes"', "%s %(x)s {0}"]
    job = start(store, issue_url=INJECTION, repo=INJECTION, task_text="\n".join(odd), config={INJECTION: odd, "nul\x00key": "v\x00"})
    for i, text in enumerate(odd, 1):
        store.record_model_calls(job, i, [ModelCallInput(INJECTION, INJECTION, INJECTION, response_text=text, requested_tools=[{"id": text, "name": text, "arguments": {text: text}}])])
        store.record_tool_call(job, i, ToolCallInput(text, INJECTION, {text: [text, {"k": text}]}, text, False, True, 0.1))
    store.finish_job(job, JobFinish(INJECTION, text_for(odd), INJECTION, INJECTION, INJECTION))
    trace = store.get_trace(job)
    assert trace.job.issue_url == INJECTION and trace.job.repo == INJECTION and trace.job.status == INJECTION
    assert trace.job.config[INJECTION][3] == "nul\\x00inside" and trace.job.config["nul\\x00key"] == "v\\x00"
    assert [s.model_calls[0].response_text for s in trace.steps][0] == "emoji 🙂" and trace.steps[3].model_calls[0].response_text == "nul\\x00inside"
    assert trace.steps[1].tool_calls[0].arguments == {"עברית ←→": ["עברית ←→", {"k": "עברית ←→"}]}
    assert trace.steps[4].model_calls[0].response_text.startswith("surrogate ")
    assert {"jobs", "steps", "model_calls", "tool_calls"} <= table_names(store)  # the injection did nothing
    assert len(store.list_jobs()) == 1


def text_for(items):
    return "\n".join(items)


def test_a_two_megabyte_string_is_cut_with_its_marker(store):
    job = start(store, task_text="x" * 2_000_000)
    store.record_tool_call(job, 1, ToolCallInput("c", "t", {"big": "y" * 2_000_000}, "z" * 2_000_000, False, True, 0))
    trace = store.get_trace(job)
    assert len(trace.job.task_text) < MAX_TEXT_CHARS + 100 and trace.job.task_text.endswith("[... 1000000 more characters not stored ...]")
    tool = trace.steps[0].tool_calls[0]
    assert tool.output_text.endswith("more characters not stored ...]") and len(tool.arguments["big"]) < MAX_TEXT_CHARS + 100


# -- constraints --------------------------------------------------------------------------------------------------------------------------


def test_an_unknown_job_is_rejected_with_the_constraint_named(store):
    with pytest.raises(TraceStoreError, match="ForeignKeyViolation"):
        store.record_model_calls(uuid.uuid4(), 1, [ModelCallInput("m")])
    with pytest.raises(TraceStoreError, match="ForeignKeyViolation"):
        store.record_tool_call(uuid.uuid4(), 1, ToolCallInput("c", "t", {}, "o", False, True, 0))


def test_negative_numbers_and_bad_steps_are_rejected(store):
    job = start(store)
    with pytest.raises(TraceStoreError, match="CheckViolation"):
        store.record_model_calls(job, 1, [ModelCallInput("m", input_tokens=-1)])
    with pytest.raises(TraceStoreError, match="CheckViolation"):
        store.record_model_calls(job, 0, [ModelCallInput("m")])
    with pytest.raises(TraceStoreError, match="CheckViolation"):
        store.record_tool_call(job, 1, ToolCallInput("c", "t", {}, "o", False, True, -0.5))
    with pytest.raises(TraceStoreError, match="CheckViolation"):
        store.finish_job(job, JobFinish("finished", cost_usd=Decimal("-1")))
    with pytest.raises(psycopg.errors.CheckViolation):  # and the database itself refuses an unknown sensitivity
        store._connection().execute("INSERT INTO jobs (id, issue_url, repo, model, sensitivity) VALUES (%s, 'u', 'r', 'm', 'secret')", (uuid.uuid4(),))
    assert store.get_trace(job).steps == ()  # a rejected batch leaves nothing behind


def test_a_rejected_batch_is_all_or_nothing(store):
    job = start(store)
    with pytest.raises(TraceStoreError):
        store.record_model_calls(job, 1, [ModelCallInput("m"), ModelCallInput("m", output_tokens=-5)])
    assert store.get_trace(job).steps == ()


def test_positions_are_unique_in_the_database(store):
    job = start(store)
    store.record_model_calls(job, 1, [ModelCallInput("m")])
    with pytest.raises(psycopg.errors.UniqueViolation):
        store._connection().execute("INSERT INTO model_calls (job_id, step, position, model) VALUES (%s, 1, 1, 'm')", (job,))


def test_a_job_can_only_be_finished_once(store):
    job = start(store)
    store.finish_job(job, JobFinish("finished"))
    with pytest.raises(TraceStoreError, match="no running job"):
        store.finish_job(job, JobFinish("model_error"))
    with pytest.raises(TraceStoreError, match="no running job"):
        store.finish_job(uuid.uuid4(), JobFinish("finished"))
    assert store.get_job(job).status == "finished"


def test_deleting_a_job_deletes_everything_under_it(store):
    keep, drop = start(store), start(store)
    for job in (keep, drop):
        store.record_model_calls(job, 1, [ModelCallInput("m")])
        store.record_tool_call(job, 1, ToolCallInput("c", "t", {}, "o", False, True, 0))
        store.record_step(job, 1, "n")
    assert store.delete_job(drop) is True and store.delete_job(drop) is False
    conn = store._connection()
    for table in ("steps", "model_calls", "tool_calls"):
        rows = conn.execute(f"SELECT job_id FROM {table}").fetchall()
        assert [r["job_id"] for r in rows] == [keep], table
    assert store.get_job(drop) is None and store.get_job(keep) is not None


# -- queries --------------------------------------------------------------------------------------------------------------------------------


def test_listing_is_newest_first_and_filters(store):
    ids = []
    for i, (repo, status) in enumerate([("o/a", "finished"), ("o/b", "model_error"), ("o/a", "finished"), ("o/a", "loop_detected"), ("o/b", "finished")]):
        job = start(store, repo=repo)
        store.finish_job(job, JobFinish(status))
        ids.append(job)
    everything = store.list_jobs()
    assert [j.id for j in everything] == sorted(ids, key=lambda i: store.get_job(i).created_at, reverse=True)
    assert everything[0].id == ids[-1] and everything[-1].id == ids[0]
    assert {j.repo for j in store.list_jobs(repo="o/a")} == {"o/a"} and len(store.list_jobs(repo="o/a")) == 3
    assert [j.status for j in store.list_jobs(status="model_error")] == ["model_error"]
    assert len(store.list_jobs(status="finished", repo="o/b")) == 1 and store.list_jobs(status="nope") == []
    assert len(store.list_jobs(limit=2)) == 2 and store.list_jobs(limit=2)[0].id == ids[-1]


def test_totals_add_up_exactly(store):
    a, b, running = start(store), start(store), start(store)
    store.finish_job(a, JobFinish("finished", input_tokens=100, output_tokens=10, cache_read_tokens=5, cache_write_tokens=1, cost_usd=Decimal("0.1")))
    store.finish_job(b, JobFinish("finished", input_tokens=200, output_tokens=20, cost_usd=Decimal("0.2")))
    totals = store.totals()
    assert (totals.jobs, totals.running) == (3, 1) and totals.cost_usd == Decimal("0.3")
    assert (totals.input_tokens, totals.output_tokens, totals.cache_read_tokens, totals.cache_write_tokens) == (300, 30, 5, 1)


def test_an_empty_database_has_zero_totals(store):
    totals = store.totals()
    assert (totals.jobs, totals.cost_usd, totals.input_tokens) == (0, Decimal(0), 0)


def test_two_jobs_written_in_turns_do_not_mix(store):
    a, b = start(store, repo="o/a"), start(store, repo="o/b")
    for step in (1, 2, 3):
        store.record_model_calls(a, step, [ModelCallInput("ma", response_text=f"a{step}")])
        store.record_model_calls(b, step, [ModelCallInput("mb", response_text=f"b{step}")])
        store.record_tool_call(a, step, ToolCallInput(f"a{step}", "t", {}, f"out-a{step}", False, True, 0))
        store.record_tool_call(b, step, ToolCallInput(f"b{step}", "t", {}, f"out-b{step}", False, True, 0))
    for job, tag in ((a, "a"), (b, "b")):
        trace = store.get_trace(job)
        assert [s.model_calls[0].response_text for s in trace.steps] == [f"{tag}1", f"{tag}2", f"{tag}3"]
        assert [s.tool_calls[0].output_text for s in trace.steps] == [f"out-{tag}1", f"out-{tag}2", f"out-{tag}3"]


def test_two_stores_can_write_at_the_same_time(pg_dsn):
    with TraceStore(pg_dsn) as setup:
        setup.create_schema()
    errors = []

    def worker(n):
        try:
            with TraceStore(pg_dsn) as s:
                job = start(s, repo=f"o/w{n}")
                for step in range(1, 21):
                    s.record_model_calls(job, step, [ModelCallInput("m", response_text=str(step))])
                s.finish_job(job, JobFinish("finished"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    with TraceStore(pg_dsn) as s:
        assert len(s.list_jobs()) == 8 and all(j.status == "finished" for j in s.list_jobs())
        assert all(len(s.get_trace(j.id).steps) == 20 for j in s.list_jobs())


# -- crash and abort ----------------------------------------------------------------------------------------------------------------------------


def test_a_job_that_never_finished_reads_as_running_and_can_be_aborted(store):
    job = start(store)
    store.record_model_calls(job, 1, [ModelCallInput("m", response_text="partial")])
    row = store.get_job(job)
    assert row.status == "running" and row.finished_at is None and row.cost_usd is None
    assert store.get_trace(job).steps[0].model_calls[0].response_text == "partial"  # what was written before the "crash" is there
    assert store.abort_job(job, "the process was killed") is True
    row = store.get_job(job)
    assert row.status == "aborted" and row.error_message == "the process was killed" and row.finished_at is not None
    assert store.abort_job(job, "again") is False and store.get_job(job).error_message == "the process was killed"
    done = start(store)
    store.finish_job(done, JobFinish("finished"))
    assert store.abort_job(done, "too late") is False and store.get_job(done).status == "finished"


def test_the_connection_comes_back_after_being_closed(store):
    job = start(store)
    store.close()
    assert store.get_job(job) is not None and "connected=True" in repr(store)
