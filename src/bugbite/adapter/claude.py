"""Adapter for Claude, through the official Anthropic SDK.

Choices that differ from a plain chat API, each recorded in specs/decisions.md:
- the SDK's own retries are off (adapters never retry, AD-049/AD-058);
- no sampling parameter is ever sent, and only the default temperature is accepted (AD-059);
- thinking is turned off, so no thinking blocks enter the conversation (AD-060);
- prompt caching is controlled by the model's `prompt_caching` setting (AD-061).

The key is passed in by the caller. The SDK would otherwise fall back to
credentials in the environment, so building an adapter without a key is refused.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

import anthropic

from bugbite.adapter._http import parse_retry_after, redact, shorten
from bugbite.adapter.base import ModelAdapter, estimate_tokens, validate_request
from bugbite.adapter.registry import register_adapter, registered_providers
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    STOP_END_TURN,
    STOP_MAX_TOKENS,
    STOP_OTHER,
    STOP_REFUSAL,
    STOP_SEQUENCE,
    STOP_TOOL_USE,
    GenerationRequest,
    GenerationResponse,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
    Usage,
)
from bugbite.config import ConfigError, ModelConfig
from bugbite.errors import (
    AUTH_FAILED_MODEL,
    BAD_RESPONSE,
    CONTEXT_TOO_LONG,
    INVALID_REQUEST,
    NETWORK_ERROR_MODEL,
    RATE_LIMITED_MODEL,
    SERVER_ERROR_MODEL,
    TIMEOUT_MODEL,
    AdapterError,
)

PROVIDER = "claude"
DEFAULT_TEMPERATURE = 1.0  # Claude's own default, the only value its newer models accept
MAX_CACHE_MARKERS = 4  # the API's limit on cache breakpoints per request
EMPTY_PLACEHOLDER = "(empty)"  # the API rejects empty text blocks and empty messages

_CONTEXT_WORDING = (
    "prompt is too long",
    "context window",
    "context limit",
    "context length",
    "maximum context",
    "too many tokens",
)

_STOP_REASONS = {
    "end_turn": STOP_END_TURN,
    "tool_use": STOP_TOOL_USE,
    "max_tokens": STOP_MAX_TOKENS,
    "stop_sequence": STOP_SEQUENCE,
}


def _cache_control() -> dict[str, str]:
    return {"type": "ephemeral"}


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class ClaudeAdapter(ModelAdapter):
    def __init__(
        self,
        config: ModelConfig,
        api_key: str | None = None,
        *,
        timeout: float = 120.0,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        super().__init__(config)
        if not api_key:
            # Without this the SDK would quietly use a key or profile found in the environment.
            raise ConfigError(f"model '{config.name}' needs an API key; pass it in explicitly (nothing is read from the environment)")
        self._api_key = api_key
        self._timeout = timeout
        self._host = config.base_url.split("//", 1)[-1].split("/", 1)[0] or "the Claude API"
        # The SDK's own HTTP client follows redirects by default; the key must never travel to another host.
        self._client = client or anthropic.Anthropic(
            api_key=api_key,
            base_url=config.base_url,
            max_retries=0,
            timeout=timeout,
            http_client=anthropic.DefaultHttpxClient(follow_redirects=False),
        )

    def __repr__(self) -> str:  # never shows the key
        return f"ClaudeAdapter(model={self.config.name!r}, host={self._host!r}, prompt_caching={self.config.prompt_caching!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClaudeAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the call --------------------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        validate_request(request)
        if request.temperature is not None and request.temperature != DEFAULT_TEMPERATURE:
            raise AdapterError(
                INVALID_REQUEST,
                f"Model '{self.config.name}' only supports its default temperature; "
                f"leave temperature unset (or {DEFAULT_TEMPERATURE:g}), got {request.temperature!r}.",
            )
        kwargs = self._build_kwargs(request)
        started = time.monotonic()
        try:
            message = self._client.messages.create(**kwargs)
        except anthropic.APITimeoutError:
            raise AdapterError(TIMEOUT_MODEL, f"The request to {self._host} timed out.") from None
        except anthropic.APIConnectionError:
            raise AdapterError(NETWORK_ERROR_MODEL, f"Could not reach {self._host} (connection failed).") from None
        except anthropic.APIStatusError as exc:
            raise self._status_error(exc) from None
        except ValueError as exc:  # the SDK refuses some requests locally (for example very large non-streaming outputs)
            raise AdapterError(INVALID_REQUEST, f"The request was refused before it was sent: {shorten(redact(str(exc), self._api_key))}") from None
        except anthropic.AnthropicError as exc:
            raise AdapterError(BAD_RESPONSE, f"{self._host}: {shorten(redact(str(exc), self._api_key))}") from None
        self._check_message(message)
        return self._parse(message, request, time.monotonic() - started)

    # -- request translation -------------------------------------------------------------

    def _build_kwargs(self, request: GenerationRequest) -> dict[str, Any]:
        mode = self.config.prompt_caching
        candidates: list[dict[str, Any]] = []  # content blocks that were flagged for caching, in order

        def text_block(block: TextBlock) -> dict[str, Any]:
            entry: dict[str, Any] = {"type": "text", "text": block.text}
            if block.cache and mode != "off":
                candidates.append(entry)
            return entry

        system = [text_block(b) for b in request.system if b.text]

        messages: list[dict[str, Any]] = []
        for message in request.messages:
            content: list[dict[str, Any]] = []
            if message.role == ROLE_ASSISTANT:
                for block in message.blocks:
                    if isinstance(block, TextBlock) and block.text:
                        content.append(text_block(block))
                    elif isinstance(block, ToolCallBlock):
                        content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.arguments})
            else:
                # tool results must come first in a user message
                for block in message.blocks:
                    if isinstance(block, ToolResultBlock):
                        entry = {"type": "tool_result", "tool_use_id": block.tool_call_id}
                        if block.content:
                            entry["content"] = block.content
                        if block.is_error:
                            entry["is_error"] = True
                        content.append(entry)
                for block in message.blocks:
                    if isinstance(block, TextBlock) and block.text:
                        content.append(text_block(block))
            if not content:
                content.append({"type": "text", "text": EMPTY_PLACEHOLDER})
            messages.append({"role": message.role, "content": content})

        # At most four markers per request; the automatic one counts as one. When more blocks are
        # flagged, the last ones are kept: a later marker covers everything before it.
        budget = MAX_CACHE_MARKERS - (1 if mode == "auto" else 0)
        for entry in candidates[-budget:] if budget > 0 else []:
            entry["cache_control"] = _cache_control()

        kwargs: dict[str, Any] = {
            "model": self.config.model_name,
            "max_tokens": self.resolve_max_output_tokens(request),
            "messages": messages,
            "thinking": {"type": "disabled"},
            "timeout": self._timeout,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in request.tools
            ]
        if request.stop_sequences:
            kwargs["stop_sequences"] = list(request.stop_sequences)
        if mode == "auto":
            kwargs["cache_control"] = _cache_control()
        return kwargs

    # -- errors --------------------------------------------------------------------------------

    def _api_message(self, exc: anthropic.APIStatusError) -> str:
        """The API's own error text, taken from the parsed body (not the SDK's message, which repeats the whole body)."""
        body = exc.body
        text = ""
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                text = str(error.get("message") or "")
            elif isinstance(error, str):
                text = error
            elif isinstance(body.get("message"), str):
                text = body["message"]
        elif isinstance(body, str):
            text = body
        return shorten(redact(text, self._api_key))

    def _status_error(self, exc: anthropic.APIStatusError) -> AdapterError:
        status = exc.status_code
        message = self._api_message(exc)
        detail = f": {message}" if message else ""
        text = f"HTTP {status} from {self._host}{detail}"
        lowered = message.lower()
        retry_after = None
        try:
            retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
        except Exception:  # a missing response object must not hide the real error
            pass
        if status == 429:
            return AdapterError(RATE_LIMITED_MODEL, text, retry_after_s=retry_after, status_code=status)
        if status in (401, 402, 403):
            return AdapterError(AUTH_FAILED_MODEL, text, status_code=status)
        if status == 408:
            return AdapterError(TIMEOUT_MODEL, text, status_code=status)
        if status == 413 or (status in (400, 422) and any(w in lowered for w in _CONTEXT_WORDING)):
            return AdapterError(CONTEXT_TOO_LONG, text, status_code=status)
        if status >= 500:  # includes 529, overloaded
            return AdapterError(SERVER_ERROR_MODEL, text, retry_after_s=retry_after, status_code=status)
        if 400 <= status < 500:
            return AdapterError(INVALID_REQUEST, text, status_code=status)
        return AdapterError(BAD_RESPONSE, text, status_code=status)

    # -- response parsing ----------------------------------------------------------------------------

    def _check_message(self, message: Any) -> None:
        """The SDK returns odd objects for malformed 200 responses (a string, a list, a message
        with no content, even an error body); none of them may pass as an empty success."""
        if not isinstance(message, anthropic.types.Message):
            raise AdapterError(BAD_RESPONSE, f"{self._host} returned a response that is not a message.")
        if isinstance(getattr(message, "content", None), list):
            return
        error = getattr(message, "error", None)
        if getattr(message, "type", None) == "error" and isinstance(error, dict):
            kind = str(error.get("type") or "")
            text = shorten(redact(str(error.get("message") or ""), self._api_key))
            detail = f": {text}" if text else ""
            wording = f"{self._host} returned an error instead of a message ({kind or 'unknown'}){detail}"
            if kind == "rate_limit_error":
                raise AdapterError(RATE_LIMITED_MODEL, wording)
            if kind in ("overloaded_error", "api_error"):
                raise AdapterError(SERVER_ERROR_MODEL, wording)
            if kind in ("authentication_error", "permission_error", "billing_error"):
                raise AdapterError(AUTH_FAILED_MODEL, wording)
            if kind == "invalid_request_error":
                raise AdapterError(INVALID_REQUEST, wording)
            raise AdapterError(BAD_RESPONSE, wording)
        raise AdapterError(BAD_RESPONSE, f"{self._host} returned a message without content.")

    def _parse(self, message: Any, request: GenerationRequest, latency: float) -> GenerationResponse:
        blocks: list[TextBlock | ToolCallBlock] = []
        for block in getattr(message, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "text":
                if getattr(block, "text", ""):
                    blocks.append(TextBlock(block.text))
            elif kind == "tool_use":
                arguments = getattr(block, "input", None)
                error = None
                if not isinstance(arguments, dict):
                    arguments, error = {}, "tool input was not a JSON object"
                try:
                    blocks.append(ToolCallBlock(str(block.id), str(block.name), arguments, error))
                except ValueError:
                    blocks.append(ToolCallBlock(str(block.id), str(block.name), {}, "tool input held values JSON cannot carry"))
            # thinking, redacted thinking, and block types not understood are ignored

        raw = getattr(message, "stop_reason", None)
        raw_stop = raw if isinstance(raw, str) else None
        stop_reason = _STOP_REASONS.get(raw_stop or "", STOP_OTHER)
        if raw_stop == "refusal":
            stop_reason = STOP_REFUSAL
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raw_stop = f"refusal:{category}" if isinstance(category, str) and category else "refusal"

        usage, estimated = self._usage(getattr(message, "usage", None), request, blocks)
        model = getattr(message, "model", None)
        request_id = getattr(message, "_request_id", None) or getattr(message, "id", None)
        return GenerationResponse(
            blocks=tuple(blocks),
            stop_reason=stop_reason,
            usage=usage,
            model=model if isinstance(model, str) and model else self.config.model_name,
            raw_stop_reason=raw_stop,
            latency_s=latency,
            request_id=request_id if isinstance(request_id, str) and request_id else None,
            usage_estimated=estimated,
        )

    def _usage(self, raw: Any, request: GenerationRequest, blocks: list[TextBlock | ToolCallBlock]) -> tuple[Usage, bool]:
        # Claude's input_tokens already excludes cache reads and writes, which is how Usage defines it.
        input_tokens = _count(getattr(raw, "input_tokens", None))
        output_tokens = _count(getattr(raw, "output_tokens", None))
        if input_tokens is not None and output_tokens is not None:
            return (
                Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=_count(getattr(raw, "cache_read_input_tokens", None)) or 0,
                    cache_write_tokens=_count(getattr(raw, "cache_creation_input_tokens", None)) or 0,
                ),
                False,
            )
        chars = sum(len(b.text) if isinstance(b, TextBlock) else len(b.name) + len(json.dumps(b.arguments)) for b in blocks)
        return Usage(input_tokens=estimate_tokens(request), output_tokens=math.ceil(chars / 4)), True


def _factory(config: ModelConfig, api_key: str | None) -> ClaudeAdapter:
    return ClaudeAdapter(config, api_key)


if PROVIDER not in registered_providers():
    register_adapter(PROVIDER, _factory)
