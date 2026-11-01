"""How a tool conversation is shown to a model that only reads and writes text."""

import json

import pytest
from text_action_helpers import EDIT_FILE, LIST_DIRECTORY, READ_FILE, RUN_COMMAND, RUN_TESTS, SEARCH_CODE, TOOLS, action

from bugbite.adapter import (
    GenerationRequest,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    validate_request,
)
from bugbite.adapter.text_action import INVALID_ACTION, PROMPT_VERSION, instruction_text, text_request


def flat(message):
    return "\n".join(b.text for b in message.blocks)


def conversation():
    return GenerationRequest(
        system=(TextBlock("You fix bugs.", cache=True),),
        tools=TOOLS,
        temperature=1.0,
        max_output_tokens=777,
        stop_sequences=("###",),
        messages=(
            Message.user("Fix the crash."),
            Message.assistant("Looking first.", ToolCallBlock("ta_1", "read_file", {"path": "a.py"})),
            Message.tool_results(ToolResultBlock("ta_1", "def f(): pass")),
            Message.assistant(ToolCallBlock("ta_2", "run_tests", {})),
            Message.tool_results(ToolResultBlock("ta_2", "1 failed", is_error=True)),
            Message.assistant("All fixed."),
            Message.user("Thanks, summarise."),
        ),
    )


# -- the instruction block -------------------------------------------------------------------------


def test_the_instructions_describe_every_tool_both_shapes_and_the_version():
    text = instruction_text(TOOLS)
    assert f"format version {PROMPT_VERSION}" in text
    for tool in TOOLS:
        assert f"- {tool.name}: {tool.description}" in text
        assert json.dumps(tool.parameters, ensure_ascii=False, separators=(",", ":")) in text
    assert '{"tool": "<tool name>", "arguments": {<arguments>}}' in text
    assert '{"final": "<your final answer>"}' in text
    assert "exactly ONE JSON action" in text


@pytest.mark.parametrize(
    "tool, expected",
    [
        (READ_FILE, {"path": "..."}),
        (EDIT_FILE, {"path": "...", "old": "...", "new": "..."}),
        (RUN_TESTS, {}),
        (SEARCH_CODE, {"query": "..."}),
        (RUN_COMMAND, {"command": "..."}),
        (LIST_DIRECTORY, {"path": "..."}),
    ],
)
def test_the_worked_example_uses_the_first_tools_required_arguments(tool, expected):
    assert f"For example: {json.dumps({'tool': tool.name, 'arguments': expected})}" in instruction_text((tool,))


def test_the_prompt_version_is_a_non_empty_string():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


# -- the request sent to the model -----------------------------------------------------------------------


def test_the_text_request_has_no_tools_and_keeps_the_options():
    request = text_request(conversation())
    assert request.tools == ()
    assert (request.temperature, request.max_output_tokens, request.stop_sequences) == (1.0, 777, ("###",))


def test_the_instructions_follow_the_original_system_prompt_and_its_cache_flag_is_kept():
    system = text_request(conversation()).system
    assert system[0] == TextBlock("You fix bugs.", cache=True)
    assert system[1].text == instruction_text(TOOLS) and system[1].cache is False and len(system) == 2


def test_the_converted_conversation_is_a_valid_request():
    validate_request(text_request(conversation()))


def test_history_is_rendered_in_the_format_the_model_must_produce():
    messages = text_request(conversation()).messages
    assert flat(messages[0]) == "Fix the crash."
    assert flat(messages[1]) == 'Looking first.\n{"tool": "read_file", "arguments": {"path": "a.py"}}'
    assert flat(messages[2]) == "[result of read_file call ta_1]\ndef f(): pass"
    assert flat(messages[3]) == '{"tool": "run_tests", "arguments": {}}'
    assert flat(messages[4]) == "[result of run_tests call ta_2]\nERROR: 1 failed"
    assert json.loads(flat(messages[5])) == {"final": "All fixed."}
    assert flat(messages[6]) == "Thanks, summarise."


def test_a_user_message_with_results_and_text_keeps_both():
    request = GenerationRequest(
        tools=TOOLS,
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("ta_1", "list_directory", {"path": "."})),
            Message("user", (ToolResultBlock("ta_1", "a.py\nb.py"), TextBlock("and then?", cache=True))),
        ),
    )
    last = text_request(request).messages[2]
    assert [b.text for b in last.blocks] == ["[result of list_directory call ta_1]\na.py\nb.py", "and then?"]
    assert last.blocks[1].cache is True


def test_a_failed_step_is_shown_as_the_models_own_reply_then_a_not_valid_message():
    request = GenerationRequest(
        tools=TOOLS,
        messages=(
            Message.user("go"),
            Message.assistant("I will chat instead.", ToolCallBlock("ta_1", INVALID_ACTION, {}, error="no JSON action")),
            Message.tool_results(ToolResultBlock("ta_1", "The reply was not a valid action: No JSON action was found.", is_error=True)),
        ),
    )
    messages = text_request(request).messages
    assert flat(messages[1]) == "I will chat instead."
    assert INVALID_ACTION not in flat(messages[1])  # never shown as something to imitate
    assert flat(messages[2]).startswith("Your previous reply was not a valid action: The reply was not a valid action")
    assert flat(messages[2]).endswith("Reply with exactly one JSON action.")


def test_a_failed_step_with_no_reply_text_gets_a_placeholder():
    request = GenerationRequest(
        tools=TOOLS,
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("ta_1", INVALID_ACTION, {}, error="empty")),
            Message.tool_results(ToolResultBlock("ta_1", "nothing usable")),
        ),
    )
    assert flat(text_request(request).messages[1]) == "(no valid action)"


def test_a_result_for_an_unknown_call_still_renders():
    request = GenerationRequest(tools=TOOLS, messages=(Message.user("go"), Message.assistant(ToolCallBlock("ta_1", "read_file", {})), Message.tool_results(ToolResultBlock("ta_1", "x"))))
    assert flat(text_request(request).messages[2]).startswith("[result of read_file call ta_1]")


def test_unicode_and_special_characters_survive_rendering():
    args = {"path": "café.py", "old": 'say "hi"\n{x}', "new": "✓ \U0001f41b"}
    request = GenerationRequest(tools=TOOLS, messages=(Message.user("go"), Message.assistant(ToolCallBlock("ta_1", "edit_file", args)), Message.tool_results(ToolResultBlock("ta_1", "ok"))))
    rendered = flat(text_request(request).messages[1])
    assert json.loads(rendered) == {"tool": "edit_file", "arguments": args} and "✓" in rendered  # not escaped away


def test_empty_assistant_and_user_messages_get_placeholders():
    request = GenerationRequest(tools=TOOLS, messages=(Message.user(""), Message.assistant(""), Message.user("x")))
    messages = text_request(request).messages
    assert flat(messages[0]) == "(empty)" and json.loads(flat(messages[1])) == {"final": ""}


def test_the_original_request_is_not_modified():
    request = conversation()
    before = json.dumps(request.to_dict(), sort_keys=True)
    text_request(request)
    assert json.dumps(request.to_dict(), sort_keys=True) == before


def test_the_conversion_is_deterministic():
    assert text_request(conversation()).to_dict() == text_request(conversation()).to_dict()
