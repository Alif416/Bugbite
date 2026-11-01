"""Shared helpers for the OpenAI-compatible adapter tests."""

import json

import httpx

from bugbite.adapter import OpenAICompatibleAdapter
from bugbite.config import ModelConfig, Pricing

KEY = "sk-test-0123456789abcdef"
BASE_URL = "http://llm.test/v1"


def model(native=True, base_url=BASE_URL, key_env="LLM_KEY", **overrides):
    values = dict(
        name="free-model", provider="openai_compatible", base_url=base_url, model_name="vendor/model-7b",
        context_window=32_768, native_tool_calling=native, pricing=Pricing.free(),
        per_issue_cap_usd=0.0, allow_private_code=False,
        api_key_env=key_env, max_output_tokens=2048,
    )  # fmt: skip
    values.update(overrides)
    return ModelConfig(**values)


def completion(content="Hello there!", tool_calls=None, finish="stop", usage="default", **extra):
    """A typical chat completions response body."""
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body = {"id": "chatcmpl-1", "model": "vendor/model-7b", "choices": [{"index": 0, "message": message, "finish_reason": finish}]}
    if usage == "default":
        usage = {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}
    if usage is not None:
        body["usage"] = usage
    body.update(extra)
    return body


def tool_call(name="read_file", arguments='{"path": "a.py"}', id="call_abc", **extra):
    entry = {"type": "function", "function": {"name": name, "arguments": arguments}}
    if id is not None:
        entry["id"] = id
    entry.update(extra)
    return entry


class Recorder:
    """A mock transport handler that records requests and answers with `reply`."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        result = self.reply(request) if callable(self.reply) else self.reply
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json=result)

    @property
    def bodies(self):
        return [json.loads(r.content) for r in self.requests]

    @property
    def body(self):
        return self.bodies[-1]


def adapter_for(reply, *, key=KEY, config=None, **config_overrides):
    recorder = Recorder(reply)
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    adapter = OpenAICompatibleAdapter(config or model(**config_overrides), key, client=client)
    return adapter, recorder
