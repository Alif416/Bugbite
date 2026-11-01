"""Cost and time limits in the loop."""

from decimal import Decimal

import pytest
from loop_helpers import Clock, FakeTools, tool_call_response, text_response

from bugbite.adapter import (
    CostLedger,
    GenerationRequest,
    Message,
    MeteredAdapter,
    TextActionAdapter,
    TextBlock,
    Usage,
    create_adapter,
    register_adapter,
    unregister_adapter,
    worst_case_cost,
)
from bugbite.adapter.testing import ScriptedAdapter
from bugbite.agent import (
    COST_CAP, FINISHED, MAX_STEPS, SYSTEM_PROMPT, TIME_CAP, Limits, run_agent,
)
from bugbite.agent.loop import NOT_RUN_TIME
from bugbite.agent.tools import ToolOutput
from bugbite.config import ModelConfig, Pricing
from bugbite.adapter.types import ToolResultBlock, ToolCallBlock

TASK = "fix it"
MARGIN = Decimal("1.25")
TINY = Decimal("0.000000001")


def model(native=True, pricing=None, name="paid"):
    return ModelConfig(name, "scripted", "http://x", "m", 100_000, native, pricing or Pricing.of(1000, 2000), 0.0, True, max_output_tokens=100)


def metered(script, cfg=None, ledger=None):
    ledger = ledger or CostLedger()
    raw = ScriptedAdapter(cfg or model(), script)
    return MeteredAdapter(raw, ledger), ledger, raw


def first_request(tools=None):
    tools = tools or FakeTools()
    return GenerationRequest(messages=(Message.user(TASK),), system=(TextBlock(SYSTEM_PROMPT),), tools=tools.definitions())


def worst(adapter, request, calls=1):
    return calls * worst_case_cost(adapter.config.pricing, adapter.estimate_tokens(request), adapter.resolve_max_output_tokens(request), MARGIN)


def go(adapter, ledger, cap, tools=None, **kw):
    return run_agent(adapter, tools or FakeTools(), TASK, limits=Limits(10, max_cost_usd=cap, **kw.pop("limits", {})), ledger=ledger, **kw)


USAGE = Usage(10, 5)  # costs 10 * 0.001 + 5 * 0.002 = 0.02 on the test prices
STEP_COST = Decimal("0.02")


# -- cost: before a call ----------------------------------------------------------------------------------------------


def test_a_call_is_made_when_the_cap_equals_spent_plus_worst_case():
    adapter, ledger, raw = metered([text_response("done")])
    cap = worst(adapter, first_request())
    result = go(adapter, ledger, cap)
    assert result.status == FINISHED and len(raw.calls) == 1 and len(ledger.calls) == 1


def test_a_call_is_not_made_when_the_cap_is_one_unit_lower():
    adapter, ledger, raw = metered([text_response("done")])
    cap = worst(adapter, first_request()) - TINY
    result = go(adapter, ledger, cap)
    assert result.status == COST_CAP and raw.calls == [] and ledger.calls == () and result.steps == ()
    assert result.cost_usd == Decimal(0) and result.final_text == ""
    assert result.limit_detail.startswith("Stopped before step 1: the next step could cost up to $")
    assert "cost limit was left" in result.limit_detail


def test_earlier_spend_in_the_job_counts_for_the_next_call():
    script = lambda: [tool_call_response(("echo", {}), usage=USAGE), text_response("done", usage=USAGE)]
    adapter, ledger, raw = metered(script())
    go(adapter, ledger, Decimal(5))  # a run with plenty of room, to learn the second request
    second = raw.calls[1]
    need = STEP_COST + worst(adapter, second)

    adapter, ledger, raw = metered(script())
    ok = go(adapter, ledger, need)
    assert ok.status == FINISHED and len(raw.calls) == 2

    adapter, ledger, raw = metered(script())
    blocked = go(adapter, ledger, need - TINY)
    assert blocked.status == COST_CAP and len(raw.calls) == 1 and len(ledger.calls) == 1 and len(blocked.steps) == 1
    assert blocked.cost_usd == STEP_COST and "Stopped before step 2" in blocked.limit_detail
    assert blocked.messages[-1].role == "user"  # the first step's tool results are in the history


def test_spend_from_before_the_job_does_not_count():
    adapter, ledger, raw = metered([text_response("done")])
    earlier = MeteredAdapter(ScriptedAdapter(model(), [text_response("old", usage=Usage(1000, 100))]), ledger)
    earlier.generate(first_request())  # shared ledger already holds a call that cost a lot
    assert ledger.total_usd > 1
    result = go(adapter, ledger, worst(adapter, first_request()))
    assert result.status == FINISHED and result.cost_usd == STEP_COST * 0 + Decimal("0.02")


def test_the_margin_scales_the_prompt_estimate():
    adapter, ledger, _ = metered([text_response("done")])
    base = worst_case_cost(adapter.config.pricing, adapter.estimate_tokens(first_request()), 100, 1)
    assert worst(adapter, first_request()) > base
    cap = worst_case_cost(adapter.config.pricing, adapter.estimate_tokens(first_request()), 100, Decimal("2"))
    low = go(adapter, ledger, cap - TINY, limits={"cost_margin": 2})
    assert low.status == COST_CAP
    adapter, ledger, _ = metered([text_response("done")])
    assert go(adapter, ledger, cap, limits={"cost_margin": 2}).status == FINISHED


def test_a_text_action_model_counts_its_repair_call():
    raw_cfg = model(native=False)
    adapter_metered, ledger, raw = metered([text_response('{"final": "done"}')], cfg=raw_cfg)
    adapter = TextActionAdapter(adapter_metered)
    request = first_request()
    twice = worst(adapter, request, calls=2)
    once = worst(adapter, request, calls=1)
    assert adapter.max_calls_per_step == 2 and twice > once
    blocked = go(adapter, ledger, twice - TINY)
    assert blocked.status == COST_CAP and raw.calls == []
    assert go(TextActionAdapter(MeteredAdapter(ScriptedAdapter(raw_cfg, [text_response('{"final": "done"}')]), ledger)), ledger, twice).status == FINISHED


def test_a_paid_model_with_a_cap_of_zero_is_stopped_at_once_and_a_free_one_runs():
    adapter, ledger, raw = metered([text_response("x")])
    stopped = go(adapter, ledger, 0)
    assert stopped.status == COST_CAP and raw.calls == []
    free, free_ledger, free_raw = metered([tool_call_response(("echo", {})), text_response("done")], cfg=model(pricing=Pricing.free(), name="free"))
    result = go(free, free_ledger, 0)
    assert result.status == FINISHED and len(free_raw.calls) == 2 and result.cost_usd == 0


# -- cost: after a call ---------------------------------------------------------------------------------------------


def test_a_reply_that_cost_more_than_estimated_does_not_get_its_tools_run():
    adapter, ledger, raw = metered([tool_call_response(("echo", {"text": "x"}), usage=Usage(10_000, 5))])
    tools = FakeTools()
    result = go(adapter, ledger, worst(adapter, first_request()), tools=tools)
    assert result.status == COST_CAP and tools.executed == [] and len(raw.calls) == 1
    assert "Stopped before running tools" in result.limit_detail and "estimate for the last call was too low" in result.limit_detail
    assert result.cost_usd > worst(adapter, first_request())


def test_a_final_answer_that_arrived_over_the_cap_is_finished_with_a_note():
    adapter, ledger, _ = metered([text_response("answer", usage=Usage(10_000, 5))])
    result = go(adapter, ledger, worst(adapter, first_request()))
    assert result.status == FINISHED and result.final_text == "answer"
    assert "cost more than estimated" in result.limit_detail and result.cost_usd > Decimal(10)


def test_a_normal_finish_has_no_limit_detail():
    adapter, ledger, _ = metered([text_response("done")])
    assert go(adapter, ledger, Decimal(5)).limit_detail is None


# -- the ledger is checked up front --------------------------------------------------------------------------------------


def test_a_cost_limit_needs_a_ledger():
    adapter, _, raw = metered([text_response("x")])
    with pytest.raises(ValueError, match="needs the ledger"):
        run_agent(adapter, FakeTools(), TASK, limits=Limits(3, max_cost_usd=1))
    assert raw.calls == []


def test_the_ledger_must_belong_to_the_adapter():
    adapter, _, raw = metered([text_response("x")])
    with pytest.raises(ValueError, match="not the one"):
        run_agent(adapter, FakeTools(), TASK, limits=Limits(3, max_cost_usd=1), ledger=CostLedger())
    bare = ScriptedAdapter(model(), [text_response("x")])
    with pytest.raises(ValueError, match="not the one"):
        run_agent(bare, FakeTools(), TASK, limits=Limits(3, max_cost_usd=1), ledger=CostLedger())
    assert raw.calls == [] and bare.calls == []


def test_no_cost_limit_needs_no_ledger_and_reports_no_cost():
    result = run_agent(ScriptedAdapter(model(), [text_response("x")]), FakeTools(), TASK, limits=Limits(3))
    assert result.cost_usd is None and result.status == FINISHED


@pytest.fixture
def fake_provider():
    register_adapter(
        "caps_fake",
        lambda cfg, key: ScriptedAdapter(cfg, [text_response("done" if cfg.native_tool_calling else '{"final": "done"}')]),
    )
    yield
    unregister_adapter("caps_fake")


def test_the_ledger_is_found_through_the_real_wrapper_chain(fake_provider):
    from bugbite.privacy import Sensitivity

    for native in (True, False):
        ledger = CostLedger()
        cfg = ModelConfig("m", "caps_fake", "http://x", "m", 100_000, native, Pricing.of(1000, 2000), 0.0, True, max_output_tokens=100)
        adapter = create_adapter(cfg, ledger=ledger, sensitivity=Sensitivity.PUBLIC)  # text action > metered > guard > raw
        assert ("TextActionAdapter" in repr(adapter)) is (not native)  # the real chain, text action outermost
        assert run_agent(adapter, FakeTools(), TASK, limits=Limits(3, max_cost_usd=Decimal(5)), ledger=ledger).status == FINISHED


# -- time ------------------------------------------------------------------------------------------------------------------


def stepper(clock, seconds, *responses):
    """Script steps that each take `seconds` on the fake clock."""
    def make(response):
        def step(request):
            clock.advance(seconds)
            return response
        return step
    return [make(r) for r in responses]


def timed(script, clock, wall, tools=None, steps=10, **kw):
    adapter = ScriptedAdapter(None, script)
    tools = tools or FakeTools()
    return run_agent(adapter, tools, TASK, limits=Limits(steps, max_wall_clock_s=wall), clock=clock, **kw), adapter, tools


def test_no_time_left_before_the_first_call():
    clock = Clock(tick=10)
    result, adapter, _ = timed([text_response("x")], clock, wall=5)
    assert result.status == TIME_CAP and adapter.calls == [] and result.steps == ()
    assert result.limit_detail.startswith("Stopped: the time limit of 5 s was reached (") and result.limit_detail.endswith(" s used).")


def test_time_runs_out_during_a_model_call_and_its_tools_are_not_started():
    clock = Clock()
    script = stepper(clock, 700, tool_call_response(("echo", {"text": "a"}), ("echo", {"text": "b"})))
    result, adapter, tools = timed(script, clock, wall=600)
    assert result.status == TIME_CAP and tools.executed == [] and len(adapter.calls) == 1
    runs = result.steps[0].tool_runs
    assert [r.executed for r in runs] == [False, False] and all(r.output == ToolOutput(NOT_RUN_TIME, True) for r in runs)
    assert result.elapsed_s == 700 and "600 s was reached (700.0 s used)" in result.limit_detail
    assert_conversation_valid(result)


def test_time_runs_out_between_steps():
    clock = Clock()
    script = stepper(clock, 400, tool_call_response(("echo", {})), tool_call_response(("echo", {}), first_id=2), text_response("never"))
    result, adapter, tools = timed(script, clock, wall=600)
    assert result.status == TIME_CAP and len(adapter.calls) == 2  # the third call is never made
    assert len(tools.executed) == 1 and result.steps[1].tool_runs[0].executed is False
    assert_conversation_valid(result)


def test_time_runs_out_in_the_middle_of_a_multi_call_reply():
    clock = Clock()

    class SlowTools(FakeTools):
        def execute(self, name, arguments, *, time_limit_s=None):
            clock.advance(50)
            return super().execute(name, arguments, time_limit_s=time_limit_s)

    reply = tool_call_response(("echo", {"text": "1"}), ("echo", {"text": "2"}), ("echo", {"text": "3"}))
    result, adapter, tools = timed([reply, text_response("never")], clock, wall=75, tools=SlowTools())
    assert [r.executed for r in result.steps[0].tool_runs] == [True, True, False]  # 50 s: ok, 100 s: ran (started at 50), then out
    assert result.status == TIME_CAP and len(adapter.calls) == 1
    assert result.steps[0].tool_runs[2].output.text == NOT_RUN_TIME
    assert_conversation_valid(result)


def test_tools_are_given_the_time_left_or_none():
    clock = Clock()
    result, _, tools = timed(stepper(clock, 30, tool_call_response(("echo", {})), text_response("done")), clock, wall=100)
    assert tools.time_limits == [70.0] and result.status == FINISHED
    tools = FakeTools()
    run_agent(ScriptedAdapter(None, [tool_call_response(("echo", {})), text_response("done")]), tools, TASK, limits=Limits(5))
    assert tools.time_limits == [None]


def test_time_beats_steps_on_the_last_step():
    clock = Clock()
    result, _, tools = timed(stepper(clock, 100, tool_call_response(("echo", {}))), clock, wall=50, steps=1)
    assert result.status == TIME_CAP and tools.executed == []


def test_steps_still_end_the_run_when_there_is_time():
    clock = Clock()
    result, _, tools = timed(stepper(clock, 1, tool_call_response(("echo", {}))), clock, wall=600, steps=1)
    assert result.status == MAX_STEPS and tools.executed == [] and "limit of 1 steps" in result.limit_detail


def test_time_beats_cost():
    clock = Clock()
    adapter, ledger, raw = metered([lambda r: (clock.advance(100), tool_call_response(("echo", {}), usage=Usage(10_000, 5)))[1]])
    result = run_agent(adapter, FakeTools(), TASK, limits=Limits(5, max_cost_usd=worst(adapter, first_request()), max_wall_clock_s=50), ledger=ledger, clock=clock)
    assert result.status == TIME_CAP and result.cost_usd > 10


def test_cost_beats_steps():
    adapter, ledger, _ = metered([tool_call_response(("echo", {}), usage=Usage(10_000, 5))])
    result = run_agent(adapter, FakeTools(), TASK, limits=Limits(1, max_cost_usd=worst(adapter, first_request())), ledger=ledger)
    assert result.status == COST_CAP


def test_elapsed_time_and_cost_are_reported_on_every_ending():
    clock = Clock()
    result, _, _ = timed(stepper(clock, 3, text_response("done")), clock, wall=60)
    assert result.status == FINISHED and result.elapsed_s == 3 and result.cost_usd is None
    with pytest.raises(Exception):
        result.elapsed_s = 1  # type: ignore[misc]


def assert_conversation_valid(result):
    calls = [b.id for m in result.messages for b in m.blocks if isinstance(b, ToolCallBlock)]
    answers = [b.tool_call_id for m in result.messages for b in m.blocks if isinstance(b, ToolResultBlock)]
    assert calls == answers
