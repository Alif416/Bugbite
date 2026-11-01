"""The wrapper end to end: success, repair, failure, accounting, and wiring."""

import json
from decimal import Decimal

import httpx
import pytest
from adapter_contract import AdapterContract
from claude_helpers import model as paid_model
from openai_helpers import adapter_for as openai_adapter_for
from openai_helpers import completion
from text_action_helpers import EDIT_FILE, READ_FILE, TOOLS, action, final

from bugbite.adapter import (
    ClaudeAdapter,
    CostLedger,
    GenerationRequest,
    GenerationResponse,
    Message,
    MeteredAdapter,
    TextActionAdapter,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    Usage,
    create_adapter,
)
from bugbite.adapter.testing import ScriptedAdapter, scripted_config, text_response
from bugbite.adapter.text_action import INVALID_ACTION, PROMPT_VERSION
from bugbite.config import load_models_config
from bugbite.errors import INVALID_REQUEST, RATE_LIMITED_MODEL, AdapterError

REQUEST = GenerationRequest(messages=(Message.user("Fix it."),), tools=TOOLS)


def reply(text, usage=Usage(100, 20), latency=0.5, request_id="req", stop="end_turn", estimated=False, model="m"):
    return GenerationResponse(
        blocks=(TextBlock(text),) if text else (), stop_reason=stop, usage=usage, model=model,
        raw_stop_reason=stop, latency_s=latency, request_id=request_id, usage_estimated=estimated,
    )  # fmt: skip


def wrapper(script):
    inner = ScriptedAdapter(scripted_config("local"), script)
    return TextActionAdapter(inner), inner


# -- a valid action first time -----------------------------------------------------------------------------------


def test_a_valid_tool_action_becomes_a_tool_call_with_one_model_call():
    adapter, inner = wrapper([reply(action("read_file", path="a.py"))])
    response = adapter.generate(REQUEST)
    (call,) = response.tool_calls
    assert (call.id, call.name, call.arguments, call.error) == ("ta_1", "read_file", {"path": "a.py"}, None)
    assert response.stop_reason == "tool_use" and len(inner.calls) == 1
    assert adapter.stats.steps == 1 and adapter.stats.repaired_steps == 0 and adapter.stats.failed_steps == 0


def test_the_model_never_sees_tools_but_does_see_the_instructions():
    adapter, inner = wrapper([reply(action("read_file", path="a.py"))])
    adapter.generate(REQUEST)
    sent = inner.calls[0]
    assert sent.tools == () and any(PROMPT_VERSION in b.text and "read_file" in b.text for b in sent.system)


def test_prose_around_the_action_is_kept_as_text_before_the_call():
    adapter, _ = wrapper([reply("I should look.\n" + action("read_file", path="a.py") + "\nThat will tell me.")])
    response = adapter.generate(REQUEST)
    assert [type(b).__name__ for b in response.blocks] == ["TextBlock", "ToolCallBlock"]
    assert response.text == "I should look.\n\nThat will tell me."


def test_a_final_answer_becomes_text_and_end_turn():
    adapter, _ = wrapper([reply(final("The bug is fixed."))])
    response = adapter.generate(REQUEST)
    assert response.text == "The bug is fixed." and response.tool_calls == () and response.stop_reason == "end_turn"


def test_a_final_answer_with_empty_text_falls_back_to_the_prose():
    adapter, _ = wrapper([reply("Summary of work.\n" + final(""))])
    assert adapter.generate(REQUEST).text == "Summary of work."


def test_call_ids_continue_from_the_calls_already_in_the_conversation():
    history = GenerationRequest(
        tools=TOOLS,
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("ta_1", "read_file", {"path": "a"})),
            Message.tool_results(ToolResultBlock("ta_1", "x")),
            Message.assistant(ToolCallBlock("ta_2", "read_file", {"path": "b"})),
            Message.tool_results(ToolResultBlock("ta_2", "y")),
        ),
    )
    adapter, _ = wrapper([reply(action("read_file", path="c"))] * 2)
    assert adapter.generate(history).tool_calls[0].id == "ta_3"
    assert adapter.generate(history).tool_calls[0].id == "ta_3"  # identical history, identical id


# -- repair -----------------------------------------------------------------------------------------------------------------


def test_an_invalid_reply_gets_one_repair_and_the_repaired_action_is_used():
    adapter, inner = wrapper([reply("I'll just describe it."), reply(action("read_file", path="a.py"), usage=Usage(130, 25), latency=0.7, request_id="req2")])
    response = adapter.generate(REQUEST)
    assert response.tool_calls[0].name == "read_file" and len(inner.calls) == 2
    repair = inner.calls[1]
    assert repair.tools == ()
    assert repair.messages[-2].blocks[0].text == "I'll just describe it."  # the bad reply is shown back
    assert "No JSON action was found" in repair.messages[-1].blocks[0].text  # with the specific problem
    assert "exactly one JSON action" in repair.messages[-1].blocks[0].text
    stats = adapter.stats
    assert (stats.steps, stats.repaired_steps, stats.failed_steps) == (1, 1, 0)


def test_the_repair_message_is_specific_about_a_schema_problem():
    adapter, inner = wrapper([reply(action("read_file", path=5)), reply(action("read_file", path="a.py"))])
    adapter.generate(REQUEST)
    nudge = inner.calls[1].messages[-1].blocks[0].text
    assert "arguments.path" in nudge and "5 is not of type 'string'" in nudge


def test_a_cut_off_reply_tells_the_model_about_the_limit():
    adapter, inner = wrapper([reply('{"tool": "edit_file", "arguments": {"path": "a.py", "old": "x', stop="max_tokens"), reply(action("read_file", path="a.py"))])
    adapter.generate(REQUEST)
    assert "cut off by the output limit" in inner.calls[1].messages[-1].blocks[0].text


def test_usage_latency_and_flags_are_summed_over_the_whole_step():
    first = reply("chatty", usage=Usage(100, 20, 5, 7), latency=0.5, request_id="req1", estimated=False, model="m1")
    second = reply(action("read_file", path="a"), usage=Usage(130, 25, 2, 0), latency=0.7, request_id="req2", estimated=True, model="m2")
    response = wrapper([first, second])[0].generate(REQUEST)
    assert response.usage == Usage(input_tokens=230, output_tokens=45, cache_read_tokens=7, cache_write_tokens=7)
    assert response.latency_s == pytest.approx(1.2) and response.usage_estimated is True
    assert (response.model, response.request_id) == ("m2", "req2")  # from the last call


def test_a_step_that_succeeds_first_time_reports_just_that_calls_usage():
    response = wrapper([reply(action("read_file", path="a"), usage=Usage(11, 3))])[0].generate(REQUEST)
    assert response.usage == Usage(11, 3)


# -- failure ----------------------------------------------------------------------------------------------------------------------


def test_two_invalid_replies_make_a_failed_step_with_exactly_two_model_calls():
    adapter, inner = wrapper([reply("no action here"), reply("still " + "chatting " * 4 + "chatting")])
    response = adapter.generate(REQUEST)
    assert len(inner.calls) == 2 and inner.remaining == 0  # never a third call
    call = response.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("ta_1", INVALID_ACTION, {})
    assert call.error and call.error.startswith("The reply was not a valid action:") and "No JSON action" in call.error
    assert response.stop_reason == "tool_use"
    assert response.blocks[0] == TextBlock("still " + "chatting " * 4 + "chatting")  # the model's last reply is kept
    assert (adapter.stats.steps, adapter.stats.repaired_steps, adapter.stats.failed_steps) == (1, 0, 1)


def test_a_failed_step_with_an_empty_last_reply_has_just_the_call():
    response = wrapper([reply("x"), reply("")])[0].generate(REQUEST)
    assert [type(b).__name__ for b in response.blocks] == ["ToolCallBlock"]


def test_a_failed_step_sums_usage_too():
    response = wrapper([reply("a", usage=Usage(10, 1)), reply("b", usage=Usage(12, 2))])[0].generate(REQUEST)
    assert response.usage == Usage(22, 3)


def test_the_failed_step_can_be_fed_back_and_the_conversation_stays_valid():
    adapter, inner = wrapper([reply("x"), reply("y"), reply(action("read_file", path="a.py"))])
    failed = adapter.generate(REQUEST)
    call = failed.tool_calls[0]
    follow_up = GenerationRequest(
        tools=TOOLS,
        messages=(*REQUEST.messages, Message.assistant(*failed.blocks), Message.tool_results(ToolResultBlock(call.id, call.error, True))),
    )
    assert adapter.generate(follow_up).tool_calls[0].id == "ta_2"
    seen = inner.calls[2].messages  # what the model is shown on the next step
    assert seen[1].blocks[0].text == "y" and "not a valid action" in seen[2].blocks[0].text


def test_a_long_failed_reply_is_shortened_in_the_response():
    response = wrapper([reply("x"), reply("z" * 50_000)])[0].generate(REQUEST)
    assert len(response.blocks[0].text) <= 1000


# -- what is never repaired ---------------------------------------------------------------------------------------------------------


def test_an_adapter_error_on_the_first_call_propagates_without_a_repair():
    error = AdapterError(RATE_LIMITED_MODEL, "slow down", status_code=429)
    adapter, inner = wrapper([error, reply(action("read_file", path="a"))])
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value is error and inner.remaining == 1
    assert (adapter.stats.repaired_steps, adapter.stats.failed_steps) == (0, 0)


def test_an_adapter_error_during_the_repair_propagates():
    error = AdapterError(RATE_LIMITED_MODEL, "slow down", status_code=429)
    adapter, _ = wrapper([reply("chat"), error])
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value is error and adapter.stats.failed_steps == 0


def test_a_refusal_is_passed_through_with_no_repair():
    refusal = reply("", stop="refusal")
    adapter, inner = wrapper([refusal])
    assert adapter.generate(REQUEST) is refusal and len(inner.calls) == 1


def test_a_refusal_during_the_repair_comes_back_as_a_refusal_with_summed_usage():
    adapter, _ = wrapper([reply("chat", usage=Usage(10, 1)), reply("", usage=Usage(12, 0), stop="refusal")])
    response = adapter.generate(REQUEST)
    assert response.stop_reason == "refusal" and response.usage == Usage(22, 1)
    assert adapter.stats.failed_steps == 0 and adapter.stats.repaired_steps == 0


# -- requests the wrapper does not touch or refuses ---------------------------------------------------------------------------------------


def test_a_request_without_tools_passes_through_untouched():
    response = reply("Plain answer.")
    adapter, inner = wrapper([response])
    request = GenerationRequest(messages=(Message.user("hi"),), system=(TextBlock("sys"),))
    assert adapter.generate(request) is response
    assert inner.calls == [request] and adapter.stats.steps == 0  # not a tool step, and the request was not converted


def test_an_invalid_request_is_rejected_before_any_model_call():
    adapter, inner = wrapper([reply(action("read_file", path="a"))])
    with pytest.raises(AdapterError) as info:
        adapter.generate(GenerationRequest(messages=(), tools=TOOLS))
    assert info.value.code == INVALID_REQUEST and inner.calls == []


def test_a_tool_with_an_invalid_schema_is_refused_locally():
    broken = ToolDefinition("broken", "Bad schema.", {"type": "object", "properties": {"a": {"type": "not-a-type"}}})
    adapter, inner = wrapper([reply(action("broken"))])
    with pytest.raises(AdapterError) as info:
        adapter.generate(GenerationRequest(messages=(Message.user("x"),), tools=(broken,)))
    assert info.value.code == INVALID_REQUEST and "broken" in info.value.message and inner.calls == []


def test_the_original_request_is_not_modified():
    before = json.dumps(REQUEST.to_dict(), sort_keys=True)
    wrapper([reply("x"), reply(action("read_file", path="a"))])[0].generate(REQUEST)
    assert json.dumps(REQUEST.to_dict(), sort_keys=True) == before


# -- the wrapper looks like the adapter it wraps -------------------------------------------------------------------------------------------


def test_name_config_and_estimate_come_from_the_inner_adapter():
    adapter, inner = wrapper([])
    assert adapter.name == inner.name and adapter.config is inner.config and adapter.inner is inner
    assert adapter.max_calls_per_step == 2
    plain = GenerationRequest(messages=(Message.user("hi"),))
    assert adapter.estimate_tokens(plain) == inner.estimate_tokens(plain)
    assert adapter.estimate_tokens(REQUEST) > inner.estimate_tokens(REQUEST)  # the instruction block is counted


def test_close_reaches_the_inner_adapter():
    class Closable(ScriptedAdapter):
        closed = False

        def close(self):
            self.closed = True

    inner = Closable(scripted_config(), [])
    TextActionAdapter(inner).close()
    assert inner.closed
    TextActionAdapter(ScriptedAdapter(scripted_config(), [])).close()  # nothing to close is fine


class TestTextActionContract(AdapterContract):
    """The wrapper passes the same contract every adapter must pass."""

    def adapter_for_text(self):
        return TextActionAdapter(ScriptedAdapter(scripted_config(), [text_response("Hello there!")] * 10))

    def adapter_for_tool_call(self):
        return TextActionAdapter(ScriptedAdapter(scripted_config(), [text_response(action("read_file", path="a.py"))] * 10))


# -- cost accounting and wiring -------------------------------------------------------------------------------------------------------------


def test_a_repaired_step_leaves_two_ledger_entries_and_the_response_carries_their_sum():
    ledger = CostLedger()
    inner = ScriptedAdapter(paid_model(), [reply("chat", usage=Usage(1000, 100)), reply(action("read_file", path="a"), usage=Usage(1200, 50))])
    adapter = TextActionAdapter(MeteredAdapter(inner, ledger))
    response = adapter.generate(REQUEST)
    assert len(ledger.calls) == 2  # the original call and the repair, each its own paid call
    assert response.usage == Usage(2200, 150)
    first, second = ledger.calls
    assert ledger.total_usd == first.cost.total_usd + second.cost.total_usd > 0


def test_create_adapter_wraps_models_without_native_tool_calling_and_only_those():
    models = load_models_config("config/models.yaml")
    ledger = CostLedger()
    local = create_adapter(models["local-free"], ledger=ledger)
    assert isinstance(local, TextActionAdapter) and isinstance(local.inner, MeteredAdapter) and local.inner.ledger is ledger
    local.close()
    native = create_adapter(models["haiku"], api_key="sk-ant-x", ledger=ledger)
    assert isinstance(native, MeteredAdapter) and isinstance(native.inner, ClaudeAdapter)
    native.close()
    plain = create_adapter(models["haiku"], api_key="sk-ant-x")
    assert isinstance(plain, ClaudeAdapter)
    plain.close()


def test_without_a_ledger_a_non_native_model_is_wrapped_directly():
    local = create_adapter(load_models_config("config/models.yaml")["local-free"])
    assert isinstance(local, TextActionAdapter) and not isinstance(local.inner, MeteredAdapter)
    local.close()


# -- end to end through the OpenAI-compatible adapter on a mock server --------------------------------------------------------------------------


def served(replies):
    """A non-native model served over (mock) HTTP; `replies` are the contents it answers with, in order."""
    queue = list(replies)
    adapter, recorder = openai_adapter_for(lambda request: httpx.Response(200, json=completion(queue.pop(0))), native=False)
    return TextActionAdapter(adapter), recorder


def test_end_to_end_the_http_request_has_no_tools_and_a_json_reply_becomes_a_tool_call():
    adapter, recorder = served(['Let me read it.\n```json\n' + action("read_file", path="a.py") + '\n```'])
    response = adapter.generate(REQUEST)
    body = recorder.body
    assert "tools" not in body and "tool_choice" not in body
    system = body["messages"][0]["content"]
    assert body["messages"][0]["role"] == "system" and "HOW TO USE TOOLS" in system and "edit_file" in system
    assert response.tool_calls[0].name == "read_file" and response.tool_calls[0].arguments == {"path": "a.py"}
    assert response.text == "Let me read it."


def test_end_to_end_a_broken_first_reply_triggers_a_second_http_request():
    adapter, recorder = served(["Sure, I can help!", action("run_command", command="pwd")])
    response = adapter.generate(REQUEST)
    assert len(recorder.requests) == 2 and response.tool_calls[0].name == "run_command"
    repair_messages = recorder.bodies[1]["messages"]
    assert repair_messages[-2] == {"role": "assistant", "content": "Sure, I can help!"}
    assert "No JSON action was found" in repair_messages[-1]["content"]


def test_end_to_end_two_broken_replies_give_an_invalid_action_call():
    adapter, recorder = served(["Sure!", "Of course!"])
    response = adapter.generate(REQUEST)
    assert len(recorder.requests) == 2
    assert response.tool_calls[0].name == INVALID_ACTION and adapter.stats.failed_steps == 1


def test_end_to_end_a_multi_step_conversation_keeps_the_format():
    adapter, recorder = served([action("read_file", path="a.py"), final("Done.")])
    first = adapter.generate(REQUEST)
    call = first.tool_calls[0]
    second_request = GenerationRequest(
        tools=TOOLS,
        messages=(*REQUEST.messages, Message.assistant(*first.blocks), Message.tool_results(ToolResultBlock(call.id, "def f(): pass"))),
    )
    second = adapter.generate(second_request)
    assert second.text == "Done." and second.stop_reason == "end_turn"
    sent = recorder.bodies[1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert json.loads(sent[2]["content"]) == {"tool": "read_file", "arguments": {"path": "a.py"}}
    assert sent[3]["content"] == "[result of read_file call ta_1]\ndef f(): pass"
