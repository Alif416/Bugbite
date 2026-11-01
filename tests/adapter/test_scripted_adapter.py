import threading

import pytest
from adapter_contract import AdapterContract, simple_request

from bugbite.adapter import GenerationRequest, Message, Usage
from bugbite.adapter.testing import (
    ScriptExhausted,
    ScriptedAdapter,
    scripted_config,
    text_response,
    tool_call_response,
)
from bugbite.errors import INVALID_REQUEST, RATE_LIMITED_MODEL, AdapterError


class TestScriptedAdapterContract(AdapterContract):
    """The reference adapter passes the same contract real adapters must pass."""

    def adapter_for_text(self):
        return ScriptedAdapter(None, [text_response("Hello there!")] * 10)

    def adapter_for_tool_call(self):
        return ScriptedAdapter(None, [tool_call_response(("read_file", {"path": "a.py"}))] * 10)


def req(text="hi"):
    return GenerationRequest(messages=(Message.user(text),))


def test_responses_come_back_in_order():
    adapter = ScriptedAdapter(None, [text_response("one"), text_response("two"), text_response("three")])
    assert [adapter.generate(req()).text for _ in range(3)] == ["one", "two", "three"]
    assert adapter.remaining == 0


def test_scripted_errors_are_raised_and_later_steps_still_work():
    error = AdapterError(RATE_LIMITED_MODEL, "slow down", retry_after_s=2, status_code=429)
    adapter = ScriptedAdapter(None, [text_response("a"), error, text_response("c")])
    assert adapter.generate(req()).text == "a"
    with pytest.raises(AdapterError) as info:
        adapter.generate(req())
    assert info.value is error and info.value.retry_after_s == 2
    assert adapter.generate(req()).text == "c"


def test_function_steps_see_the_request():
    adapter = ScriptedAdapter(None, [lambda request: text_response(request.messages[-1].blocks[0].text.upper())])
    assert adapter.generate(req("shout")).text == "SHOUT"


def test_function_steps_may_return_errors():
    adapter = ScriptedAdapter(None, [lambda request: AdapterError(INVALID_REQUEST, "nope")])
    with pytest.raises(AdapterError):
        adapter.generate(req())


def test_every_request_is_recorded():
    adapter = ScriptedAdapter(None, [text_response("a"), text_response("b")])
    first, second = req("first"), req("second")
    adapter.generate(first)
    adapter.generate(second)
    assert adapter.calls == [first, second]


def test_running_out_of_script_is_a_clear_error():
    adapter = ScriptedAdapter(None, [text_response("only")])
    adapter.generate(req())
    with pytest.raises(ScriptExhausted, match="1 step"):
        adapter.generate(req())


def test_an_empty_script_fails_on_the_first_call():
    with pytest.raises(ScriptExhausted):
        ScriptedAdapter(None, []).generate(req())


def test_invalid_requests_are_rejected_without_consuming_the_script():
    adapter = ScriptedAdapter(None, [text_response("kept")])
    with pytest.raises(AdapterError) as info:
        adapter.generate(GenerationRequest(messages=()))
    assert info.value.code == INVALID_REQUEST
    assert adapter.remaining == 1 and adapter.calls == []
    assert adapter.generate(req()).text == "kept"


def test_builders():
    assert text_response("x").stop_reason == "end_turn"
    response = tool_call_response(("a", {"k": 1}), ("b", {}), text="thinking", first_id=5)
    assert response.stop_reason == "tool_use"
    assert [c.id for c in response.tool_calls] == ["call_5", "call_6"]
    assert response.text == "thinking"
    custom = text_response("x", usage=Usage(input_tokens=1, output_tokens=2), model="other")
    assert custom.usage.total == 3 and custom.model == "other"


def test_config_defaults_and_name():
    adapter = ScriptedAdapter(None, [])
    assert adapter.name == "scripted" and adapter.config.provider == "scripted"
    assert ScriptedAdapter(scripted_config("custom"), []).name == "custom"


def test_concurrent_calls_each_get_a_distinct_step():
    adapter = ScriptedAdapter(None, [text_response(str(i)) for i in range(20)])
    seen, lock = [], threading.Lock()

    def work():
        text = adapter.generate(req()).text
        with lock:
            seen.append(text)

    threads = [threading.Thread(target=work) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(seen, key=int) == [str(i) for i in range(20)]
