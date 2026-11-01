"""The recorder against a fake store: what it writes, in what order, with what numbers."""

import dataclasses
import uuid
from decimal import Decimal

import pytest
from ts_helpers import ECHO, AdapterError, FakeTools, Limits, model, scripted_run, text_response, tool_call_response

from bugbite.adapter import CostLedger, MeteredAdapter
from bugbite.adapter.testing import ScriptedAdapter
from bugbite.agent import run_agent
from bugbite.agent.tools import ToolOutput
from bugbite.trace_store import JobStart, TraceRecorder, start_trace
from bugbite.trace_store.recorder import _scrub_json

JOB = uuid.uuid4()
SECRET = "SECRET-TOKEN-8f3a"


class FakeStore:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def _do(self, name, *args):
        self.calls.append((name, args))
        if self.fail:
            raise RuntimeError(f"{SECRET} postgresql://u:{SECRET}@h/d")

    def start_job(self, start):
        self._do("start_job", start)
        return JOB

    def record_step(self, job, step, nudge=None):
        self._do("record_step", job, step, nudge)

    def record_model_calls(self, job, step, calls):
        self._do("record_model_calls", job, step, list(calls))

    def record_tool_call(self, job, step, call):
        self._do("record_tool_call", job, step, call)

    def finish_job(self, job, finish):
        self._do("finish_job", job, finish)

    def abort_job(self, job, reason):
        self._do("abort_job", job, reason)

    def names(self):
        return [c[0] for c in self.calls]

    def model_calls(self):
        return [(a[1], call) for n, a in self.calls if n == "record_model_calls" for call in a[2]]

    def finish(self):
        return next(a[1] for n, a in self.calls if n == "finish_job")


def go(script, store=None, **kw):
    store = store or FakeStore()
    scrub = kw.pop("scrub", lambda t: t)

    def make(ledger):
        return TraceRecorder(store, JOB, ledger, scrub=scrub)

    result, ledger, recorder, raw = scripted_run(script, make, **kw)
    return result, ledger, recorder, store


USAGE = dict(usage=__import__("bugbite.adapter", fromlist=["Usage"]).Usage(10, 5))


# -- what is written and in what order ---------------------------------------------------------------------------------------


def test_a_two_step_run_is_written_in_order_with_the_ledgers_numbers():
    result, ledger, recorder, store = go([tool_call_response(("echo", {"text": "hi"}), text="thinking", **USAGE), text_response("done", **USAGE)])
    assert store.names() == ["record_model_calls", "record_tool_call", "record_model_calls", "finish_job"] and recorder.errors == 0
    (step1, call1), (step2, call2) = store.model_calls()
    assert (step1, step2) == (1, 2) and call1.response_text == "thinking" and call2.response_text == "done"
    assert call1.requested_tools == [{"id": "call_1", "name": "echo", "arguments": {"text": "hi"}}] and call2.requested_tools is None
    record = ledger.calls[0]
    assert (call1.input_tokens, call1.output_tokens) == (10, 5) and call1.cost_usd == record.cost.total_usd == Decimal("0.02")
    assert call1.latency_s == record.latency_s and call1.stop_reason == "tool_use" and call2.stop_reason == "end_turn" and call1.error_code is None
    tool = next(a[2] for n, a in store.calls if n == "record_tool_call")
    assert (tool.tool, tool.arguments, tool.output_text, tool.is_error, tool.executed) == ("echo", {"text": "hi"}, "echo: hi", False, True)
    finish = store.finish()
    assert (finish.status, finish.final_text, finish.steps_count, finish.nudges, finish.retries) == ("finished", "done", 2, 0, 0)
    assert (finish.input_tokens, finish.output_tokens) == (20, 10) and finish.cost_usd == ledger.total_usd == Decimal("0.04")
    assert finish.elapsed_s == result.elapsed_s and finish.error_code is None


def test_failed_attempts_come_first_in_their_step_and_count_as_retries():
    slow = AdapterError("rate_limited", "slow", retry_after_s=1)
    result, ledger, recorder, store = go([slow, AdapterError("timeout", "t"), text_response("ok", **USAGE)], retry=True)
    rows = [c for _, c in store.model_calls()]
    assert [r.error_code for r in rows] == ["rate_limited", "timeout", None] and [s for s, _ in store.model_calls()] == [1, 1, 1]
    assert rows[0].cost_usd is None and rows[0].input_tokens == 0 and rows[0].response_text is None and rows[2].response_text == "ok"
    assert store.finish().retries == 2 and store.finish().cost_usd == Decimal("0.02") and len(ledger.calls) == 3


def test_failed_attempts_after_the_last_reply_are_stored_under_the_next_step():
    result, ledger, recorder, store = go([tool_call_response(("echo", {}), **USAGE), AdapterError("auth_failed", "bad key")])
    steps = [(s, c.error_code) for s, c in store.model_calls()]
    assert steps == [(1, None), (2, "auth_failed")] and result.status == "model_error"
    finish = store.finish()
    assert (finish.status, finish.error_code, finish.error_message, finish.steps_count, finish.retries) == ("model_error", "auth_failed", "bad key", 1, 0)


def test_attempts_that_ran_out_of_retries_are_all_kept():
    errors = [AdapterError("server_error", f"e{i}") for i in range(4)]
    result, ledger, recorder, store = go([tool_call_response(("echo", {}), **USAGE)] + errors, retry=True)
    last = [(s, c.error_code) for s, c in store.model_calls() if s == 2]
    assert last == [(2, "server_error")] * 4 and store.finish().retries == 3  # three waits, then it gave up


def test_a_text_action_repair_stores_both_calls_in_one_step():
    reply = '{"tool": "echo", "arguments": {"text": "x"}}'
    result, ledger, recorder, store = go(
        [text_response("I will think about it", **USAGE), text_response(reply, **USAGE), text_response('{"final": "done"}', **USAGE)], native=False
    )
    steps = [s for s, _ in store.model_calls()]
    assert steps == [1, 1, 2] and result.status == "finished" and store.finish().retries == 0  # a repair is not a retry
    assert store.finish().input_tokens == 30 and store.finish().cost_usd == Decimal("0.06")


def test_nudges_are_stored_on_their_step():
    script = [tool_call_response(("echo", {"text": "a"}), first_id=i, **USAGE) for i in range(1, 4)] + [text_response("stop", **USAGE)]
    result, ledger, recorder, store = go(script)
    nudges = [(a[1], a[2]) for n, a in store.calls if n == "record_step"]
    assert result.nudges == 1 and len(nudges) == 1 and nudges[0][0] == 3 and "same echo call 3 times" in nudges[0][1]
    assert store.finish().nudges == 1


def test_a_loop_stop_is_stored_with_its_detail():
    script = [tool_call_response(("echo", {"text": "a"}), first_id=i, **USAGE) for i in range(1, 8)]
    result, _, _, store = go(script)
    finish = store.finish()
    assert finish.status == "loop_detected" and "same echo call returned the same result 5 times" in finish.limit_detail


def test_ledger_entries_from_before_the_job_are_not_ours():
    ledger = CostLedger()
    old = MeteredAdapter(ScriptedAdapter(model(), [text_response("old", **USAGE)] * 2), ledger)
    from bugbite.adapter import GenerationRequest, Message
    for _ in range(2):
        old.generate(GenerationRequest(messages=(Message.user("x"),)))
    store = FakeStore()
    recorder = TraceRecorder(store, JOB, ledger)
    adapter = MeteredAdapter(ScriptedAdapter(model(), [text_response("new", **USAGE)]), ledger)
    result = run_agent(adapter, FakeTools(), "t", limits=Limits(5), ledger=ledger, observer=recorder)
    assert len(store.model_calls()) == 1 and store.finish().cost_usd == Decimal("0.02") and result.cost_usd == Decimal("0.02")


def test_an_unmetered_reply_is_stored_from_the_reply_itself():
    store = FakeStore()
    ledger = CostLedger()
    result = run_agent(ScriptedAdapter(None, [text_response("plain", **USAGE)]), FakeTools(), "t", limits=Limits(3), observer=TraceRecorder(store, JOB, ledger))
    [(step, call)] = store.model_calls()
    assert step == 1 and call.response_text == "plain" and call.cost_usd is None and call.input_tokens == 10 and result.finished


def test_unknown_events_are_ignored():
    recorder = TraceRecorder(FakeStore(), JOB, CostLedger())
    recorder("not an event")
    recorder(None)
    assert recorder.errors == 0


# -- secrets -------------------------------------------------------------------------------------------------------------------------


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from strings_in(getattr(value, f.name))
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from strings_in(k)
            yield from strings_in(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings_in(v)


def test_every_string_is_scrubbed_before_it_reaches_the_store():
    tools = FakeTools(outputs={"echo": ToolOutput(f"output has {SECRET}")})
    script = [
        tool_call_response(("echo", {"text": f"arg {SECRET}"}), text=f"reply {SECRET}", **USAGE),
        AdapterError("invalid_request", f"provider echoed {SECRET}"),
    ]
    scrub = lambda t: t.replace(SECRET, "[key]")
    result, ledger, recorder, store = go(script, tools=tools, scrub=scrub)
    assert SECRET in result.messages[1].blocks[0].text  # the raw run did contain it ...
    stored = [s for _, args in store.calls for s in strings_in(args)]
    assert stored and not any(SECRET in s for s in stored)  # ... but nothing stored does
    assert any("[key]" in s for s in stored)


def test_start_trace_scrubs_the_job_row_and_the_nested_config():
    store = FakeStore()
    scrub = lambda t: t.replace(SECRET, "[key]")
    start = JobStart(f"https://x/{SECRET}", f"o/{SECRET}", f"m-{SECRET}", "public", ref=SECRET, task_text=f"task {SECRET}",
                     config={"limits": {"note": SECRET}, "list": [SECRET, 1], SECRET: "k"})
    recorder = start_trace(store, start, CostLedger(), scrub=scrub)
    sent = store.calls[0][1][0]
    assert not any(SECRET in s for s in strings_in(sent)) and recorder.job_id == JOB
    assert _scrub_json({"a": [SECRET, {SECRET: SECRET}]}, scrub) == {"a": ["[key]", {"[key]": "[key]"}]}


# -- failure isolation -------------------------------------------------------------------------------------------------------------------


def test_a_dead_database_changes_nothing_about_the_run():
    script = lambda: [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)]
    baseline, _, _, _ = go(script())
    broken, ledger, recorder, store = go(script(), store=FakeStore(fail=True))
    for attr in ("status", "final_text", "usage", "error_code", "limit_detail", "nudges"):
        assert getattr(broken, attr) == getattr(baseline, attr)
    assert len(broken.steps) == len(baseline.steps) and broken.observer_errors == 0
    assert recorder.errors >= 4 and recorder.last_error == "RuntimeError"
    assert SECRET not in repr(recorder.last_error) and SECRET not in repr(vars(recorder).get("last_error"))
    assert len(store.calls) >= 4  # every write was still attempted


def test_the_totals_still_match_what_was_billed_when_writes_fail():
    result, ledger, recorder, store = go([tool_call_response(("echo", {}), **USAGE), text_response("done", **USAGE)], store=FakeStore(fail=True))
    finish = store.finish()
    assert finish.cost_usd == ledger.total_usd
    assert finish.observer_errors == 3 and recorder.errors == 4  # the finish write itself failed after the count was taken


def test_a_flaky_store_loses_only_the_failed_writes():
    class Flaky(FakeStore):
        def record_tool_call(self, job, step, call):
            raise RuntimeError("down")

    result, _, recorder, store = go([tool_call_response(("echo", {}), **USAGE), text_response("done", **USAGE)], store=Flaky())
    assert recorder.errors == 1 and store.names() == ["record_model_calls", "record_model_calls", "finish_job"] and result.finished


def test_abort_marks_the_job_and_absorbs_failures():
    store = FakeStore()
    recorder = TraceRecorder(store, JOB, CostLedger(), scrub=lambda t: t.replace(SECRET, "[key]"))
    recorder.abort(f"crashed: {SECRET}")
    assert store.calls == [("abort_job", (JOB, "crashed: [key]"))]
    dead = TraceRecorder(FakeStore(fail=True), JOB, CostLedger())
    dead.abort("x")
    assert dead.errors == 1
