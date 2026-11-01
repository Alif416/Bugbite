"""Provider-neutral request and response types.

Every adapter translates between these and its provider's format. They convert
to and from JSON exactly (`to_dict` / `from_dict`), which is what recordings
for replay are made of. Standard library only.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Union

SCHEMA_VERSION = 1

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLES = (ROLE_USER, ROLE_ASSISTANT)

STOP_END_TURN = "end_turn"
STOP_TOOL_USE = "tool_use"
STOP_MAX_TOKENS = "max_tokens"
STOP_SEQUENCE = "stop_sequence"
STOP_OTHER = "other"
STOP_REASONS = frozenset({STOP_END_TURN, STOP_TOOL_USE, STOP_MAX_TOKENS, STOP_SEQUENCE, STOP_OTHER})

_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


class SchemaError(ValueError):
    """JSON could not be turned into a request or response (the message says where)."""


def _json_safe(value: Any, what: str) -> Any:
    """A deep copy of `value`, which must be JSON-serialisable."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be JSON-serialisable: {exc}") from None
    return copy.deepcopy(value)


def _tuple_of(items: Iterable[Any], kind: type | tuple[type, ...], what: str) -> tuple[Any, ...]:
    result = tuple(items)
    for index, item in enumerate(result):
        if not isinstance(item, kind):
            raise TypeError(f"{what}[{index}] must be {_names(kind)}, got {type(item).__name__}")
    return result


def _names(kind: type | tuple[type, ...]) -> str:
    kinds = kind if isinstance(kind, tuple) else (kind,)
    return " or ".join(k.__name__ for k in kinds)


# -- content blocks ------------------------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    text: str
    cache: bool = False  # ask the provider to cache the prompt up to here, if it supports caching

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("TextBlock.text must be a string")
        if not isinstance(self.cache, bool):
            raise TypeError("TextBlock.cache must be a bool")


@dataclass(frozen=True)
class ToolCallBlock:
    """A tool the model wants called. `error` is set if its arguments could not be parsed."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("ToolCallBlock.id must be a non-empty string")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("ToolCallBlock.name must be a non-empty string")
        if not isinstance(self.arguments, dict):
            raise TypeError("ToolCallBlock.arguments must be a dict")
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("ToolCallBlock.error must be a string or None")
        object.__setattr__(self, "arguments", _json_safe(self.arguments, "ToolCallBlock.arguments"))


@dataclass(frozen=True)
class ToolResultBlock:
    tool_call_id: str
    content: str
    is_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tool_call_id, str) or not self.tool_call_id:
            raise ValueError("ToolResultBlock.tool_call_id must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("ToolResultBlock.content must be a string")
        if not isinstance(self.is_error, bool):
            raise TypeError("ToolResultBlock.is_error must be a bool")


Block = Union[TextBlock, ToolCallBlock, ToolResultBlock]
_BLOCK_TYPES = (TextBlock, ToolCallBlock, ToolResultBlock)


@dataclass(frozen=True)
class Message:
    role: str
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"Message.role must be one of {ROLES}, got {self.role!r}")
        blocks = _tuple_of(self.blocks, _BLOCK_TYPES, "Message.blocks")
        if not blocks:
            raise ValueError("Message.blocks must not be empty")
        object.__setattr__(self, "blocks", blocks)

    @classmethod
    def user(cls, text: str, *, cache: bool = False) -> "Message":
        return cls(ROLE_USER, (TextBlock(text, cache),))

    @classmethod
    def assistant(cls, *blocks: Block | str) -> "Message":
        return cls(ROLE_ASSISTANT, tuple(TextBlock(b) if isinstance(b, str) else b for b in blocks))

    @classmethod
    def tool_results(cls, *results: ToolResultBlock) -> "Message":
        return cls(ROLE_USER, tuple(results))


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]  # a JSON Schema object

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _TOOL_NAME.fullmatch(self.name):
            raise ValueError(f"ToolDefinition.name must match [A-Za-z0-9_-]{{1,64}}, got {self.name!r}")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("ToolDefinition.description must be a non-empty string")
        if not isinstance(self.parameters, dict) or self.parameters.get("type") != "object":
            raise ValueError("ToolDefinition.parameters must be a JSON Schema object with type 'object'")
        object.__setattr__(self, "parameters", _json_safe(self.parameters, "ToolDefinition.parameters"))


# -- request and response --------------------------------------------------------


@dataclass(frozen=True)
class GenerationRequest:
    messages: tuple[Message, ...]
    system: tuple[TextBlock, ...] = ()
    tools: tuple[ToolDefinition, ...] = ()
    temperature: float = 0.0
    max_output_tokens: int | None = None
    stop_sequences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", _tuple_of(self.messages, Message, "GenerationRequest.messages"))
        object.__setattr__(self, "system", _tuple_of(self.system, TextBlock, "GenerationRequest.system"))
        object.__setattr__(self, "tools", _tuple_of(self.tools, ToolDefinition, "GenerationRequest.tools"))
        object.__setattr__(self, "stop_sequences", _tuple_of(self.stop_sequences, str, "GenerationRequest.stop_sequences"))
        if any(not seq for seq in self.stop_sequences):
            raise ValueError("stop sequences must not be empty")
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)):
            raise TypeError("GenerationRequest.temperature must be a number")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int)
        ):
            raise TypeError("GenerationRequest.max_output_tokens must be an int or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "system": [_block_to_dict(b) for b in self.system],
            "messages": [{"role": m.role, "blocks": [_block_to_dict(b) for b in m.blocks]} for m in self.messages],
            "tools": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in self.tools],
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "stop_sequences": list(self.stop_sequences),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GenerationRequest":
        d = _mapping(data, "request", {"schema_version", "system", "messages", "tools", "temperature", "max_output_tokens", "stop_sequences"})
        _check_version(d, "request")
        try:
            return cls(
                messages=tuple(
                    _message_from_dict(m, f"messages[{i}]") for i, m in enumerate(_list(d, "messages", "request"))
                ),
                system=tuple(
                    _text_block(_block_from_dict(b, f"system[{i}]"), f"system[{i}]")
                    for i, b in enumerate(_list(d, "system", "request"))
                ),
                tools=tuple(_tool_from_dict(t, f"tools[{i}]") for i, t in enumerate(_list(d, "tools", "request"))),
                temperature=_number(d, "temperature", "request"),
                max_output_tokens=_optional_int(d, "max_output_tokens", "request"),
                stop_sequences=tuple(_str_list(d, "stop_sequences", "request")),
            )
        except SchemaError:
            raise
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"request: {exc}") from None


@dataclass(frozen=True)
class Usage:
    """Token counts for one call.

    `input_tokens` are prompt tokens charged at the normal input rate and do not
    include tokens read from or written to the provider's prompt cache.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Usage.{name} must be a non-negative integer, got {value!r}")

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.output_tokens


@dataclass(frozen=True)
class GenerationResponse:
    blocks: tuple[TextBlock | ToolCallBlock, ...]
    stop_reason: str
    usage: Usage
    model: str
    raw_stop_reason: str | None = None  # the provider's own value, kept for debugging
    latency_s: float = 0.0
    request_id: str | None = None

    def __post_init__(self) -> None:
        blocks = _tuple_of(self.blocks, (TextBlock, ToolCallBlock), "GenerationResponse.blocks")
        object.__setattr__(self, "blocks", blocks)
        if self.stop_reason not in STOP_REASONS:
            raise ValueError(f"GenerationResponse.stop_reason must be one of {sorted(STOP_REASONS)}, got {self.stop_reason!r}")
        if not isinstance(self.usage, Usage):
            raise TypeError("GenerationResponse.usage must be a Usage")
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("GenerationResponse.model must be a non-empty string")
        if isinstance(self.latency_s, bool) or not isinstance(self.latency_s, (int, float)) or self.latency_s < 0:
            raise ValueError("GenerationResponse.latency_s must be a non-negative number")

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.blocks if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> tuple[ToolCallBlock, ...]:
        return tuple(b for b in self.blocks if isinstance(b, ToolCallBlock))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocks": [_block_to_dict(b) for b in self.blocks],
            "stop_reason": self.stop_reason,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cache_read_tokens": self.usage.cache_read_tokens,
                "cache_write_tokens": self.usage.cache_write_tokens,
            },
            "model": self.model,
            "raw_stop_reason": self.raw_stop_reason,
            "latency_s": self.latency_s,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GenerationResponse":
        d = _mapping(data, "response", {"schema_version", "blocks", "stop_reason", "usage", "model", "raw_stop_reason", "latency_s", "request_id"})
        _check_version(d, "response")
        usage = _mapping(d.get("usage"), "response.usage", set(_USAGE_KEYS))
        try:
            return cls(
                blocks=tuple(
                    _block_from_dict(b, f"blocks[{i}]") for i, b in enumerate(_list(d, "blocks", "response"))
                ),
                stop_reason=_string(d, "stop_reason", "response"),
                usage=Usage(*(_int(usage, k, "response.usage") for k in _USAGE_KEYS)),
                model=_string(d, "model", "response"),
                raw_stop_reason=_optional_string(d, "raw_stop_reason", "response"),
                latency_s=_number(d, "latency_s", "response"),
                request_id=_optional_string(d, "request_id", "response"),
            )
        except SchemaError:
            raise
        except (TypeError, ValueError) as exc:
            raise SchemaError(f"response: {exc}") from None


# -- JSON helpers --------------------------------------------------------------------


def _block_to_dict(block: Block) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text, "cache": block.cache}
    if isinstance(block, ToolCallBlock):
        return {"type": "tool_call", "id": block.id, "name": block.name, "arguments": block.arguments, "error": block.error}
    return {"type": "tool_result", "tool_call_id": block.tool_call_id, "content": block.content, "is_error": block.is_error}


_USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
_BLOCK_KEYS = {
    "text": {"type", "text", "cache"},
    "tool_call": {"type", "id", "name", "arguments", "error"},
    "tool_result": {"type", "tool_call_id", "content", "is_error"},
}


def _mapping(value: Any, where: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{where}: expected an object")
    extra = sorted(str(k) for k in value if k not in allowed)
    if extra:
        raise SchemaError(f"{where}: unknown field '{extra[0]}'")
    return value


def _check_version(d: dict[str, Any], where: str) -> None:
    if "schema_version" not in d:
        raise SchemaError(f"{where}: missing 'schema_version'")
    if d["schema_version"] != SCHEMA_VERSION:
        raise SchemaError(f"{where}: unsupported schema_version {d['schema_version']!r} (this code reads {SCHEMA_VERSION})")


def _field(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise SchemaError(f"{where}: missing field '{key}'")
    return d[key]


def _string(d: dict[str, Any], key: str, where: str) -> str:
    value = _field(d, key, where)
    if not isinstance(value, str):
        raise SchemaError(f"{where}: field '{key}' must be a string")
    return value


def _optional_string(d: dict[str, Any], key: str, where: str) -> str | None:
    value = _field(d, key, where)
    if value is not None and not isinstance(value, str):
        raise SchemaError(f"{where}: field '{key}' must be a string or null")
    return value


def _int(d: dict[str, Any], key: str, where: str) -> int:
    value = _field(d, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaError(f"{where}: field '{key}' must be an integer")
    return value


def _optional_int(d: dict[str, Any], key: str, where: str) -> int | None:
    value = _field(d, key, where)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise SchemaError(f"{where}: field '{key}' must be an integer or null")
    return value


def _number(d: dict[str, Any], key: str, where: str) -> float:
    value = _field(d, key, where)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaError(f"{where}: field '{key}' must be a number")
    return value


def _bool(d: dict[str, Any], key: str, where: str) -> bool:
    value = _field(d, key, where)
    if not isinstance(value, bool):
        raise SchemaError(f"{where}: field '{key}' must be true or false")
    return value


def _list(d: dict[str, Any], key: str, where: str) -> list[Any]:
    value = _field(d, key, where)
    if not isinstance(value, list):
        raise SchemaError(f"{where}: field '{key}' must be a list")
    return value


def _str_list(d: dict[str, Any], key: str, where: str) -> list[str]:
    items = _list(d, key, where)
    if not all(isinstance(i, str) for i in items):
        raise SchemaError(f"{where}: field '{key}' must be a list of strings")
    return items


def _block_from_dict(data: Any, where: str) -> Block:
    if not isinstance(data, dict):
        raise SchemaError(f"{where}: expected an object")
    kind = data.get("type")
    if kind not in _BLOCK_KEYS:
        raise SchemaError(f"{where}: unknown block type {kind!r}")
    d = _mapping(data, where, _BLOCK_KEYS[kind])
    try:
        if kind == "text":
            return TextBlock(_string(d, "text", where), _bool(d, "cache", where))
        if kind == "tool_call":
            arguments = _field(d, "arguments", where)
            if not isinstance(arguments, dict):
                raise SchemaError(f"{where}: field 'arguments' must be an object")
            return ToolCallBlock(_string(d, "id", where), _string(d, "name", where), arguments, _optional_string(d, "error", where))
        return ToolResultBlock(_string(d, "tool_call_id", where), _string(d, "content", where), _bool(d, "is_error", where))
    except SchemaError:
        raise
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{where}: {exc}") from None


def _text_block(block: Block, where: str) -> TextBlock:
    if not isinstance(block, TextBlock):
        raise SchemaError(f"{where}: only text blocks are allowed here")
    return block


def _message_from_dict(data: Any, where: str) -> Message:
    d = _mapping(data, where, {"role", "blocks"})
    role = _string(d, "role", where)
    blocks = tuple(_block_from_dict(b, f"{where}.blocks[{i}]") for i, b in enumerate(_list(d, "blocks", where)))
    try:
        return Message(role, blocks)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{where}: {exc}") from None


def _tool_from_dict(data: Any, where: str) -> ToolDefinition:
    d = _mapping(data, where, {"name", "description", "parameters"})
    parameters = _field(d, "parameters", where)
    if not isinstance(parameters, dict):
        raise SchemaError(f"{where}: field 'parameters' must be an object")
    try:
        return ToolDefinition(_string(d, "name", where), _string(d, "description", where), parameters)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"{where}: {exc}") from None
