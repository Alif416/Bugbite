"""Record a scripted run through the real chain, replay it, and expect the same result (README FR10.2, FR10.5)."""

import pytest
from loop_helpers import Clock
from rp_helpers import (
    USAGE, AdapterError, FakeTools, Limits, Sensitivity, ToolOutput, Usage, record, replay_it, text_response, tool_call_response,
)

from bugbite.agent import (
    COST_CAP, FINISHED, LOOP_DETECTED, MAX_STEPS, MODEL_ERROR, PRIVACY_BLOCKED, TIME_CAP, LoopPolicy,
)


def again(count, text="again"):
    """`count` replies that all make the same tool call (each with its own call id, as a real model's would have)."""
    return [tool_call_response(("echo", {"text": text}), first_id=i, **USAGE) for i in range(1, count + 1)]


def assert_same(recorded, path, **kw):
    result = replay_it(path, **kw)
    assert result.divergence is None and result.differences == () and result.identical, (result.divergence, result.differences)
    assert result.agent.status == recorded.status and result.agent.final_text == recorded.final_text
    assert result.agent.cost_usd == recorded.cost_usd and result.agent.usage == recorded.usage
    assert result.agent.steps == recorded.steps or [s.response for s in result.agent.steps] == [s.response for s in recorded.steps]
    assert result.agent.nudges == recorded.nudges and result.agent.error_code == recorded.error_code
    return result


def test_a_finished_run_with_tools_replays_identically(tmp_path, provider):
    tools = FakeTools(outputs={"echo": ToolOutput("echoed")})
    script = [tool_call_response(("echo", {"text": "hi"}), text="looking", **USAGE), text_response("Fixed.", **USAGE)]
    recorded, path = record(tmp_path, provider, script, tools=tools)
    result = assert_same(recorded, path)
    assert recorded.status == FINISHED and [e["type"] for e in result.events] == ["model_call", "step", "tool_call", "model_call", "step", "finish"]
    assert result.notes == ()


def test_a_run_that_ended_in_a_model_error_replays_identically(tmp_path, provider):
    recorded, path = record(tmp_path, provider, [AdapterError("server_error", "the provider broke", status_code=500)])
    result = assert_same(recorded, path)
    assert recorded.status == MODEL_ERROR and result.agent.error_message == "the provider broke"


def test_an_immediate_answer_replays_identically(tmp_path, provider):
    recorded, path = record(tmp_path, provider, [text_response("Nothing to change.", **USAGE)])
    assert_same(recorded, path)


def test_a_text_action_model_with_a_repair_replays_identically(tmp_path, provider):
    script = [text_response("this is not an action", **USAGE), text_response('{"tool": "echo", "arguments": {"text": "x"}}', **USAGE),
              text_response('{"final": "done"}', **USAGE)]
    recorded, path = record(tmp_path, provider, script, native=False)
    result = assert_same(recorded, path)
    assert recorded.final_text == "done" and sum(e["type"] == "model_call" for e in result.events) == 3  # the repair is its own provider call


def test_loop_detection_nudges_and_stops_the_same_way(tmp_path, provider):
    recorded, path = record(tmp_path, provider, again(5), tools=FakeTools(outputs={"echo": ToolOutput("same result")}))
    result = assert_same(recorded, path)
    assert recorded.status == LOOP_DETECTED and recorded.nudges == 1 and result.agent.limit_detail == recorded.limit_detail


def test_a_privacy_refusal_is_enforced_again_from_the_manifest(tmp_path, provider):
    recorded, path = record(tmp_path, provider, [], allow=False, sensitivity=Sensitivity.PRIVATE)
    result = assert_same(recorded, path)
    assert recorded.status == PRIVACY_BLOCKED and result.events[-1]["type"] == "finish" and not any(e["type"] == "model_call" for e in result.events)


def test_max_steps_replays_identically(tmp_path, provider):
    script = [tool_call_response(("echo", {"text": "a"}), **USAGE), tool_call_response(("echo", {"text": "b"}), **USAGE)]
    recorded, path = record(tmp_path, provider, script, limits=Limits(2))
    assert recorded.status == MAX_STEPS
    assert_same(recorded, path)


@pytest.mark.parametrize("cap, usage, expected_calls", [("500", Usage(1_000_000, 0), 1), ("0.5", Usage(1, 1), 0)])
def test_cost_caps_replay_identically(tmp_path, provider, cap, usage, expected_calls):
    """The first case is passed by the estimate and broken by the real usage; the second is stopped before any call."""
    recorded, path = record(tmp_path, provider, [tool_call_response(("echo", {"text": "a"}), usage=usage)], limits=Limits(5, max_cost_usd=cap))
    result = assert_same(recorded, path)
    assert recorded.status == COST_CAP and sum(e["type"] == "model_call" for e in result.events) == expected_calls


class SlowTools(FakeTools):
    """Each run takes `seconds` on a shared clock."""

    def __init__(self, clock, seconds, **kw):
        super().__init__(**kw)
        self.clock, self.seconds = clock, seconds

    def execute(self, name, arguments, *, time_limit_s=None):
        self.clock.advance(self.seconds)
        return super().execute(name, arguments, time_limit_s=time_limit_s)


def test_a_time_cap_replays_as_a_time_cap_on_the_virtual_clock(tmp_path, provider):
    clock = Clock()
    script = [tool_call_response(("echo", {"text": "a"}), **USAGE), tool_call_response(("echo", {"text": "b"}), **USAGE)]
    recorded, path = record(tmp_path, provider, script, tools=SlowTools(clock, 10), limits=Limits(10, max_wall_clock_s=5), clock=clock, monotonic=clock)
    assert recorded.status == TIME_CAP
    result = assert_same(recorded, path)
    assert result.agent.elapsed_s == recorded.elapsed_s == 10  # the replay waited for nothing and measured the recorded time


def test_a_call_skipped_for_time_is_skipped_again(tmp_path, provider):
    clock = Clock()
    script = [tool_call_response(("echo", {"text": "a"}), ("echo", {"text": "b"}), **USAGE)]
    recorded, path = record(tmp_path, provider, script, tools=SlowTools(clock, 10), limits=Limits(10, max_wall_clock_s=5), clock=clock, monotonic=clock)
    assert [r.executed for r in recorded.steps[0].tool_runs] == [True, False]
    result = assert_same(recorded, path)
    assert [r.executed for r in result.agent.steps[0].tool_runs] == [True, False]


def test_a_native_run_with_a_failed_first_attempt_ends_the_same_way(tmp_path, provider):
    """Without a retry layer the error reaches the loop; recordings that used one are refused (see test_replay_refusals)."""
    recorded, path = record(tmp_path, provider, [AdapterError("rate_limited", "slow down", retry_after_s=3, status_code=429), text_response("never reached")])
    result = assert_same(recorded, path)
    assert recorded.status == MODEL_ERROR and result.agent.error_code == "rate_limited"
    assert result.divergence is None


def test_a_loop_policy_none_in_the_manifest_is_respected(tmp_path, provider):
    recorded, path = record(tmp_path, provider, again(6) + [text_response("done", **USAGE)], limits=Limits(10), loop_policy=None)
    assert recorded.status == FINISHED and recorded.nudges == 0
    assert_same(recorded, path)


def test_a_custom_recorded_loop_policy_is_used(tmp_path, provider):
    policy = LoopPolicy(repeat_nudge=2, repeat_stop=3)
    recorded, path = record(tmp_path, provider, again(4), loop_policy=policy)
    assert recorded.status == LOOP_DETECTED and len(recorded.steps) == 3
    assert_same(recorded, path)


def test_a_run_setting_that_is_on_every_request_is_taken_from_the_recording(tmp_path, provider):
    """The output-token limit is a setting of the run, not of the code, and is not in the manifest: replay reads it from the first request."""
    script = [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)]
    recorded, path = record(tmp_path, provider, script, max_output_tokens=50)
    result = assert_same(recorded, path)
    assert result.identical
