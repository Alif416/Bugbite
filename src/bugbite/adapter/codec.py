"""Exact conversion between the neutral model types and plain JSON data (README FR10.1, FR14.7).

Used by the recorder (P22) and the replayer (P23). Decoding is strict: unknown keys, wrong types and
unknown block kinds are rejected, so a damaged or foreign recording is noticed instead of half-read.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bugbite.adapter.types import (
    GenerationRequest,
    GenerationResponse,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    Usage,
)
from bugbite.errors import AdapterError


class CodecError(ValueError):
    """The data is not a valid encoding of a model type."""


def canonical_json(value: Any) -> str:
    """One text form per value: sorted keys, no extra spaces, no NaN or infinity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _exact(where: str, data: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise CodecError(f"{where}: expected an object")
    if set(data) != keys:
        missing, extra = sorted(keys - set(data)), sorted(set(data) - keys)
        raise CodecError(f"{where}: bad keys (missing {missing}, unexpected {extra})")
    return data


# -- blocks -----------------------------------------------------------------------------------------------------------------


def block_to_dict(block: Any) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text, "cache": block.cache}
    if isinstance(block, ToolCallBlock):
        return {"type": "tool_call", "id": block.id, "name": block.name, "arguments": block.arguments, "error": block.error}
    if isinstance(block, ToolResultBlock):
        return {"type": "tool_result", "tool_call_id": block.tool_call_id, "content": block.content, "is_error": block.is_error}
    raise CodecError(f"cannot encode a block of type {type(block).__name__}")


def block_from_dict(data: Any) -> Any:
    if not isinstance(data, dict) or "type" not in data:
        raise CodecError("block: expected an object with a type")
    kind = data["type"]
    try:
        if kind == "text":
            d = _exact("text block", data, {"type", "text", "cache"})
            return TextBlock(d["text"], d["cache"])
        if kind == "tool_call":
            d = _exact("tool_call block", data, {"type", "id", "name", "arguments", "error"})
            return ToolCallBlock(d["id"], d["name"], d["arguments"], d["error"])
        if kind == "tool_result":
            d = _exact("tool_result block", data, {"type", "tool_call_id", "content", "is_error"})
            return ToolResultBlock(d["tool_call_id"], d["content"], d["is_error"])
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CodecError):
            raise
        raise CodecError(f"{kind} block: {exc}") from None
    raise CodecError(f"unknown block type {kind!r}")


# -- responses and errors ---------------------------------------------------------------------------------------------------------


def usage_to_dict(usage: Usage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
    }


def response_to_dict(response: GenerationResponse) -> dict[str, Any]:
    return {
        "blocks": [block_to_dict(b) for b in response.blocks],
        "stop_reason": response.stop_reason,
        "usage": usage_to_dict(response.usage),
        "model": response.model,
        "raw_stop_reason": response.raw_stop_reason,
        "latency_s": response.latency_s,
        "request_id": response.request_id,
        "usage_estimated": response.usage_estimated,
    }


def response_from_dict(data: Any) -> GenerationResponse:
    d = _exact("response", data, {"blocks", "stop_reason", "usage", "model", "raw_stop_reason", "latency_s", "request_id", "usage_estimated"})
    if not isinstance(d["blocks"], list):
        raise CodecError("response: blocks must be a list")
    usage = _exact("usage", d["usage"], {"input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"})
    try:
        return GenerationResponse(
            blocks=tuple(block_from_dict(b) for b in d["blocks"]), stop_reason=d["stop_reason"], usage=Usage(**usage), model=d["model"],
            raw_stop_reason=d["raw_stop_reason"], latency_s=d["latency_s"], request_id=d["request_id"], usage_estimated=d["usage_estimated"],
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CodecError):
            raise
        raise CodecError(f"response: {exc}") from None


def error_to_dict(error: AdapterError) -> dict[str, Any]:
    return {"code": error.code, "message": error.message, "retry_after_s": error.retry_after_s, "status_code": error.status_code}


def error_from_dict(data: Any) -> AdapterError:
    d = _exact("error", data, {"code", "message", "retry_after_s", "status_code"})
    try:
        return AdapterError(d["code"], d["message"], retry_after_s=d["retry_after_s"], status_code=d["status_code"])
    except (TypeError, ValueError) as exc:
        raise CodecError(f"error: {exc}") from None


# -- requests ----------------------------------------------------------------------------------------------------------------------


def request_to_dict(request: GenerationRequest) -> dict[str, Any]:
    return {
        "messages": [{"role": m.role, "blocks": [block_to_dict(b) for b in m.blocks]} for m in request.messages],
        "system": [block_to_dict(b) for b in request.system],
        "tools": [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in request.tools],
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
        "stop_sequences": list(request.stop_sequences),
    }


def request_from_dict(data: Any) -> GenerationRequest:
    d = _exact("request", data, {"messages", "system", "tools", "temperature", "max_output_tokens", "stop_sequences"})
    try:
        messages = tuple(Message(m["role"], tuple(block_from_dict(b) for b in m["blocks"])) for m in d["messages"])
        tools = tuple(ToolDefinition(t["name"], t["description"], t["parameters"]) for t in d["tools"])
        return GenerationRequest(
            messages=messages, system=tuple(block_from_dict(b) for b in d["system"]), tools=tools, temperature=d["temperature"],
            max_output_tokens=d["max_output_tokens"], stop_sequences=tuple(d["stop_sequences"]),
        )
    except (TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, CodecError):
            raise
        raise CodecError(f"request: {exc}") from None


def request_fingerprint(request: GenerationRequest) -> dict[str, Any]:
    """A small, stable summary of a request: the SHA-256 of its canonical JSON plus its size and counts."""
    text = canonical_json(request_to_dict(request))
    raw = text.encode("utf-8")
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "messages": len(request.messages),
        "system_blocks": len(request.system),
        "tools": len(request.tools),
        "max_output_tokens": request.max_output_tokens,
        "temperature": request.temperature,
        "stop_sequences": list(request.stop_sequences),
    }


def scrub_value(value: Any, scrub: Any) -> Any:
    """Apply `scrub` to every string (and dict key) in a JSON-like value."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {scrub(k) if isinstance(k, str) else k: scrub_value(v, scrub) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_value(v, scrub) for v in value]
    return value
