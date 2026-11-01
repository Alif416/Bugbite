"""Adapter for any server that speaks the OpenAI chat completions API.

Covers any server, local or hosted, that offers this API. The request is built strictly
to the standard shape; the response is parsed tolerantly, because servers differ
in small ways. The key goes only in the Authorization header and only to the
configured host; redirects are not followed; there are no retries.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

import httpx

from bugbite.adapter._http import (  # noqa: F401  (parse_retry_after is re-exported for older imports)
    MAX_PROVIDER_MESSAGE_CHARS,
    parse_retry_after,
    redact,
    shorten as _shorten,
)
from bugbite.adapter.base import ModelAdapter, estimate_tokens, validate_request
from bugbite.adapter.registry import register_adapter, registered_providers
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    STOP_END_TURN,
    STOP_MAX_TOKENS,
    STOP_OTHER,
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

PROVIDER = "openai_compatible"

_CONTEXT_WORDING = (
    "context length",
    "context_length",
    "context window",
    "maximum context",
    "too many tokens",
    "reduce the length",
    "prompt is too long",
    "input is too long",
    "request too large",
    "token limit",
)

_FINISH_REASONS = {
    "stop": STOP_END_TURN,
    "length": STOP_MAX_TOKENS,
    "tool_calls": STOP_TOOL_USE,
    "function_call": STOP_TOOL_USE,
}


class OpenAICompatibleAdapter(ModelAdapter):
    def __init__(
        self,
        config: ModelConfig,
        api_key: str | None = None,
        *,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(config)
        self._api_key = api_key or None
        self._url = config.base_url.rstrip("/") + "/chat/completions"
        try:
            host = httpx.URL(config.base_url).host
        except httpx.InvalidURL:
            host = ""
        if not host:
            raise ConfigError(f"model '{config.name}': base_url is not a valid URL (it needs a host name)")
        self._host = host
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))

    def __repr__(self) -> str:  # never shows the key or any credentials inside the URL
        return (
            f"OpenAICompatibleAdapter(model={self.config.name!r}, host={self._host!r}, "
            f"authenticated={self._api_key is not None})"
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenAICompatibleAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the call ------------------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        validate_request(request)
        if request.tools and not self.config.native_tool_calling:
            raise AdapterError(
                INVALID_REQUEST,
                f"Model '{self.config.name}' has no native tool calling (integration: text_action); "
                "wrap it with the text-action adapter instead of sending tools directly.",
            )
        payload = self._build_payload(request)
        started = time.monotonic()
        response = self._post(payload)
        latency = time.monotonic() - started
        data = self._decode(response)
        return self._parse(data, request, latency, response.headers.get("x-request-id"))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "bugbite"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(self._url, json=payload, headers=self._headers(), follow_redirects=False)
        except httpx.TimeoutException:
            raise AdapterError(TIMEOUT_MODEL, f"The request to {self._host} timed out.") from None
        except httpx.InvalidURL:
            raise AdapterError(INVALID_REQUEST, f"The base_url for model '{self.config.name}' is not a valid URL.") from None
        except httpx.HTTPError:
            raise AdapterError(NETWORK_ERROR_MODEL, f"Could not reach {self._host} (connection failed).") from None

    # -- request translation -------------------------------------------------------------

    def _build_payload(self, request: GenerationRequest) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        system = "\n\n".join(block.text for block in request.system if block.text)
        if system:
            messages.append({"role": "system", "content": system})

        for message in request.messages:
            texts = [b.text for b in message.blocks if isinstance(b, TextBlock) and b.text]
            if message.role == ROLE_ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant", "content": "\n\n".join(texts)}
                calls = [b for b in message.blocks if isinstance(b, ToolCallBlock)]
                if calls:
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                        }
                        for c in calls
                    ]
                messages.append(entry)
                continue
            # tool results must directly follow the assistant message that made the calls
            results = [b for b in message.blocks if isinstance(b, ToolResultBlock)]
            for result in results:
                messages.append({"role": "tool", "tool_call_id": result.tool_call_id, "content": result.content})
            if texts or not results:
                messages.append({"role": "user", "content": "\n\n".join(texts)})

        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": self.resolve_max_output_tokens(request),
            "stream": False,
        }
        if request.temperature is not None:  # None means "the server's default"
            payload["temperature"] = request.temperature
        if request.stop_sequences:
            payload["stop"] = list(request.stop_sequences)
        if request.tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in request.tools
            ]
        return payload

    # -- errors --------------------------------------------------------------------------------

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        status = response.status_code
        if status >= 400:
            raise self._http_error(response)
        if 300 <= status < 400:
            raise AdapterError(BAD_RESPONSE, f"{self._host} answered with a redirect (HTTP {status}); redirects are not followed.", status_code=status)
        try:
            data = response.json()
        except ValueError:
            raise AdapterError(BAD_RESPONSE, f"{self._host} returned a response that is not JSON.", status_code=status) from None
        if not isinstance(data, dict):
            raise AdapterError(BAD_RESPONSE, f"{self._host} returned an unexpected response shape.", status_code=status)
        if data.get("error") and not data.get("choices"):
            message, code = self._error_details(data)
            raise self._classify(self._embedded_status(data), message, code, None)
        return data

    @staticmethod
    def _embedded_status(data: dict[str, Any]) -> int:
        """The HTTP-style status an error inside a 200 response carries, or 0 if it has none."""
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        return code if isinstance(code, int) and not isinstance(code, bool) and 400 <= code < 600 else 0

    def _redact(self, text: str) -> str:
        return redact(text, self._api_key)

    def _error_details(self, data: Any) -> tuple[str, str]:
        """Message and code from the common error body shapes."""
        message, code = "", ""
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
                code = str(error.get("code") or error.get("type") or "")
            elif isinstance(error, str):
                message = error
            elif isinstance(data.get("message"), str):
                message = data["message"]
        return _shorten(self._redact(message)), _shorten(self._redact(code), 80)

    def _http_error(self, response: httpx.Response) -> AdapterError:
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        if body is not None:
            message, code = self._error_details(body)
        else:
            message, code = _shorten(self._redact(response.text or "")), ""
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        return self._classify(response.status_code, message, code, retry_after)

    def _classify(self, status: int, message: str, code: str, retry_after: float | None) -> AdapterError:
        detail = f": {message}" if message else ""
        text = f"HTTP {status} from {self._host}{detail}" if status else f"{self._host} returned an error instead of a completion{detail}"
        lowered = f"{message} {code}".lower()
        if status == 429:
            return AdapterError(RATE_LIMITED_MODEL, text, retry_after_s=retry_after, status_code=status)
        if status in (401, 402, 403):
            return AdapterError(AUTH_FAILED_MODEL, text, status_code=status)
        if status == 408:
            return AdapterError(TIMEOUT_MODEL, text, status_code=status)
        if status == 413 or (status in (400, 422) and any(w in lowered for w in _CONTEXT_WORDING)):
            return AdapterError(CONTEXT_TOO_LONG, text, status_code=status)
        if status >= 500:
            return AdapterError(SERVER_ERROR_MODEL, text, status_code=status)
        if 400 <= status < 500:
            return AdapterError(INVALID_REQUEST, text, status_code=status)
        return AdapterError(BAD_RESPONSE, text, status_code=status)

    # -- response parsing --------------------------------------------------------------------

    def _bad(self, what: str) -> AdapterError:
        return AdapterError(BAD_RESPONSE, f"{self._host} returned an unexpected response: {what}.")

    def _parse(self, data: dict[str, Any], request: GenerationRequest, latency: float, header_id: str | None) -> GenerationResponse:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise self._bad("no choices")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise self._bad("the first choice has no message")

        text = self._content_text(message.get("content"))
        calls = self._tool_calls(message.get("tool_calls"))
        finish = choice.get("finish_reason")
        raw_finish = finish if isinstance(finish, str) else None
        stop_reason = _FINISH_REASONS.get(raw_finish or "", STOP_OTHER)
        if calls and stop_reason != STOP_MAX_TOKENS:
            stop_reason = STOP_TOOL_USE  # some servers say "stop" even when they return tool calls

        usage, estimated = self._usage(data.get("usage"), request, text, calls)
        blocks: list[TextBlock | ToolCallBlock] = ([TextBlock(text)] if text else []) + calls
        model = data.get("model")
        request_id = data.get("id") if isinstance(data.get("id"), str) and data.get("id") else header_id
        return GenerationResponse(
            blocks=tuple(blocks),
            stop_reason=stop_reason,
            usage=usage,
            model=model if isinstance(model, str) and model else self.config.model_name,
            raw_stop_reason=raw_finish,
            latency_s=latency,
            request_id=request_id,
            usage_estimated=estimated,
        )

    @staticmethod
    def _content_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # some servers return a list of parts
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            return "".join(parts)
        return ""

    def _tool_calls(self, raw: Any) -> list[ToolCallBlock]:
        if raw is None or raw == []:
            return []
        if not isinstance(raw, list):
            raise self._bad("tool_calls is not a list")
        provided = {
            item["id"] for item in raw if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        }
        used: set[str] = set()
        calls: list[ToolCallBlock] = []
        for index, item in enumerate(raw):
            function = item.get("function") if isinstance(item, dict) else None
            if not isinstance(function, dict):
                raise self._bad(f"tool_calls[{index}] has no function")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise self._bad(f"tool_calls[{index}] has no function name")
            given = item.get("id") if isinstance(item.get("id"), str) and item.get("id") else None
            # A missing id is generated and must not collide with any id the server did provide;
            # a repeated id gets a suffix so every id in the response is unique.
            call_id = self._unique_id(given or f"call_{index + 1}", used, set() if given else provided)
            arguments, error = self._arguments(function.get("arguments"))
            try:
                calls.append(ToolCallBlock(call_id, name, arguments, error))
            except ValueError:  # arguments held values JSON cannot carry (such as NaN)
                calls.append(ToolCallBlock(call_id, name, {}, "arguments contained values that are not valid JSON"))
        return calls

    @staticmethod
    def _unique_id(candidate: str, used: set[str], avoid: set[str]) -> str:
        result, suffix = candidate, 1
        while result in used or result in avoid:
            suffix += 1
            result = f"{candidate}_{suffix}"
        used.add(result)
        return result

    @staticmethod
    def _arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
        if raw is None or raw == "":
            return {}, None
        if isinstance(raw, dict):
            return raw, None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                return {}, f"arguments were not valid JSON ({exc.__class__.__name__}: {_shorten(str(exc), 80)})"
            if isinstance(parsed, dict):
                return parsed, None
            return {}, "arguments must be a JSON object"
        return {}, "arguments must be a JSON object or a string containing one"

    def _usage(self, raw: Any, request: GenerationRequest, text: str, calls: list[ToolCallBlock]) -> tuple[Usage, bool]:
        if isinstance(raw, dict):
            prompt, completion = raw.get("prompt_tokens"), raw.get("completion_tokens")
            if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (prompt, completion)):
                details = raw.get("prompt_tokens_details")
                cached = details.get("cached_tokens") if isinstance(details, dict) else 0
                if not (isinstance(cached, int) and not isinstance(cached, bool) and 0 <= cached <= prompt):
                    cached = 0
                return Usage(input_tokens=prompt - cached, output_tokens=completion, cache_read_tokens=cached), False
        output_chars = len(text) + sum(len(c.name) + len(json.dumps(c.arguments)) for c in calls)
        estimate = Usage(input_tokens=estimate_tokens(request), output_tokens=math.ceil(output_chars / 4))
        return estimate, True


def _factory(config: ModelConfig, api_key: str | None) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(config, api_key)


if PROVIDER not in registered_providers():
    register_adapter(PROVIDER, _factory)
