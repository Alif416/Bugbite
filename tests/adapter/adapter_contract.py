"""Tests that every adapter must pass.

Subclass `AdapterContract` in a test module and implement the two hooks. Each
hook returns an adapter that will answer exactly one call as described. Real
adapters (P9, P10) point their hooks at a fake HTTP backend.
"""

import json

import pytest

from bugbite.adapter import (
    STOP_REASONS,
    GenerationRequest,
    GenerationResponse,
    Message,
    ModelAdapter,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    Usage,
)
from bugbite.errors import INVALID_REQUEST, AdapterError

READ_FILE = ToolDefinition(
    "read_file",
    "Read a file",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)


def simple_request(**overrides):
    values = dict(
        system=(TextBlock("You are a careful assistant.", cache=True),),
        messages=(Message.user("Say hello."),),
        temperature=0.0,
        max_output_tokens=256,
    )
    values.update(overrides)
    return GenerationRequest(**values)


def tool_request():
    return simple_request(messages=(Message.user("Read a.py"),), tools=(READ_FILE,))


class AdapterContract:
    def adapter_for_text(self) -> ModelAdapter:
        """An adapter whose next call returns a plain text answer."""
        raise NotImplementedError

    def adapter_for_tool_call(self) -> ModelAdapter:
        """An adapter whose next call returns one call of `read_file` with a `path`."""
        raise NotImplementedError

    # -- well-formed responses ---------------------------------------------------

    def test_text_response_is_well_formed(self):
        response = self.adapter_for_text().generate(simple_request())
        assert isinstance(response, GenerationResponse)
        assert response.text.strip()
        assert response.tool_calls == ()
        assert response.stop_reason in STOP_REASONS
        assert response.stop_reason == "end_turn"
        assert isinstance(response.usage, Usage)
        assert response.usage.output_tokens > 0
        assert response.usage.input_tokens + response.usage.cache_read_tokens + response.usage.cache_write_tokens > 0
        assert response.model
        assert response.latency_s >= 0

    def test_tool_call_response_is_well_formed(self):
        response = self.adapter_for_tool_call().generate(tool_request())
        assert response.stop_reason == "tool_use"
        assert len(response.tool_calls) >= 1
        call = response.tool_calls[0]
        assert call.id and call.name == "read_file"
        assert isinstance(call.arguments, dict) and call.arguments.get("path")
        assert call.error is None

    def test_tool_call_ids_are_unique_within_a_response(self):
        response = self.adapter_for_tool_call().generate(tool_request())
        ids = [c.id for c in response.tool_calls]
        assert len(ids) == len(set(ids))

    def test_responses_survive_a_json_round_trip(self):
        for adapter, request in ((self.adapter_for_text(), simple_request()), (self.adapter_for_tool_call(), tool_request())):
            response = adapter.generate(request)
            assert GenerationResponse.from_dict(json.loads(json.dumps(response.to_dict()))) == response

    def test_the_response_can_be_fed_back_as_history(self):
        adapter = self.adapter_for_tool_call()
        request = tool_request()
        response = adapter.generate(request)
        call = response.tool_calls[0]
        follow_up = GenerationRequest(
            system=request.system,
            tools=request.tools,
            messages=(
                *request.messages,
                Message.assistant(*response.blocks),
                Message.tool_results(ToolResultBlock(call.id, "print('hi')")),
            ),
        )
        from bugbite.adapter import validate_request

        validate_request(follow_up)  # the shape an adapter returns is the shape the loop sends back

    # -- invalid requests -----------------------------------------------------------

    @pytest.mark.parametrize(
        "bad",
        [
            lambda: GenerationRequest(messages=()),
            lambda: GenerationRequest(messages=(Message.assistant("hi"), Message.user("x"))),
            lambda: GenerationRequest(messages=(Message.user("a"), Message.user("b"))),
            lambda: GenerationRequest(messages=(Message.user("x"),), temperature=5),
            lambda: GenerationRequest(messages=(Message.user("x"),), max_output_tokens=0),
            lambda: GenerationRequest(messages=(Message.tool_results(ToolResultBlock("nope", "x")),)),
            lambda: GenerationRequest(
                messages=(Message.user("x"), Message.assistant(ToolCallBlock("c1", "read_file", {})), Message.user("no result")),
            ),
        ],
        ids=["empty", "starts-with-assistant", "same-role-twice", "bad-temperature", "bad-max-tokens", "orphan-result", "unanswered-call"],
    )
    def test_invalid_requests_are_rejected_before_anything_is_sent(self, bad):
        adapter = self.adapter_for_text()
        with pytest.raises(AdapterError) as info:
            adapter.generate(bad())
        assert info.value.code == INVALID_REQUEST
        # the adapter is still usable: the rejected request did not use up its one answer
        assert adapter.generate(simple_request()).text.strip()

    # -- behaviour that must hold for every adapter ----------------------------------

    def test_the_request_is_not_modified(self):
        request = tool_request()
        before = json.dumps(request.to_dict(), sort_keys=True)
        self.adapter_for_tool_call().generate(request)
        assert json.dumps(request.to_dict(), sort_keys=True) == before

    def test_name_and_token_estimate(self):
        adapter = self.adapter_for_text()
        assert adapter.name
        small = adapter.estimate_tokens(simple_request())
        large = adapter.estimate_tokens(simple_request(messages=(Message.user("word " * 4000),)))
        with_tools = adapter.estimate_tokens(tool_request())
        assert 0 < small < large
        assert with_tools > adapter.estimate_tokens(simple_request(messages=(Message.user("Read a.py"),)))

    def test_default_output_cap_comes_from_the_model_config(self):
        adapter = self.adapter_for_text()
        assert adapter.resolve_max_output_tokens(simple_request(max_output_tokens=None)) == adapter.config.max_output_tokens
        assert adapter.resolve_max_output_tokens(simple_request(max_output_tokens=99)) == 99
