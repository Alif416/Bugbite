"""What the Claude adapter sends. The SDK's HTTP layer is mocked; nothing touches the network."""

import json

import pytest
from claude_helpers import KEY, adapter_for, message, model

from bugbite.adapter import (
    ClaudeAdapter,
    GenerationRequest,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
)
from bugbite.config import ConfigError
from bugbite.errors import INVALID_REQUEST, AdapterError

TOOL = ToolDefinition("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})


def send(request, **kwargs):
    adapter, rec = adapter_for(message(), **kwargs)
    adapter.generate(request)
    return rec


def simple(**kwargs):
    return GenerationRequest(messages=(Message.user("hi"),), **kwargs)


def markers(body):
    """How many cache_control markers a request body carries, anywhere."""
    return json.dumps(body).count('"cache_control"')


# -- basics ------------------------------------------------------------------------------------


def test_basic_request():
    rec = send(simple())
    request = rec.requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.anthropic.com/v1/messages"
    assert rec.body == {
        "model": "claude-haiku-5-5",
        "max_tokens": 2048,  # the model's default
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        "thinking": {"type": "disabled"},
        "cache_control": {"type": "ephemeral"},  # prompt_caching: auto
    }


def test_headers():
    headers = send(simple()).requests[0].headers
    assert headers["authorization"] == f"Bearer {KEY}"
    assert headers["content-type"] == "application/json"
    assert headers["anthropic-version"]


def test_no_sampling_parameter_is_ever_sent():
    for request in (simple(), simple(temperature=1.0), simple(temperature=1), simple(tools=(TOOL,), stop_sequences=("x",))):
        body = send(request).body
        assert not {"temperature", "top_p", "top_k"} & set(body)


def test_base_url_comes_from_the_model_config():
    rec = send(simple(), base_url="https://proxy.example.com/anthropic")
    assert str(rec.requests[0].url) == "https://proxy.example.com/anthropic/v1/messages"


def test_max_tokens_comes_from_the_request_or_the_model_default():
    assert send(simple()).body["max_tokens"] == 2048
    assert send(simple(max_output_tokens=77)).body["max_tokens"] == 77


def test_stop_sequences_are_passed_only_when_given():
    assert send(simple(stop_sequences=("###", "END"))).body["stop_sequences"] == ["###", "END"]
    assert "stop_sequences" not in send(simple()).body


def test_thinking_is_disabled_on_every_request():
    assert send(simple()).body["thinking"] == {"type": "disabled"}
    assert send(simple(tools=(TOOL,))).body["thinking"] == {"type": "disabled"}


def test_tools_use_input_schema_and_leave_tool_choice_alone():
    body = send(simple(tools=(TOOL,))).body
    assert body["tools"] == [{"name": "read_file", "description": "Read a file", "input_schema": TOOL.parameters}]
    assert "tool_choice" not in body and "tools" not in send(simple()).body


# -- messages --------------------------------------------------------------------------------------


def conversation():
    return GenerationRequest(
        system=(TextBlock("sys one"), TextBlock(""), TextBlock("sys two")),
        tools=(TOOL,),
        messages=(
            Message.user("fix é"),
            Message.assistant("looking", ToolCallBlock("c1", "read_file", {"path": "a.py", "n": [1, 2]}), ToolCallBlock("c2", "read_file", {})),
            Message("user", (TextBlock("go on"), ToolResultBlock("c1", "contents"), ToolResultBlock("c2", "boom", True))),
            Message.assistant(ToolCallBlock("c3", "read_file", {"path": "b.py"})),
            Message.tool_results(ToolResultBlock("c3", "")),
        ),
    )


def test_full_conversation_translation():
    body = send(conversation(), prompt_caching="off").body
    assert body["system"] == [{"type": "text", "text": "sys one"}, {"type": "text", "text": "sys two"}]
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "fix é"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "looking"},
                {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "a.py", "n": [1, 2]}},
                {"type": "tool_use", "id": "c2", "name": "read_file", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": "contents"},
                {"type": "tool_result", "tool_use_id": "c2", "content": "boom", "is_error": True},
                {"type": "text", "text": "go on"},  # text comes after the tool results even though it was first
            ],
        },
        {"role": "assistant", "content": [{"type": "tool_use", "id": "c3", "name": "read_file", "input": {"path": "b.py"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c3"}]},  # empty content is omitted
    ]


def test_tool_results_always_come_before_text_in_a_user_message():
    request = GenerationRequest(
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("c1", "t", {})),
            Message("user", (TextBlock("a"), TextBlock("b"), ToolResultBlock("c1", "r"), TextBlock("c"))),
        )
    )
    kinds = [b["type"] for b in send(request, prompt_caching="off").body["messages"][2]["content"]]
    assert kinds == ["tool_result", "text", "text", "text"]


def test_is_error_is_sent_only_when_true():
    request = GenerationRequest(
        messages=(
            Message.user("go"),
            Message.assistant(ToolCallBlock("c1", "t", {}), ToolCallBlock("c2", "t", {})),
            Message.tool_results(ToolResultBlock("c1", "fine"), ToolResultBlock("c2", "bad", True)),
        )
    )
    first, second = send(request).body["messages"][2]["content"]
    assert "is_error" not in first and second["is_error"] is True


def test_unicode_is_preserved():
    text = "café ✓ \U0001f41b"
    body = send(GenerationRequest(messages=(Message.user(text),))).body
    assert body["messages"][0]["content"][0]["text"] == text


def test_empty_messages_get_a_placeholder_because_the_api_rejects_empty_ones():
    request = GenerationRequest(messages=(Message.user(""), Message.assistant(""), Message.user("x")))
    messages = send(request).body["messages"]
    assert messages[0]["content"] == [{"type": "text", "text": "(empty)"}]
    assert messages[1]["content"] == [{"type": "text", "text": "(empty)"}]


def test_tool_call_arguments_are_sent_as_an_object_not_a_string():
    sent = send(conversation()).body["messages"][1]["content"][1]["input"]
    assert isinstance(sent, dict)


# -- temperature --------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 1, 1.0])
def test_default_temperature_is_accepted_and_nothing_is_sent(value):
    rec = send(simple(temperature=value))
    assert len(rec.requests) == 1 and "temperature" not in rec.body


@pytest.mark.parametrize("value", [0, 0.0, 0.5, 0.99, 1.01, 1.5, 2])
def test_other_temperatures_are_refused_before_any_network_call(value):
    adapter, rec = adapter_for(message())
    with pytest.raises(AdapterError) as info:
        adapter.generate(simple(temperature=value))
    assert info.value.code == INVALID_REQUEST
    assert "default temperature" in info.value.message and "claude-model" in info.value.message
    assert rec.requests == []


# -- prompt caching ------------------------------------------------------------------------------------


def flagged(count):
    """A request with `count` cache-flagged user blocks spread over the conversation."""
    messages = [Message("user", (TextBlock("first", cache=count >= 1),))]
    for index in range(1, count):
        messages.append(Message.assistant(f"a{index}"))
        messages.append(Message("user", (TextBlock(f"u{index}", cache=True),)))
    return GenerationRequest(messages=tuple(messages))


def test_auto_sets_the_top_level_marker_and_honours_flags():
    request = GenerationRequest(system=(TextBlock("system", cache=True),), messages=(Message.user("q"),))
    body = send(request, prompt_caching="auto").body
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in body["messages"][0]["content"][0]


def test_explicit_honours_flags_only():
    request = GenerationRequest(system=(TextBlock("system", cache=True),), messages=(Message.user("q"),))
    body = send(request, prompt_caching="explicit").body
    assert "cache_control" not in {k for k in body if k != "system"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert markers(body) == 1


def test_off_sends_no_marker_at_all_even_for_flagged_blocks():
    request = GenerationRequest(system=(TextBlock("system", cache=True),), messages=(Message("user", (TextBlock("q", cache=True),)),))
    assert markers(send(request, prompt_caching="off").body) == 0


def test_unflagged_requests_in_explicit_mode_carry_no_markers():
    assert markers(send(simple(), prompt_caching="explicit").body) == 0


@pytest.mark.parametrize("mode, limit", [("auto", 4), ("explicit", 4), ("off", 0)])
@pytest.mark.parametrize("count", [0, 1, 3, 4, 5, 9])
def test_never_more_than_four_markers_in_total(mode, limit, count):
    body = send(flagged(count), prompt_caching=mode).body
    assert markers(body) <= limit


def test_when_too_many_blocks_are_flagged_the_last_ones_are_kept():
    body = send(flagged(6), prompt_caching="explicit").body  # six flagged blocks, four allowed
    marked = [m["content"][0]["text"] for m in body["messages"] if "cache_control" in m["content"][0]]
    assert marked == ["u2", "u3", "u4", "u5"]
    body = send(flagged(6), prompt_caching="auto").body  # the top-level marker takes one slot
    marked = [m["content"][0]["text"] for m in body["messages"] if "cache_control" in m["content"][0]]
    assert marked == ["u3", "u4", "u5"] and "cache_control" in body


def test_an_empty_flagged_block_is_never_marked():
    request = GenerationRequest(system=(TextBlock("", cache=True),), messages=(Message.user("q"),))
    assert "system" not in send(request, prompt_caching="explicit").body


# -- validation and the key -------------------------------------------------------------------------------


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
    adapter, rec = adapter_for(message())
    with pytest.raises(AdapterError) as info:
        adapter.generate(bad)
    assert info.value.code == INVALID_REQUEST
    assert rec.requests == []


def test_the_request_object_is_not_modified():
    request = conversation()
    before = json.dumps(request.to_dict(), sort_keys=True)
    send(request)
    assert json.dumps(request.to_dict(), sort_keys=True) == before


@pytest.mark.parametrize("key", [None, ""])
def test_an_adapter_cannot_be_built_without_a_key(key):
    with pytest.raises(ConfigError, match="needs an API key"):
        ClaudeAdapter(model(), key)


def test_the_default_client_has_the_sdk_retries_switched_off():
    adapter = ClaudeAdapter(model(), KEY)
    try:
        assert adapter._client.max_retries == 0
        assert adapter._client.base_url.host == "api.anthropic.com"
    finally:
        adapter.close()


def test_ambient_credentials_in_the_environment_are_never_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-api-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-auth-token")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ambient.example")
    adapter, rec = adapter_for(message())
    adapter.generate(simple())
    request = rec.requests[0]
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.url.host == "api.anthropic.com"
    with pytest.raises(ConfigError):  # and no key means no adapter, even though the environment holds one
        ClaudeAdapter(model(), None)


def test_the_key_is_not_in_the_repr_or_str():
    adapter, _ = adapter_for(message())
    assert KEY not in repr(adapter) and KEY not in str(adapter)
    assert "claude-model" in repr(adapter)
