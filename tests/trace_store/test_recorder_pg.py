"""The agent loop, the real metering wrappers and the recorder writing to a real PostgreSQL."""

from decimal import Decimal

import pytest
from ts_helpers import FakeTools, Limits, Usage, AdapterError, scripted_run, text_response, tool_call_response

from bugbite.agent import PROMPT_VERSION
from bugbite.agent.tools import TOOLS_VERSION, ToolOutput
from bugbite.trace_store import JobStart, TraceStore, start_trace

pytestmark = pytest.mark.docker

USAGE = Usage(10, 5)
SECRET = "SECRET-TOKEN-8f3a"


def traced(store, script, *, sensitivity="public", scrub=lambda t: t, **kw):
    started = {}

    def make(ledger):
        started["recorder"] = start_trace(
            store, JobStart("https://github.com/o/r/issues/9", "o/r", "paid", sensitivity, ref="c" * 40, prompt_version=PROMPT_VERSION,
                            tools_version=TOOLS_VERSION, task_text="fix it", config={"limits": {"max_steps": 10}}), ledger, scrub=scrub)
        return started["recorder"]

    result, ledger, recorder, raw = scripted_run(script, make, **kw)
    return result, ledger, recorder, store.get_trace(recorder.job_id)


def totals_of(trace):
    calls = [c for s in trace.steps for c in s.model_calls]
    return (sum(c.input_tokens for c in calls), sum(c.output_tokens for c in calls),
            sum((c.cost_usd or Decimal(0) for c in calls), Decimal(0)))


def test_a_finished_run_is_stored_exactly(store):
    tools = FakeTools(outputs={"echo": ToolOutput("echoed")})
    script = [tool_call_response(("echo", {"text": "hello"}), text="let me check", usage=USAGE), text_response("Fixed.", usage=USAGE)]
    result, ledger, recorder, trace = traced(store, script, sensitivity="private", tools=tools)
    job = trace.job
    assert recorder.errors == 0 and job.status == "finished" == result.status and job.final_text == "Fixed."
    assert job.sensitivity == "private" and job.prompt_version == PROMPT_VERSION and job.tools_version == TOOLS_VERSION and job.ref == "c" * 40
    assert job.steps_count == len(result.steps) == len(trace.steps) == 2 and job.finished_at is not None
    assert (job.input_tokens, job.output_tokens) == (20, 10) == totals_of(trace)[:2]
    assert job.cost_usd == ledger.total_usd == totals_of(trace)[2] == result.cost_usd == Decimal("0.04")
    assert job.elapsed_s == result.elapsed_s
    first, second = trace.steps
    assert first.model_calls[0].response_text == "let me check" and first.model_calls[0].requested_tools[0]["name"] == "echo"
    assert (first.tool_calls[0].tool, first.tool_calls[0].arguments, first.tool_calls[0].output_text) == ("echo", {"text": "hello"}, "echoed")
    assert second.model_calls[0].response_text == "Fixed." and second.tool_calls == ()
    assert [c.cost_usd for c in (first.model_calls[0], second.model_calls[0])] == [Decimal("0.02")] * 2


def test_a_throttled_run_stores_every_attempt_and_a_failed_ending(store):
    slow = AdapterError("rate_limited", "slow")
    script = [slow, tool_call_response(("echo", {}), usage=USAGE), slow, slow, slow, slow]
    result, ledger, recorder, trace = traced(store, script, retry=True)
    assert result.status == "model_error" and trace.job.status == "model_error" and trace.job.error_code == "rate_limited"
    step1, step2 = trace.steps[0], trace.steps[1]
    assert [c.error_code for c in step1.model_calls] == ["rate_limited", None] and [c.error_code for c in step2.model_calls] == ["rate_limited"] * 4
    assert [c.position for c in step2.model_calls] == [1, 2, 3, 4]
    assert trace.job.retries == 4 and len(ledger.calls) == 6  # one wait in step 1, three in step 2
    assert trace.job.cost_usd == ledger.total_usd == Decimal("0.02") and all(c.cost_usd is None for c in step2.model_calls)
    assert trace.job.steps_count == 1  # the loop completed one step; the second ended in the failure


def test_a_nudge_and_a_loop_stop_are_stored(store):
    script = [tool_call_response(("echo", {"text": "a"}), first_id=i, usage=USAGE) for i in range(1, 8)]
    result, ledger, recorder, trace = traced(store, script)
    assert trace.job.status == "loop_detected" and trace.job.nudges == 1 == result.nudges
    assert "same echo call returned the same result 5 times" in trace.job.limit_detail
    nudged = [s for s in trace.steps if s.nudge]
    assert [s.step for s in nudged] == [3] and "same echo call 3 times" in nudged[0].nudge
    assert len(trace.steps) == 5 and all(len(s.tool_calls) == 1 for s in trace.steps)


def test_a_text_action_repair_is_two_calls_in_one_step(store):
    action = '{"tool": "echo", "arguments": {"text": "x"}}'
    script = [text_response("hmm", usage=USAGE), text_response(action, usage=USAGE), text_response('{"final": "done"}', usage=USAGE)]
    result, ledger, recorder, trace = traced(store, script, native=False)
    assert trace.job.status == "finished" and [len(s.model_calls) for s in trace.steps] == [2, 1] and trace.job.retries == 0
    assert trace.job.input_tokens == 30 and trace.job.cost_usd == Decimal("0.06")


def test_invalid_actions_and_skipped_calls_are_stored_with_their_flags(store):
    from bugbite.adapter import ToolCallBlock

    bad = ToolCallBlock("ta_1", "invalid_action", {}, "The reply was not a valid action: broken")
    result, ledger, recorder, trace = traced(store, [tool_call_response(bad, usage=USAGE), text_response("recovered", usage=USAGE)])
    tool = trace.steps[0].tool_calls[0]
    assert (tool.tool, tool.is_error, tool.executed, tool.output_text) == ("invalid_action", True, False, "The reply was not a valid action: broken")


def test_hostile_content_flowing_through_a_run_is_stored_safely(store):
    nasty = "x'); DROP TABLE tool_calls; --\x00 \U0001F642"
    tools = FakeTools(outputs={"echo": ToolOutput(nasty, True)})
    script = [tool_call_response(("echo", {"text": nasty}), text=nasty, usage=USAGE), text_response(nasty, usage=USAGE)]
    result, ledger, recorder, trace = traced(store, script, tools=tools)
    safe = nasty.replace("\x00", "\\x00")
    assert recorder.errors == 0 and trace.steps[0].tool_calls[0].output_text == safe and trace.steps[0].tool_calls[0].arguments == {"text": safe}
    assert trace.job.final_text == safe and trace.steps[0].model_calls[0].response_text == safe
    assert len(store.list_jobs()) == 1


def test_the_secret_never_reaches_the_database(store, pg_dsn):
    import psycopg

    tools = FakeTools(outputs={"echo": ToolOutput(f"output {SECRET}")})
    script = [tool_call_response(("echo", {"text": f"arg {SECRET}"}), text=f"reply {SECRET}", usage=USAGE), AdapterError("invalid_request", f"echoed {SECRET}")]
    result, ledger, recorder, trace = traced(store, script, tools=tools, scrub=lambda t: t.replace(SECRET, "[key]"))
    assert SECRET in result.messages[1].blocks[0].text  # it really was in the run
    with psycopg.connect(pg_dsn) as conn:
        for table in ("jobs", "steps", "model_calls", "tool_calls"):
            dump = str(conn.execute(f"SELECT t::text FROM {table} t").fetchall())
            assert SECRET not in dump, table
        assert "[key]" in str(conn.execute("SELECT t::text FROM tool_calls t").fetchall())


def test_a_database_that_goes_away_mid_run_does_not_change_the_result(pg_server, pg_dsn):
    import psycopg

    with TraceStore(pg_dsn) as store:
        store.create_schema()
        script = lambda: [tool_call_response(("echo", {}), usage=USAGE), tool_call_response(("echo", {}), first_id=2, usage=USAGE), text_response("done", usage=USAGE)]
        baseline, _, _, _ = scripted_run(script(), lambda ledger: (lambda event: None))
        killed = {}

        def make(ledger):
            recorder = start_trace(store, JobStart("u", "o/r", "m", "public"), ledger)
            killed["recorder"] = recorder
            original = recorder.__call__

            def wrapper(event):
                original(event)
                if type(event).__name__ == "ToolCallEvent" and "yes" not in killed:
                    killed["yes"] = True
                    with psycopg.connect(pg_server.dsn(), autocommit=True) as admin:  # kill the recorder's connection
                        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() "
                                      "OR datname = %s", (pg_dsn.rsplit("/", 1)[1],))
            return wrapper

        result, ledger, recorder, _ = scripted_run(script(), make)
        job = store.get_job(killed["recorder"].job_id)
        trace = store.get_trace(job.id)
    assert result.status == baseline.status == "finished" and result.final_text == baseline.final_text and len(result.steps) == len(baseline.steps)
    assert result.usage == baseline.usage and killed.get("yes")
    assert killed["recorder"].errors >= 1 and killed["recorder"].last_error  # the dead connection was noticed and counted ...
    assert job.status == "finished" and job.observer_errors >= 1  # ... and the store reconnected, so the later writes (and the finish) landed
    assert trace.steps[-1].model_calls[0].response_text == "done"


def test_one_trace_printed_for_a_human_to_read(store, capsys):
    script = [tool_call_response(("echo", {"text": "look"}), text="I will look first.", usage=USAGE), text_response("The bug was in f; fixed.", usage=USAGE)]
    result, ledger, recorder, trace = traced(store, script)
    j = trace.job
    lines = [f"job {j.repo} issue {j.issue_url.rsplit('/', 1)[1]} | {j.model} | {j.status} | steps {j.steps_count} | tokens {j.input_tokens}/{j.output_tokens} | cost ${j.cost_usd}"]
    for s in trace.steps:
        lines.append(f"  step {s.step}" + (f"  [nudge: {s.nudge}]" if s.nudge else ""))
        for c in s.model_calls:
            lines.append(f"    model {c.model} {c.stop_reason or c.error_code} in={c.input_tokens} out={c.output_tokens} cost=${c.cost_usd} text={c.response_text!r}")
        for t in s.tool_calls:
            lines.append(f"    tool {t.tool}({t.arguments}) -> {t.output_text!r}")
    text = "\n".join(lines)
    print(text)
    assert "step 1" in text and "tool echo" in text and "model paid" in text
