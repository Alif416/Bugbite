"""A scripted adapter for tests: canned responses, no provider, no cost.

Used to build and test the agent loop, the recorder, and the replayer, and as
the reference implementation of the adapter contract.
"""

from __future__ import annotations

import threading
from typing import Callable, Sequence, Union

from bugbite.adapter.base import ModelAdapter, validate_request
from bugbite.adapter.types import (
    STOP_END_TURN,
    STOP_TOOL_USE,
    GenerationRequest,
    GenerationResponse,
    TextBlock,
    ToolCallBlock,
    Usage,
)
from bugbite.config import ModelConfig, Pricing
from bugbite.errors import AdapterError

ScriptStep = Union[
    GenerationResponse,
    AdapterError,
    Callable[[GenerationRequest], Union[GenerationResponse, AdapterError]],
]


class ScriptExhausted(Exception):
    """The adapter was called more times than the script has steps (a bug in the test)."""


def scripted_config(name: str = "scripted") -> ModelConfig:
    return ModelConfig(
        name=name,
        provider="scripted",
        base_url="http://scripted.invalid",
        model_name="scripted-model",
        context_window=100_000,
        native_tool_calling=True,
        pricing=Pricing.free(),
        per_issue_cap_usd=0.0,
        allow_private_code=True,
    )


def text_response(
    text: str,
    *,
    usage: Usage | None = None,
    model: str = "scripted-model",
    stop_reason: str = STOP_END_TURN,
) -> GenerationResponse:
    return GenerationResponse(
        blocks=(TextBlock(text),),
        stop_reason=stop_reason,
        usage=usage or Usage(input_tokens=10, output_tokens=5),
        model=model,
        raw_stop_reason=stop_reason,
    )


def tool_call_response(
    *calls: tuple[str, dict] | ToolCallBlock,
    text: str | None = None,
    usage: Usage | None = None,
    model: str = "scripted-model",
    first_id: int = 1,
) -> GenerationResponse:
    blocks: list[TextBlock | ToolCallBlock] = [TextBlock(text)] if text else []
    for offset, call in enumerate(calls):
        if isinstance(call, ToolCallBlock):
            blocks.append(call)
        else:
            name, arguments = call
            blocks.append(ToolCallBlock(id=f"call_{first_id + offset}", name=name, arguments=arguments))
    return GenerationResponse(
        blocks=tuple(blocks),
        stop_reason=STOP_TOOL_USE,
        usage=usage or Usage(input_tokens=10, output_tokens=5),
        model=model,
        raw_stop_reason="tool_use",
    )


class ScriptedAdapter(ModelAdapter):
    def __init__(self, config: ModelConfig | None, script: Sequence[ScriptStep]) -> None:
        super().__init__(config or scripted_config())
        self._script = list(script)
        self._next = 0
        self._lock = threading.Lock()
        self.calls: list[GenerationRequest] = []

    @property
    def remaining(self) -> int:
        return len(self._script) - self._next

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        validate_request(request)  # before consuming a step, like a real adapter before any network call
        with self._lock:
            if self._next >= len(self._script):
                raise ScriptExhausted(
                    f"the script has {len(self._script)} step(s) but the adapter was called {len(self._script) + 1} times"
                )
            step = self._script[self._next]
            self._next += 1
            self.calls.append(request)
        result = step(request) if callable(step) else step
        if isinstance(result, AdapterError):
            raise result
        return result
