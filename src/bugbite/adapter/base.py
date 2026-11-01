"""The adapter base class and the request checks every adapter shares."""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod

from bugbite.config import ModelConfig
from bugbite.errors import INVALID_REQUEST, AdapterError
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    ROLE_USER,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)

CHARS_PER_TOKEN = 4  # rough heuristic used by the default token estimate


def _invalid(message: str) -> AdapterError:
    return AdapterError(INVALID_REQUEST, message)


def validate_request(request: GenerationRequest) -> None:
    """Reject a malformed request before any network call, so it can never cost money.

    Raises `AdapterError("invalid_request")` with a message that says what is wrong.
    """
    messages = request.messages
    if not messages:
        raise _invalid("The request has no messages.")
    if messages[0].role != ROLE_USER:
        raise _invalid("The first message must be from the user.")
    if messages[-1].role != ROLE_USER:
        raise _invalid("The last message must be from the user, so the model has something to answer.")
    if isinstance(request.temperature, bool) or not (0 <= request.temperature <= 2):
        raise _invalid(f"temperature must be between 0 and 2, got {request.temperature!r}.")
    if request.max_output_tokens is not None and request.max_output_tokens <= 0:
        raise _invalid(f"max_output_tokens must be positive, got {request.max_output_tokens!r}.")

    names = [tool.name for tool in request.tools]
    if len(set(names)) != len(names):
        duplicate = next(n for n in names if names.count(n) > 1)
        raise _invalid(f"Tool names must be unique; '{duplicate}' appears more than once.")

    seen_call_ids: set[str] = set()
    for index, message in enumerate(messages):
        expected_role = ROLE_USER if index % 2 == 0 else ROLE_ASSISTANT
        if message.role != expected_role:
            raise _invalid(f"messages[{index}]: roles must alternate user, assistant, user, ...; found two {message.role} messages in a row.")
        _check_block_kinds(index, message)
        if message.role == ROLE_ASSISTANT:
            for block in message.blocks:
                if isinstance(block, ToolCallBlock):
                    if block.id in seen_call_ids:
                        raise _invalid(f"messages[{index}]: tool call id '{block.id}' is used more than once.")
                    seen_call_ids.add(block.id)

    # Tool calls and tool results must pair up with the message right before or after.
    for index, message in enumerate(messages):
        if message.role == ROLE_ASSISTANT:
            call_ids = [b.id for b in message.blocks if isinstance(b, ToolCallBlock)]
            if call_ids:
                answers = _result_ids(messages[index + 1])  # a following user message always exists (checked above)
                missing = [i for i in call_ids if i not in answers]
                if missing:
                    raise _invalid(f"messages[{index}]: tool call '{missing[0]}' is not answered by a tool result in the next message.")
        else:
            results = _result_ids(message)
            if not results:
                continue
            previous = messages[index - 1] if index > 0 else None
            offered = {b.id for b in previous.blocks if isinstance(b, ToolCallBlock)} if previous else set()
            for result_id in results:
                if result_id not in offered:
                    raise _invalid(f"messages[{index}]: tool result for '{result_id}' does not match a tool call in the previous message.")
            if len(set(results)) != len(results):
                raise _invalid(f"messages[{index}]: more than one tool result for the same tool call.")


def _check_block_kinds(index: int, message: Message) -> None:
    for block in message.blocks:
        if message.role == ROLE_ASSISTANT and isinstance(block, ToolResultBlock):
            raise _invalid(f"messages[{index}]: an assistant message cannot contain a tool result.")
        if message.role == ROLE_USER and isinstance(block, ToolCallBlock):
            raise _invalid(f"messages[{index}]: a user message cannot contain a tool call.")


def _result_ids(message: Message) -> list[str]:
    return [b.tool_call_id for b in message.blocks if isinstance(b, ToolResultBlock)]


def estimate_tokens(request: GenerationRequest) -> int:
    """A rough token count: characters divided by four, over everything sent to the model."""
    chars = sum(len(b.text) for b in request.system)
    for message in request.messages:
        for block in message.blocks:
            if isinstance(block, TextBlock):
                chars += len(block.text)
            elif isinstance(block, ToolCallBlock):
                chars += len(block.name) + len(json.dumps(block.arguments))
            else:
                chars += len(block.content)
    for tool in request.tools:
        chars += len(tool.name) + len(tool.description) + len(json.dumps(tool.parameters))
    return math.ceil(chars / CHARS_PER_TOKEN)


class ModelAdapter(ABC):
    """One way of talking to a model. Subclasses translate to and from a provider."""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Send one request and return one complete response.

        Implementations must call `validate_request` first, never retry, never
        modify the request, and raise `AdapterError` for provider failures.
        """

    def estimate_tokens(self, request: GenerationRequest) -> int:
        """Estimated prompt size; adapters with an exact counter can override this."""
        return estimate_tokens(request)

    def resolve_max_output_tokens(self, request: GenerationRequest) -> int:
        return request.max_output_tokens or self.config.max_output_tokens
