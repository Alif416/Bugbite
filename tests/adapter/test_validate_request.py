import pytest

from bugbite.adapter import (
    GenerationRequest,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    validate_request,
)
from bugbite.errors import INVALID_REQUEST, AdapterError

TOOL = ToolDefinition("read_file", "Read a file", {"type": "object"})


def call(i, name="read_file"):
    return ToolCallBlock(f"c{i}", name, {"path": "a.py"})


def result(i, text="contents"):
    return ToolResultBlock(f"c{i}", text)


def check(*messages, **kwargs):
    validate_request(GenerationRequest(messages=tuple(messages), **kwargs))


def rejected(match, *messages, **kwargs):
    with pytest.raises(AdapterError, match=match) as info:
        check(*messages, **kwargs)
    assert info.value.code == INVALID_REQUEST
    return info.value


# -- valid conversations -------------------------------------------------------------


def test_single_user_message_is_valid():
    check(Message.user("hi"))


def test_system_prompt_tools_and_options_are_valid():
    check(Message.user("hi"), system=(TextBlock("be brief", cache=True),), tools=(TOOL,), temperature=2, max_output_tokens=1)
    check(Message.user("hi"), temperature=0)


def test_multi_turn_tool_conversation_is_valid():
    check(
        Message.user("fix it"),
        Message.assistant("looking", call(1), call(2)),
        Message.tool_results(result(1), result(2)),
        Message.assistant("done?"),
        Message.user("thanks"),
        Message.assistant(call(3)),
        Message.tool_results(result(3, "")),
        tools=(TOOL,),
    )


def test_tool_result_message_may_also_carry_text():
    check(
        Message.user("go"),
        Message.assistant(call(1)),
        Message("user", (result(1), TextBlock("and also this"))),
    )


def test_an_error_result_and_a_call_with_an_error_are_valid_history():
    check(
        Message.user("go"),
        Message.assistant(ToolCallBlock("c1", "read_file", {}, error="bad json")),
        Message.tool_results(ToolResultBlock("c1", "arguments invalid", is_error=True)),
    )


# -- each rule -----------------------------------------------------------------------


def test_empty_messages():
    rejected("no messages")


def test_first_message_must_be_from_the_user():
    rejected("first message", Message.assistant("hi"), Message.user("x"))


def test_last_message_must_be_from_the_user():
    rejected("last message", Message.user("x"), Message.assistant("y"))


def test_roles_must_alternate():
    rejected("alternate", Message.user("a"), Message.user("b"))
    rejected("alternate", Message.user("a"), Message.assistant("b"), Message.assistant("c"), Message.user("d"))


def test_tool_call_in_a_user_message():
    rejected("user message cannot contain a tool call", Message("user", (call(1),)))


def test_tool_result_in_an_assistant_message():
    rejected(
        "assistant message cannot contain a tool result",
        Message.user("x"),
        Message("assistant", (result(1),)),
        Message.user("y"),
    )


def test_tool_result_with_no_matching_call():
    rejected("does not match", Message.tool_results(result(1)))
    rejected("does not match", Message.user("x"), Message.assistant("no calls here"), Message.tool_results(result(1)))


def test_tool_result_for_a_call_from_an_earlier_turn():
    rejected(
        "does not match",
        Message.user("x"),
        Message.assistant(call(1)),
        Message.tool_results(result(1)),
        Message.assistant(call(2)),
        Message.tool_results(result(1), result(2)),  # c1 was answered in the previous round
    )


def test_unanswered_tool_call():
    error = rejected(
        "not answered",
        Message.user("x"),
        Message.assistant(call(1), call(2)),
        Message.tool_results(result(1)),
    )
    assert "c2" in error.message


def test_tool_call_followed_by_plain_text_is_unanswered():
    rejected("not answered", Message.user("x"), Message.assistant(call(1)), Message.user("just text"))


def test_duplicate_tool_call_ids_across_the_conversation():
    rejected(
        "more than once",
        Message.user("x"),
        Message.assistant(call(1)),
        Message.tool_results(result(1)),
        Message.assistant(call(1)),
        Message.tool_results(result(1)),
    )


def test_duplicate_tool_call_ids_in_one_message():
    rejected("more than once", Message.user("x"), Message.assistant(call(1), call(1)), Message.tool_results(result(1)))


def test_two_results_for_one_call():
    rejected("more than one tool result", Message.user("x"), Message.assistant(call(1)), Message.tool_results(result(1), result(1)))


def test_duplicate_tool_names():
    error = rejected("unique", Message.user("x"), tools=(TOOL, ToolDefinition("read_file", "dup", {"type": "object"})))
    assert "read_file" in error.message


@pytest.mark.parametrize("temperature", [-0.1, 2.1, 100, float("nan"), float("inf")])
def test_temperature_out_of_range(temperature):
    rejected("temperature", Message.user("x"), temperature=temperature)


@pytest.mark.parametrize("limit", [0, -5])
def test_max_output_tokens_must_be_positive(limit):
    rejected("max_output_tokens", Message.user("x"), max_output_tokens=limit)


def test_messages_name_the_position_of_the_problem():
    error = rejected(
        None,
        Message.user("x"),
        Message.assistant("y"),
        Message.user("z"),
        Message.user("w"),
    )
    assert "messages[3]" in error.message
