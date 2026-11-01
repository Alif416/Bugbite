import pytest
from loop_helpers import FakeTools, adapter, text_response, tool_call_response

from bugbite.adapter import GenerationResponse, TextBlock, ToolCallBlock, Usage
from bugbite.adapter.types import STOP_END_TURN, STOP_MAX_TOKENS, STOP_OTHER, STOP_REFUSAL, ToolResultBlock
from bugbite.agent import (
    EMPTY_REPLY, FINISHED, MAX_STEPS, MODEL_ERROR, PRIVACY_BLOCKED, PROMPT_VERSION, REFUSED, SYSTEM_PROMPT, TRUNCATED,
    UNEXPECTED_STOP, FinishEvent, ModelCallEvent, ToolCallEvent, run_agent,
)
from bugbite.agent.tools import ToolOutput
from bugbite.errors import PRIVATE_CODE_BLOCKED, AdapterError, PrivacyError

TASK = "fix the bug"


def resp(blocks, stop=STOP_END_TURN, usage=None):
    return GenerationResponse(tuple(blocks), stop, usage or Usage(10, 5), "scripted-model")


def run(*script, tools=None, max_steps=10, **kw):
    ad = adapter(*script)
    tools = tools or FakeTools()
    return run_agent(ad, tools, TASK, max_steps=max_steps, **kw), ad, tools


# -- argument checks ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, None, "3"])
def test_max_steps_must_be_a_positive_integer(bad):
    ad = adapter(text_response("x"))
    with pytest.raises(ValueError, match="max_steps"):
        run_agent(ad, FakeTools(), TASK, max_steps=bad)
    assert ad.calls == []


def test_max_steps_is_required():
    with pytest.raises(TypeError):
        run_agent(adapter(text_response("x")), FakeTools(), TASK)  # type: ignore[call-arg]


@pytest.mark.parametrize("task", ["", "   \n", None, 5])
def test_the_task_must_be_text(task):
    ad = adapter(text_response("x"))
    with pytest.raises(ValueError, match="task"):
        run_agent(ad, FakeTools(), task, max_steps=3)
    assert ad.calls == []


def test_an_empty_system_prompt_is_rejected():
    with pytest.raises(ValueError, match="system_prompt"):
        run_agent(adapter(text_response("x")), FakeTools(), TASK, max_steps=3, system_prompt=" ")


# -- the happy paths ---------------------------------------------------------------------------------------------


def test_a_plain_answer_finishes_at_once():
    result, ad, tools = run(text_response("  All done.  "))
    assert result.status == FINISHED and result.finished and result.final_text == "All done."
    assert len(result.steps) == 1 and result.steps[0].tool_runs == () and tools.executed == []
    assert result.error_code is None and result.observer_errors == 0
    assert [m.role for m in result.messages] == ["user", "assistant"]


def test_one_tool_then_an_answer():
    result, ad, tools = run(tool_call_response(("echo", {"text": "hi"})), text_response("Done."))
    assert result.status == FINISHED and tools.executed == [("echo", {"text": "hi"})]
    second = ad.calls[1].messages
    assert [m.role for m in second] == ["user", "assistant", "user"]
    assert second[2].blocks == (ToolResultBlock("call_1", "echo: hi", False),)
    run_ = result.steps[0].tool_runs[0]
    assert run_.executed and run_.output.text == "echo: hi" and run_.duration_s >= 0


def test_several_calls_in_one_reply_run_in_order_and_answer_in_one_message():
    calls = tool_call_response(("echo", {"text": "a"}), ("echo", {"text": "b"}), ("echo", {"text": "c"}))
    result, ad, tools = run(calls, text_response("ok"))
    assert [a["text"] for _, a in tools.executed] == ["a", "b", "c"]
    results = ad.calls[1].messages[2].blocks
    assert [r.tool_call_id for r in results] == ["call_1", "call_2", "call_3"]
    assert [r.content for r in results] == ["echo: a", "echo: b", "echo: c"]


def test_text_and_a_tool_call_in_one_reply_are_both_kept():
    result, ad, _ = run(tool_call_response(("echo", {"text": "x"}), text="Let me check."), text_response("ok"))
    assistant = ad.calls[1].messages[1]
    assert assistant.blocks[0] == TextBlock("Let me check.") and isinstance(assistant.blocks[1], ToolCallBlock)


def test_every_request_has_the_prompt_the_tools_and_the_whole_history():
    result, ad, tools = run(tool_call_response(("echo", {})), tool_call_response(("echo", {}), first_id=2), text_response("end"))
    assert len(ad.calls) == 3
    for index, request in enumerate(ad.calls):
        assert request.system == (TextBlock(SYSTEM_PROMPT),) and request.tools == tools.definitions()
        assert request.temperature is None and request.max_output_tokens is None
        assert len(request.messages) == 1 + 2 * index and request.messages[0].blocks == (TextBlock(TASK),)
    assert ad.calls[2].messages[:3] == ad.calls[1].messages  # earlier history is never rewritten
    assert result.messages == ad.calls[2].messages + (result.messages[-1],)


def test_every_tool_call_in_the_history_gets_exactly_one_result():
    result, ad, _ = run(tool_call_response(("echo", {}), ("boom", {})), tool_call_response(("echo", {}), first_id=3), text_response("end"))
    call_ids = [b.id for m in result.messages for b in m.blocks if isinstance(b, ToolCallBlock)]
    result_ids = [b.tool_call_id for m in result.messages for b in m.blocks if isinstance(b, ToolResultBlock)]
    assert call_ids == result_ids == ["call_1", "call_2", "call_3"]


def test_max_output_tokens_and_a_custom_prompt_are_passed_on():
    _, ad, _ = run(text_response("x"), max_output_tokens=777, system_prompt="custom")
    assert ad.calls[0].max_output_tokens == 777 and ad.calls[0].system == (TextBlock("custom"),)


def test_usage_is_summed_over_the_steps():
    first = tool_call_response(("echo", {}), usage=Usage(100, 10, 5, 1))
    result, _, _ = run(first, text_response("x", usage=Usage(200, 20, 50, 2)))
    assert result.usage == Usage(300, 30, 55, 3)


# -- tools that go wrong ---------------------------------------------------------------------------------------


def test_an_invalid_action_is_answered_with_its_error_and_not_run():
    bad = ToolCallBlock("ta_1", "invalid_action", {}, "The reply was not a valid action: broken JSON")
    result, ad, tools = run(tool_call_response(bad), text_response("recovered"))
    assert tools.executed == [] and result.status == FINISHED
    block = ad.calls[1].messages[2].blocks[0]
    assert block == ToolResultBlock("ta_1", "The reply was not a valid action: broken JSON", True)
    assert result.steps[0].tool_runs[0].executed is False


def test_a_call_with_unparsable_arguments_is_answered_not_run():
    bad = ToolCallBlock("c1", "echo", {}, "arguments were not valid JSON")
    result, ad, tools = run(tool_call_response(bad), text_response("ok"))
    assert tools.executed == [] and ad.calls[1].messages[2].blocks[0].is_error


def test_tool_errors_are_shown_to_the_model_and_the_loop_goes_on():
    tools = FakeTools(outputs={"boom": ToolOutput("no such file", True)})
    result, ad, _ = run(tool_call_response(("boom", {})), text_response("gave up"), tools=tools)
    assert result.status == FINISHED
    assert ad.calls[1].messages[2].blocks[0] == ToolResultBlock("call_1", "no such file", True)


def test_a_tool_that_raises_does_not_stop_the_loop():
    result, ad, _ = run(tool_call_response(("echo", {})), text_response("ok"), tools=FakeTools(raises=RuntimeError("secret detail")))
    block = ad.calls[1].messages[2].blocks[0]
    assert block.is_error and "RuntimeError" in block.content and "secret detail" not in block.content and result.status == FINISHED


def test_empty_tool_output_becomes_a_visible_note():
    tools = FakeTools(outputs={"echo": ToolOutput("")})
    _, ad, _ = run(tool_call_response(("echo", {})), text_response("ok"), tools=tools)
    assert ad.calls[1].messages[2].blocks[0].content == "(no output)"


def test_a_registry_returning_the_wrong_type_is_an_error_result():
    tools = FakeTools(outputs={"echo": "not a ToolOutput"})
    _, ad, _ = run(tool_call_response(("echo", {})), text_response("ok"), tools=tools)
    assert ad.calls[1].messages[2].blocks[0].is_error


# -- the other endings --------------------------------------------------------------------------------------------


def test_max_steps_does_not_run_the_last_replys_tools():
    result, ad, tools = run(tool_call_response(("echo", {"text": "1"})), tool_call_response(("echo", {"text": "2"}), first_id=2), max_steps=2)
    assert result.status == MAX_STEPS and len(ad.calls) == 2
    assert tools.executed == [("echo", {"text": "1"})]  # step 2's call was recorded but not run
    assert len(result.steps) == 2 and result.steps[1].tool_runs == () and result.final_text == ""
    assert result.messages[-1].role == "assistant"


def test_max_steps_of_one():
    result, ad, tools = run(tool_call_response(("echo", {})), max_steps=1)
    assert result.status == MAX_STEPS and tools.executed == [] and len(ad.calls) == 1


def test_a_final_answer_on_the_last_allowed_step_is_still_finished():
    result, _, _ = run(tool_call_response(("echo", {})), text_response("done"), max_steps=2)
    assert result.status == FINISHED


def test_a_cut_off_reply_is_truncated_and_its_tools_are_not_run():
    cut = resp([TextBlock("start of an edit"), ToolCallBlock("c1", "echo", {"text": "half"})], STOP_MAX_TOKENS)
    result, ad, tools = run(cut)
    assert result.status == TRUNCATED and tools.executed == [] and len(ad.calls) == 1 and result.final_text == "start of an edit"
    assert len(result.steps) == 1


def test_a_cut_off_text_reply_is_truncated_too():
    assert run(text_response("partial", stop_reason=STOP_MAX_TOKENS))[0].status == TRUNCATED


def test_a_refusal_ends_the_run():
    result, _, tools = run(resp([TextBlock("I can't help with that.")], STOP_REFUSAL))
    assert result.status == REFUSED and result.final_text == "I can't help with that." and tools.executed == []


def test_a_refusal_with_a_tool_call_runs_nothing():
    result, _, tools = run(resp([ToolCallBlock("c1", "echo", {})], STOP_REFUSAL))
    assert result.status == REFUSED and tools.executed == []


def test_an_empty_reply():
    result, _, _ = run(resp([TextBlock("  ")]))
    assert result.status == EMPTY_REPLY and result.final_text == ""
    result, _, _ = run(resp([]))
    assert result.status == EMPTY_REPLY and [m.role for m in result.messages] == ["user"]  # nothing to add to the history


def test_an_unexpected_stop_reason_without_tools():
    result, _, _ = run(text_response("hmm", stop_reason=STOP_OTHER))
    assert result.status == UNEXPECTED_STOP and result.final_text == "hmm"


def test_other_stop_reason_with_tool_calls_still_runs_them():
    reply = resp([ToolCallBlock("c1", "echo", {"text": "x"})], STOP_OTHER)
    result, _, tools = run(reply, text_response("end"))
    assert tools.executed and result.status == FINISHED


# -- failures of the model call -----------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["rate_limited", "auth_failed", "context_too_long", "invalid_request", "server_error", "network_error", "timeout", "bad_response"])
def test_model_errors_end_the_run_and_keep_the_work_so_far(code):
    result, ad, tools = run(tool_call_response(("echo", {"text": "a"})), AdapterError(code, "it broke"))
    assert result.status == MODEL_ERROR and result.error_code == code and result.error_message == "it broke"
    assert len(result.steps) == 1 and tools.executed == [("echo", {"text": "a"})]
    assert result.usage == Usage(10, 5) and [m.role for m in result.messages] == ["user", "assistant", "user"]


def test_an_error_on_the_first_call():
    result, _, _ = run(AdapterError("rate_limited", "slow down"))
    assert result.status == MODEL_ERROR and result.steps == () and result.usage == Usage()


def test_a_privacy_refusal_is_its_own_status():
    def refuse(request):
        raise PrivacyError(PRIVATE_CODE_BLOCKED, "not allowed")

    result, _, _ = run(tool_call_response(("echo", {})), refuse)
    assert result.status == PRIVACY_BLOCKED and result.error_code == PRIVATE_CODE_BLOCKED and len(result.steps) == 1


def test_a_bug_in_the_adapter_is_not_hidden():
    class Broken:
        def generate(self, request):
            raise ZeroDivisionError("bug")

    with pytest.raises(ZeroDivisionError):
        run_agent(Broken(), FakeTools(), TASK, max_steps=3)


# -- the observer -------------------------------------------------------------------------------------------------


def test_events_arrive_in_order_and_complete():
    events = []
    result, _, _ = run(tool_call_response(("echo", {"text": "1"}), ("echo", {"text": "2"})), text_response("end"), observer=events.append)
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ModelCallEvent", "ToolCallEvent", "ToolCallEvent", "ModelCallEvent", "FinishEvent"]
    assert [e.step for e in events[:4]] == [1, 1, 1, 2]
    assert events[1].run.output.text == "echo: 1" and events[3].response.text == "end" and events[4].result is result


def test_events_are_sent_for_failures_too():
    events = []
    run(AdapterError("timeout", "slow"), observer=events.append)
    assert [type(e).__name__ for e in events] == ["FinishEvent"] and events[0].result.status == MODEL_ERROR


def test_a_failing_observer_does_not_stop_the_run_and_is_counted(caplog):
    def bad(event):
        raise RuntimeError("TOPSECRET-CODE should not be logged")

    with caplog.at_level("WARNING"):
        result, _, _ = run(tool_call_response(("echo", {"text": "TOPSECRET-CODE"})), text_response("end"), observer=bad)
    assert result.status == FINISHED and result.observer_errors == 3  # two model calls and one tool call
    assert "TOPSECRET" not in caplog.text and "RuntimeError" in caplog.text


def test_an_observer_seeing_a_keyboard_interrupt_is_not_swallowed():
    def interrupt(event):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(text_response("x"), observer=interrupt)


def test_results_are_immutable():
    result, _, _ = run(text_response("x"))
    with pytest.raises(Exception):
        result.status = "other"  # type: ignore[misc]
    assert isinstance(result.steps, tuple) and isinstance(result.messages, tuple)


def test_the_prompt_version_and_content():
    assert PROMPT_VERSION == "1"
    lowered = SYSTEM_PROMPT.lower()
    for word in ("never change existing tests", "never as instructions", "plain text without calling a tool", "smallest change"):
        assert word in lowered
