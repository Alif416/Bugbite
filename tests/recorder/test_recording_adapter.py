import json

import pytest
from rec_helpers import FakeTools, ProviderState, text_response, tool_call_response

from bugbite.adapter import (
    GenerationRequest, Message, RecordingAdapter, ToolCallBlock, create_adapter, register_adapter, unregister_adapter,
)
from bugbite.adapter.codec import request_fingerprint, request_to_dict, response_from_dict
from bugbite.adapter.testing import ScriptedAdapter
from bugbite.errors import AdapterError, PrivacyError
from bugbite.privacy import Sensitivity

REQUEST = GenerationRequest(messages=(Message.user("hello"),))


class Sink:
    def __init__(self, record_requests=False, fail_write=False):
        self.record_requests, self.events, self.errors, self.fail_write, self._n = record_requests, [], [], fail_write, 0

    def next_call_number(self):
        self._n += 1
        return self._n

    def write(self, event):
        if self.fail_write:
            raise OSError("disk full")
        self.events.append(event)
        return True

    def note_error(self, exc):
        self.errors.append(type(exc).__name__)


def wrap(script, **kw):
    sink = Sink(**kw)
    return RecordingAdapter(ScriptedAdapter(None, script), sink), sink


def test_the_same_response_object_comes_back_and_is_recorded_first():
    response = text_response("hi")
    adapter, sink = wrap([response])
    assert adapter.generate(REQUEST) is response
    [event] = sink.events
    assert event["type"] == "model_call" and event["call"] == 1 and "response" in event and "error" not in event
    assert response_from_dict(json.loads(json.dumps(event["response"]))) == response
    assert event["request"] == request_fingerprint(REQUEST) and "full" not in event["request"]


def test_the_same_error_object_is_raised_and_recorded():
    error = AdapterError("rate_limited", "slow down", retry_after_s=7, status_code=429)
    adapter, sink = wrap([error])
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    assert info.value is error
    assert sink.events[0]["error"] == {"code": "rate_limited", "message": "slow down", "retry_after_s": 7, "status_code": 429} and "response" not in sink.events[0]


def test_a_bug_in_the_provider_adapter_is_recorded_by_type_name_only_and_re_raised():
    def bug(request):
        raise ZeroDivisionError("TOPSECRET details")

    adapter, sink = wrap([bug])
    with pytest.raises(ZeroDivisionError):
        adapter.generate(REQUEST)
    assert sink.events[0]["exception"] == "ZeroDivisionError" and "TOPSECRET" not in json.dumps(sink.events)


def test_full_requests_are_stored_only_on_demand():
    adapter, sink = wrap([text_response("a")], record_requests=True)
    adapter.generate(REQUEST)
    assert sink.events[0]["request"]["full"] == request_to_dict(REQUEST)
    assert {k for k in sink.events[0]["request"]} == set(request_fingerprint(REQUEST)) | {"full"}


def test_calls_are_numbered_in_order_including_failures():
    adapter, sink = wrap([AdapterError("timeout", "t"), text_response("a"), AdapterError("timeout", "t"), text_response("b")])
    for _ in range(4):
        try:
            adapter.generate(REQUEST)
        except AdapterError:
            pass
    assert [e["call"] for e in sink.events] == [1, 2, 3, 4] and [("error" in e) for e in sink.events] == [True, False, True, False]


def test_a_failing_sink_never_breaks_a_call():
    response = text_response("fine")
    adapter, sink = wrap([response, AdapterError("timeout", "t")], fail_write=True)
    assert adapter.generate(REQUEST) is response
    with pytest.raises(AdapterError):
        adapter.generate(REQUEST)
    assert sink.errors == ["OSError", "OSError"]

    class Broken(Sink):
        def next_call_number(self):
            raise RuntimeError("x")

    adapter = RecordingAdapter(ScriptedAdapter(None, [response]), Broken())
    assert adapter.generate(REQUEST) is response  # goes ahead unrecorded


def test_it_looks_like_the_adapter_it_wraps():
    inner = ScriptedAdapter(None, [])
    adapter = RecordingAdapter(inner, Sink())
    assert adapter.config is inner.config and adapter.inner is inner and adapter.estimate_tokens(REQUEST) == inner.estimate_tokens(REQUEST)

    class Closable(ScriptedAdapter):
        closed = False

        def close(self):
            self.closed = True

    box = Closable(None, [])
    RecordingAdapter(box, Sink()).close()
    assert box.closed


# -- its place in the chain ----------------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_provider():
    state = ProviderState()
    register_adapter("chain_fake", lambda cfg, key: setattr(state, "raw", ScriptedAdapter(cfg, [text_response("ok")] * 5)) or state.raw)
    yield state
    unregister_adapter("chain_fake")


def cfg(allow):
    from rec_helpers import model
    from dataclasses import replace

    return replace(model(allow=allow), provider="chain_fake")


def test_the_recording_layer_is_directly_above_the_provider_and_inside_the_guard(fake_provider):
    from chain_helpers import names

    adapter = create_adapter(cfg(True), sensitivity=Sensitivity.PUBLIC, recorder=Sink())
    assert names(adapter) == ["PrivacyGuardAdapter", "RecordingAdapter", "ScriptedAdapter"]
    assert names(create_adapter(cfg(True), sensitivity=Sensitivity.PUBLIC)) == ["PrivacyGuardAdapter", "ScriptedAdapter"]  # nothing changes without a recorder


def test_a_call_the_guard_refuses_leaves_no_event(fake_provider):
    sink = Sink()
    adapter = create_adapter(cfg(False), recorder=sink)  # private data, a model that may not see it
    with pytest.raises(PrivacyError):
        adapter.generate(REQUEST)
    assert sink.events == [] and sink._n == 0 and fake_provider.raw.calls == []
    open_ = create_adapter(cfg(False), sensitivity=Sensitivity.PUBLIC, recorder=sink)
    open_.generate(REQUEST)
    assert len(sink.events) == 1
