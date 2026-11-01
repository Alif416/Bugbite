"""What the adapter sends: request translation. Mock transport, no network."""

import json

import pytest
from openai_helpers import BASE_URL, KEY, adapter_for, completion, model

from bugbite.adapter import (
    GenerationRequest,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
)
from bugbite.errors import INVALID_REQUEST, AdapterError

TOOL = ToolDefinition("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})


def send(request, **kwargs):
    adapter, rec = adapter_for(completion(), **kwargs)
    adapter.generate(request)
    return rec


def simple(**kwargs):
    return GenerationRequest(messages=(Message.user("hi"),), **kwargs)


def test_basic_payload_and_url():
    rec = send(simple())
    request = rec.requests[0]
    assert request.method == "POST" and str(request.url) == f"{BASE_URL}/chat/completions"
    assert rec.body == {
        "model": "vendor/model-7b",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.0,
        "max_tokens": 2048,  # the model's default
        "stream": False,
    }


@pytest.mark.parametrize(
    "base_url, expected",
    [
        ("http://h/v1", "http://h/v1/chat/completions"),
        ("http://h/v1/", "http://h/v1/chat/completions"),
        ("http://h", "http://h/chat/completions"),
        ("https://api.example.com/openai/v1", "https://api.example.com/openai/v1/chat/completions"),
        ("http://localhost:11434/v1", "http://localhost:11434/v1/chat/completions"),
    ],
)
def test_url_joining(base_url, expected):
    assert str(send(simple(), base_url=base_url).requests[0].url) == expected


def test_headers_with_a_key():
    headers = send(simple()).requests[0].headers
    assert headers["authorization"] == f"Bearer {KEY}"
    assert headers["content-type"] == "application/json"
    assert headers["user-agent"] == "bugbite"


def test_no_authorization_header_without_a_key():
    adapter, rec = adapter_for(completion(), key=None)
    adapter.generate(simple())
    assert "authorization" not in rec.requests[0].headers


def test_request_options():
    rec = send(simple(temperature=1.5, max_output_tokens=64, stop_sequences=("###", "END")))
    assert rec.body["temperature"] == 1.5
    assert rec.body["max_tokens"] == 64  # the request overrides the model default
    assert rec.body["stop"] == ["###", "END"]
    assert "tools" not in rec.body and "tool_choice" not in rec.body


def test_zero_temperature_is_sent_not_dropped():
    assert send(simple(temperature=0)).body["temperature"] == 0


def test_system_blocks_are_joined_and_cache_markers_ignored():
    rec = send(simple(system=(TextBlock("Rule one.", cache=True), TextBlock(""), TextBlock("Rule two."))))
    assert rec.body["messages"][0] == {"role": "system", "content": "Rule one.\n\nRule two."}
    assert "cache" not in json.dumps(rec.body)


def test_no_system_message_when_there_is_no_system_text():
    assert send(simple(system=(TextBlock(""),))).body["messages"][0]["role"] == "user"
    assert send(simple()).body["messages"][0]["role"] == "user"


def test_user_text_blocks_are_joined_and_empty_ones_skipped():
    request = GenerationRequest(messages=(Message("user", (TextBlock("a"), TextBlock(""), TextBlock("b"))),))
    assert send(request).body["messages"] == [{"role": "user", "content": "a\n\nb"}]


def test_a_user_message_with_only_empty_text_is_still_sent():
    request = GenerationRequest(messages=(Message.user(""),))
    assert send(request).body["messages"] == [{"role": "user", "content": ""}]


def test_tools_are_sent_in_function_format():
    rec = send(simple(tools=(TOOL,)))
    assert rec.body["tools"] == [
        {"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": TOOL.parameters}}
    ]
    assert "tool_choice" not in rec.body


def conversation():
    return GenerationRequest(
        system=(TextBlock("sys"),),
        tools=(TOOL,),
        messages=(
            Message.user("fix é"),
            Message.assistant(
                "looking",
                ToolCallBlock("c1", "read_file", {"path": "a.py", "note": "café"}),
                ToolCallBlock("c2", "read_file", {}),
            ),
            Message("user", (ToolResultBlock("c1", "contents", False), ToolResultBlock("c2", "boom", True), TextBlock("go on"))),
            Message.assistant(ToolCallBlock("c3", "read_file", {"path": "b.py"})),
            Message.tool_results(ToolResultBlock("c3", "")),
        ),
    )


def test_full_conversation_translation():
    messages = send(conversation()).body["messages"]
    assert messages == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "fix é"},
        {
            "role": "assistant",
            "content": "looking",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"path": "a.py", "note": "café"}, ensure_ascii=False)}},
                {"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "contents"},
        {"role": "tool", "tool_call_id": "c2", "content": "boom"},  # is_error has no equivalent; content passes unchanged
        {"role": "user", "content": "go on"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c3", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "b.py"}'}}]},
        {"role": "tool", "tool_call_id": "c3", "content": ""},
    ]


def test_arguments_are_json_strings_and_unicode_is_not_escaped():
    messages = send(conversation()).body["messages"]
    arguments = messages[2]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(arguments, str) and "café" in arguments


def test_tool_results_come_directly_after_the_assistant_message_and_before_user_text():
    roles = [m["role"] for m in send(conversation()).body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "tool", "user", "assistant", "tool"]


def test_a_tool_call_with_a_parse_error_in_history_is_sent_with_empty_arguments():
    request = GenerationRequest(
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("c1", "read_file", {}, error="bad json")),
            Message.tool_results(ToolResultBlock("c1", "your arguments were invalid", True)),
        )
    )
    call = send(request).body["messages"][1]["tool_calls"][0]
    assert call["function"]["arguments"] == "{}"


# -- refusing tools for models without native tool calling --------------------------------------


def test_tools_for_a_model_without_native_tool_calling_are_refused_before_any_network_call():
    adapter, rec = adapter_for(completion(), native=False)
    with pytest.raises(AdapterError) as info:
        adapter.generate(simple(tools=(TOOL,)))
    assert info.value.code == INVALID_REQUEST
    assert "text-action" in info.value.message and "free-model" in info.value.message
    assert rec.requests == []


def test_a_plain_text_request_works_for_a_model_without_native_tool_calling():
    adapter, rec = adapter_for(completion(), native=False)
    assert adapter.generate(simple()).text == "Hello there!"
    assert "tools" not in rec.body


# -- validation and immutability ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        GenerationRequest(messages=()),
        GenerationRequest(messages=(Message.assistant("hi"),)),
        GenerationRequest(messages=(Message.user("x"),), temperature=9),
        GenerationRequest(messages=(Message.tool_results(ToolResultBlock("zz", "r")),)),
    ],
)
def test_invalid_requests_never_reach_the_network(bad):
    adapter, rec = adapter_for(completion())
    with pytest.raises(AdapterError) as info:
        adapter.generate(bad)
    assert info.value.code == INVALID_REQUEST
    assert rec.requests == []


def test_the_request_object_is_not_modified():
    request = conversation()
    before = json.dumps(request.to_dict(), sort_keys=True)
    send(request)
    assert json.dumps(request.to_dict(), sort_keys=True) == before


def test_unusual_config_values_are_used_as_given():
    rec = send(simple(), config=model(model_name="llama3.1:8b", max_output_tokens=777))
    assert rec.body["model"] == "llama3.1:8b" and rec.body["max_tokens"] == 777
