"""What the Claude adapter understands from responses. Mock transport, no network."""

import httpx2
import pytest
from claude_helpers import adapter_for, message, text, tool_use

from bugbite.adapter import GenerationRequest, GenerationResponse, Message, TextBlock, ToolCallBlock

REQUEST = GenerationRequest(messages=(Message.user("hi"),))


def run(body, **kwargs):
    adapter, _ = adapter_for(body, **kwargs)
    return adapter.generate(REQUEST)


# -- content ----------------------------------------------------------------------------------


def test_plain_text():
    response = run(message([text("Hello there!")]))
    assert response.blocks == (TextBlock("Hello there!"),)
    assert response.text == "Hello there!" and response.tool_calls == ()
    assert response.stop_reason == "end_turn" and response.raw_stop_reason == "end_turn"


def test_tool_use():
    response = run(message([tool_use("read_file", {"path": "a.py", "n": [1, 2]}, id="toolu_9")], stop_reason="tool_use"))
    (call,) = response.tool_calls
    assert (call.id, call.name, call.arguments, call.error) == ("toolu_9", "read_file", {"path": "a.py", "n": [1, 2]}, None)
    assert response.stop_reason == "tool_use"


def test_text_and_several_tool_uses_keep_their_order():
    body = message([text("first"), tool_use("a", id="t1"), text("middle"), tool_use("b", id="t2")], stop_reason="tool_use")
    response = run(body)
    assert [type(b).__name__ for b in response.blocks] == ["TextBlock", "ToolCallBlock", "TextBlock", "ToolCallBlock"]
    assert [c.id for c in response.tool_calls] == ["t1", "t2"] and response.text == "firstmiddle"


def test_empty_content_is_an_empty_response():
    response = run(message([], stop_reason="max_tokens"))
    assert response.blocks == () and response.text == "" and response.stop_reason == "max_tokens"


def test_empty_text_blocks_are_dropped():
    assert run(message([text(""), text("kept")])).blocks == (TextBlock("kept"),)


def test_thinking_and_unknown_blocks_are_ignored():
    content = [
        {"type": "thinking", "thinking": "private reasoning", "signature": "sig"},
        {"type": "redacted_thinking", "data": "xxxx"},
        {"type": "something_new", "data": 1},
        text("The answer."),
    ]
    response = run(message(content))
    assert response.blocks == (TextBlock("The answer."),) and "reasoning" not in repr(response)


def test_tool_input_that_is_not_an_object_becomes_empty_arguments_with_an_error():
    response = run(message([{"type": "tool_use", "id": "t1", "name": "x", "input": [1, 2]}], stop_reason="tool_use"))
    (call,) = response.tool_calls
    assert call.arguments == {} and call.error and "object" in call.error


def test_unicode_survives():
    assert run(message([text("café ✓ \U0001f41b")])).text == "café ✓ \U0001f41b"


# -- stop reasons ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("end_turn", "end_turn"), ("tool_use", "tool_use"), ("max_tokens", "max_tokens"), ("stop_sequence", "stop_sequence"),
        ("pause_turn", "other"), ("model_context_window_exceeded", "other"), ("something_new", "other"), (None, "other"),
    ],
)  # fmt: skip
def test_stop_reason_mapping(raw, expected):
    response = run(message([text("x")], stop_reason=raw))
    assert response.stop_reason == expected and response.raw_stop_reason == raw


def test_a_refusal_is_its_own_stop_reason_and_keeps_the_category():
    body = message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": "x"})
    response = run(body)
    assert response.stop_reason == "refusal" and response.raw_stop_reason == "refusal:cyber"
    assert response.blocks == ()


@pytest.mark.parametrize("details", [None, {}, {"type": "refusal", "category": None}])
def test_a_refusal_without_a_category(details):
    body = message([], stop_reason="refusal", stop_details=details)
    response = run(body)
    assert response.stop_reason == "refusal" and response.raw_stop_reason == "refusal"


def test_a_refusal_may_carry_partial_text():
    response = run(message([text("I cannot")], stop_reason="refusal"))
    assert response.stop_reason == "refusal" and response.text == "I cannot"


# -- usage ----------------------------------------------------------------------------------------------------


def test_usage_with_cache_tokens():
    usage = {"input_tokens": 12, "output_tokens": 30, "cache_creation_input_tokens": 400, "cache_read_input_tokens": 5000}
    response = run(message(usage=usage))
    assert (response.usage.input_tokens, response.usage.output_tokens) == (12, 30)
    assert (response.usage.cache_write_tokens, response.usage.cache_read_tokens) == (400, 5000)
    assert response.usage.prompt_tokens == 5412 and response.usage.total == 5442
    assert response.usage_estimated is False


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 7, "output_tokens": 3},
        {"input_tokens": 7, "output_tokens": 3, "cache_creation_input_tokens": None, "cache_read_input_tokens": None},
        {"input_tokens": 7, "output_tokens": 3, "cache_creation_input_tokens": -4, "cache_read_input_tokens": "lots"},
    ],
)
def test_missing_or_unusable_cache_counts_are_zero(usage):
    response = run(message(usage=usage))
    assert (response.usage.input_tokens, response.usage.output_tokens) == (7, 3)
    assert (response.usage.cache_write_tokens, response.usage.cache_read_tokens) == (0, 0)
    assert response.usage_estimated is False


def test_zero_usage_is_taken_at_face_value():
    response = run(message(usage={"input_tokens": 0, "output_tokens": 0}))
    assert response.usage.total == 0 and response.usage_estimated is False


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": 5}, {"output_tokens": 5}, {"input_tokens": -1, "output_tokens": 5}])
def test_absent_or_unusable_usage_is_estimated_and_flagged(usage):
    response = run(message([text("A reasonably long answer for the estimate.")], usage=usage))
    assert response.usage_estimated is True
    assert response.usage.input_tokens > 0 and response.usage.output_tokens > 0 and response.usage.cache_read_tokens == 0


# -- model, id, latency ------------------------------------------------------------------------------------------


def test_model_and_request_id():
    response = run(message(model="claude-haiku-5-5"))
    assert response.model == "claude-haiku-5-5" and response.request_id == "req_test_1"  # the request-id header wins


def test_request_id_falls_back_to_the_message_id():
    adapter, _ = adapter_for(lambda request: httpx2.Response(200, json=message(id="msg_77")))
    assert adapter.generate(REQUEST).request_id == "msg_77"


def test_latency_is_measured():
    assert run(message()).latency_s >= 0


def test_responses_are_valid_generation_responses():
    response = run(message([text("ok"), tool_use()], stop_reason="tool_use"))
    assert GenerationResponse.from_dict(response.to_dict()) == response
    assert isinstance(response.blocks[1], ToolCallBlock)


# -- malformed successful responses must never pass as an empty success -------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="<html>gateway page</html>"),
        httpx2.Response(200, text=""),
        httpx2.Response(200, json=[1, 2, 3]),
        httpx2.Response(200, json="a string"),
        httpx2.Response(200, json={}),
        httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "x", "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}),
        httpx2.Response(200, json=message(content="not a list")),
    ],
    ids=["html", "empty", "list", "string", "empty-object", "no-content", "content-not-a-list"],
)
def test_malformed_200_responses_are_a_bad_response(response):
    from bugbite.errors import BAD_RESPONSE, AdapterError

    adapter, _ = adapter_for(lambda request: response)
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value.code == BAD_RESPONSE and "api.anthropic.com" in info.value.message


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("overloaded_error", "server_error"), ("api_error", "server_error"), ("rate_limit_error", "rate_limited"),
        ("authentication_error", "auth_failed"), ("permission_error", "auth_failed"), ("billing_error", "auth_failed"),
        ("invalid_request_error", "invalid_request"), ("something_new_error", "bad_response"),
    ],
)  # fmt: skip
def test_an_error_body_inside_a_200_is_mapped_by_its_type(kind, expected):
    from bugbite.errors import AdapterError

    body = {"type": "error", "error": {"type": kind, "message": "details here"}}
    adapter, _ = adapter_for(lambda request: httpx2.Response(200, json=body))
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value.code == expected and "details here" in info.value.message


def test_an_error_body_inside_a_200_has_the_key_redacted():
    from bugbite.errors import AdapterError
    from claude_helpers import KEY

    body = {"type": "error", "error": {"type": "authentication_error", "message": f"bad key {KEY}"}}
    adapter, _ = adapter_for(lambda request: httpx2.Response(200, json=body))
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert KEY not in info.value.message
