"""What the adapter understands from responses. Mock transport, no network."""

import httpx
import pytest
from openai_helpers import KEY, adapter_for, completion, model, tool_call

from bugbite.adapter import GenerationRequest, Message, TextBlock, ToolCallBlock
from bugbite.errors import BAD_RESPONSE, AdapterError

REQUEST = GenerationRequest(messages=(Message.user("hi"),))


def run(body, **kwargs):
    adapter, rec = adapter_for(body, **kwargs)
    return adapter.generate(REQUEST)


def failure(body, **kwargs):
    with pytest.raises(AdapterError) as info:
        run(body, **kwargs)
    return info.value


# -- text and content shapes ---------------------------------------------------------------


def test_plain_text():
    response = run(completion("Hello there!"))
    assert response.blocks == (TextBlock("Hello there!"),)
    assert response.text == "Hello there!" and response.tool_calls == ()
    assert response.stop_reason == "end_turn" and response.raw_stop_reason == "stop"


def test_null_content_with_tool_calls():
    response = run(completion(None, [tool_call()], finish="tool_calls"))
    assert response.text == "" and len(response.tool_calls) == 1
    assert all(isinstance(b, ToolCallBlock) for b in response.blocks)


def test_empty_string_content_gives_no_text_block():
    assert run(completion("")).blocks == ()


def test_content_given_as_a_list_of_parts():
    parts = [{"type": "text", "text": "Hello "}, {"type": "image_url", "image_url": {}}, "there", {"text": "!"}]
    assert run(completion(parts)).text == "Hello there!"


def test_unusual_content_types_are_treated_as_no_text():
    assert run(completion({"unexpected": "object"})).text == ""
    assert run(completion(12345)).text == ""


def test_reasoning_fields_are_ignored():
    body = completion("The answer.")
    body["choices"][0]["message"].update(reasoning="secret chain of thought", reasoning_content="more of it")
    response = run(body)
    assert response.text == "The answer." and "chain of thought" not in repr(response)


def test_only_the_first_choice_is_used():
    body = completion("first")
    body["choices"].append({"index": 1, "message": {"role": "assistant", "content": "second"}, "finish_reason": "stop"})
    assert run(body).text == "first"


# -- tool calls -------------------------------------------------------------------------------------


def calls_of(*entries):
    return run(completion(None, list(entries), finish="tool_calls")).tool_calls


def test_arguments_as_a_json_string():
    (call,) = calls_of(tool_call(arguments='{"path": "a.py", "n": [1, 2], "ok": true}'))
    assert call.arguments == {"path": "a.py", "n": [1, 2], "ok": True} and call.error is None
    assert (call.id, call.name) == ("call_abc", "read_file")


def test_arguments_as_an_object():
    (call,) = calls_of(tool_call(arguments={"path": "a.py"}))
    assert call.arguments == {"path": "a.py"} and call.error is None


@pytest.mark.parametrize("empty", ["", None, "{}"])
def test_empty_arguments_are_valid(empty):
    (call,) = calls_of(tool_call(arguments=empty))
    assert call.arguments == {} and call.error is None


def test_unicode_arguments_survive():
    (call,) = calls_of(tool_call(arguments='{"text": "caf\\u00e9 \\u2713 \\ud83d\\udc1b"}'))
    assert call.arguments == {"text": "café ✓ \U0001f41b"}


@pytest.mark.parametrize("broken", ['{"path": "a.py"', "not json", '{"a": }', "{'single': 'quotes'}"])
def test_invalid_json_arguments_become_empty_arguments_with_an_error(broken):
    (call,) = calls_of(tool_call(arguments=broken))
    assert call.arguments == {} and call.error and "not valid JSON" in call.error
    assert broken not in call.error  # the error describes the problem, it does not echo the text


@pytest.mark.parametrize("not_an_object, wording", [("[1, 2]", "JSON object"), ('"text"', "JSON object"), ("42", "JSON object"), (42, "JSON object"), ([1], "JSON object")])
def test_arguments_that_are_not_an_object(not_an_object, wording):
    (call,) = calls_of(tool_call(arguments=not_an_object))
    assert call.arguments == {} and wording in call.error


def test_nan_in_arguments_does_not_crash():
    (call,) = calls_of(tool_call(arguments='{"x": NaN}'))
    assert call.arguments == {} and call.error


def test_several_tool_calls_keep_their_order():
    first, second, third = calls_of(tool_call("a", id="x1"), tool_call("b", id="x2"), tool_call("c", id="x3"))
    assert [first.name, second.name, third.name] == ["a", "b", "c"]
    assert [first.id, second.id, third.id] == ["x1", "x2", "x3"]


def test_missing_ids_are_generated():
    a, b = calls_of(tool_call("a", id=None), tool_call("b", id=""))
    assert (a.id, b.id) == ("call_1", "call_2")


def test_generated_ids_never_collide_with_ids_the_server_provided():
    a, b = calls_of(tool_call("a", id=None), tool_call("b", id="call_1"))
    assert b.id == "call_1" and a.id != "call_1" and a.id.startswith("call_1")


def test_duplicate_ids_are_made_unique():
    a, b, c = calls_of(tool_call("a", id="same"), tool_call("b", id="same"), tool_call("c", id="same"))
    assert len({a.id, b.id, c.id}) == 3 and a.id == "same"


def test_a_tool_call_without_a_name_is_a_bad_response():
    for entry in (tool_call(name=""), {"id": "x", "type": "function", "function": {"arguments": "{}"}}):
        assert failure(completion(None, [entry], finish="tool_calls")).code == BAD_RESPONSE


@pytest.mark.parametrize("entry", ["text", 5, None, {"id": "x"}, {"id": "x", "function": "not a dict"}])
def test_malformed_tool_call_entries_are_a_bad_response(entry):
    assert failure(completion(None, [entry], finish="tool_calls")).code == BAD_RESPONSE


def test_tool_calls_that_are_not_a_list_are_a_bad_response():
    assert failure(completion(None, {"not": "a list"}, finish="tool_calls")).code == BAD_RESPONSE


def test_empty_tool_call_list_means_no_tool_calls():
    response = run(completion("done", [], finish="stop"))
    assert response.tool_calls == () and response.stop_reason == "end_turn"


# -- stop reasons --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "finish, expected",
    [("stop", "end_turn"), ("length", "max_tokens"), ("tool_calls", "tool_use"), ("function_call", "tool_use"),
     ("content_filter", "other"), ("something_new", "other"), (None, "other"), (5, "other")],
)  # fmt: skip
def test_stop_reason_mapping_without_tool_calls(finish, expected):
    response = run(completion("x", finish=finish))
    assert response.stop_reason == expected
    assert response.raw_stop_reason == (finish if isinstance(finish, str) else None)


def test_tool_calls_with_a_stop_finish_reason_are_tool_use():
    response = run(completion(None, [tool_call()], finish="stop"))
    assert response.stop_reason == "tool_use" and response.raw_stop_reason == "stop"


def test_tool_calls_cut_off_by_the_length_limit_stay_max_tokens():
    response = run(completion(None, [tool_call(arguments='{"path": "a')], finish="length"))
    assert response.stop_reason == "max_tokens" and response.tool_calls[0].error


# -- usage -------------------------------------------------------------------------------------------------


def test_reported_usage():
    response = run(completion(usage={"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}))
    assert (response.usage.input_tokens, response.usage.output_tokens, response.usage.cache_read_tokens) == (100, 25, 0)
    assert response.usage_estimated is False


def test_cached_tokens_are_subtracted_from_input_and_reported_as_cache_reads():
    usage = {"prompt_tokens": 100, "completion_tokens": 25, "prompt_tokens_details": {"cached_tokens": 60}}
    response = run(completion(usage=usage))
    assert response.usage.input_tokens == 40 and response.usage.cache_read_tokens == 60
    assert response.usage.prompt_tokens == 100 and response.usage.total == 125


@pytest.mark.parametrize("cached", [-1, 101, 1.5, "10", True, None])
def test_implausible_cached_token_counts_are_ignored(cached):
    usage = {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": cached}}
    response = run(completion(usage=usage))
    assert response.usage.input_tokens == 100 and response.usage.cache_read_tokens == 0
    assert response.usage_estimated is False


@pytest.mark.parametrize(
    "usage",
    [None, {}, {"prompt_tokens": 10}, {"completion_tokens": 5}, {"prompt_tokens": -1, "completion_tokens": 5},
     {"prompt_tokens": 1.5, "completion_tokens": 5}, {"prompt_tokens": True, "completion_tokens": 5},
     {"prompt_tokens": "10", "completion_tokens": 5}, "usage", [1, 2]],
)  # fmt: skip
def test_missing_or_unusable_usage_is_estimated_and_flagged(usage):
    response = run(completion("A reasonably long answer for the estimate.", usage=usage))
    assert response.usage_estimated is True
    assert response.usage.input_tokens > 0 and response.usage.output_tokens > 0
    assert response.usage.cache_read_tokens == 0


def test_the_estimate_counts_tool_calls_as_output():
    response = run(completion(None, [tool_call(arguments='{"path": "a_long_path/to/file.py"}')], finish="tool_calls", usage=None))
    assert response.usage_estimated and response.usage.output_tokens > 0


def test_zero_reported_usage_is_taken_at_face_value():
    response = run(completion(usage={"prompt_tokens": 0, "completion_tokens": 0}))
    assert response.usage.total == 0 and response.usage_estimated is False


# -- model, id, latency ---------------------------------------------------------------------------------------


def test_model_and_request_id_come_from_the_body():
    response = run(completion(model="served-model-v2", id="chatcmpl-77"))
    assert (response.model, response.request_id) == ("served-model-v2", "chatcmpl-77")


def test_model_falls_back_to_the_config_and_id_to_the_header():
    body = completion()
    del body["model"], body["id"]
    adapter, _ = adapter_for(lambda request: httpx.Response(200, json=body, headers={"x-request-id": "req-header-1"}))
    response = adapter.generate(REQUEST)
    assert response.model == "vendor/model-7b" and response.request_id == "req-header-1"


def test_no_request_id_anywhere_is_none():
    body = completion()
    del body["id"]
    assert run(body).request_id is None


def test_latency_is_measured():
    assert run(completion()).latency_s >= 0


# -- structurally broken responses ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [{}, {"choices": []}, {"choices": "none"}, {"choices": [None]}, {"choices": ["text"]},
     {"choices": [{"finish_reason": "stop"}]}, {"choices": [{"message": "not a dict"}]}, {"choices": [{"message": None}]}],
)  # fmt: skip
def test_responses_without_a_usable_choice_are_a_bad_response(body):
    error = failure(body)
    assert error.code == BAD_RESPONSE and "llm.test" in error.message


def test_responses_are_parsed_into_valid_generation_responses():
    response = run(completion("ok"))
    from bugbite.adapter import GenerationResponse

    assert GenerationResponse.from_dict(response.to_dict()) == response


def test_the_key_is_not_in_the_repr_or_str_of_the_adapter():
    adapter, _ = adapter_for(completion())
    assert KEY not in repr(adapter) and KEY not in str(adapter)
    assert "authenticated=True" in repr(adapter)
    keyless, _ = adapter_for(completion(), key=None)
    assert "authenticated=False" in repr(keyless)


def test_credentials_in_the_base_url_do_not_appear_in_the_repr():
    adapter, _ = adapter_for(completion(), config=model(base_url="http://user:hunter2@llm.test/v1"))
    assert "hunter2" not in repr(adapter) and "user" not in repr(adapter)
