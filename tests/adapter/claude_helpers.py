"""Shared helpers for the Claude adapter tests. Mocks run at the SDK's HTTP layer (httpx2)."""

import json

import anthropic
import httpx2

from bugbite.adapter import ClaudeAdapter
from bugbite.config import ModelConfig

KEY = "sk-ant-test-0123456789abcdef"


def model(base_url="https://api.anthropic.com", prompt_caching="auto", **overrides):
    values = dict(
        name="claude-model", provider="claude", base_url=base_url, model_name="claude-haiku-5-5",
        context_window=1_000_000, native_tool_calling=True, price_per_input_token=1e-7,
        price_per_output_token=5e-7, per_issue_cap_usd=0.1, allow_private_code=False,
        api_key_env="ANTHROPIC_API_KEY", max_output_tokens=2048, prompt_caching=prompt_caching,
    )  # fmt: skip
    values.update(overrides)
    return ModelConfig(**values)


def text(value="Hello there!"):
    return {"type": "text", "text": value}


def tool_use(name="read_file", input=None, id="toolu_01"):
    return {"type": "tool_use", "id": id, "name": name, "input": {"path": "a.py"} if input is None else input}


def message(content=None, stop_reason="end_turn", usage="default", **extra):
    """A typical Messages API response body."""
    body = {
        "id": "msg_01", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [text()] if content is None else content,
        "stop_reason": stop_reason, "stop_sequence": None,
    }  # fmt: skip
    if usage == "default":
        usage = {"input_tokens": 20, "output_tokens": 6, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    if usage is not None:
        body["usage"] = usage
    body.update(extra)
    return body


class Recorder:
    """A mock transport handler that records requests and answers with `reply`."""

    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        result = self.reply(request) if callable(self.reply) else self.reply
        if isinstance(result, httpx2.Response):
            return result
        return httpx2.Response(200, json=result, headers={"request-id": "req_test_1"})

    @property
    def bodies(self):
        return [json.loads(r.content) for r in self.requests]

    @property
    def body(self):
        return self.bodies[-1]


def adapter_for(reply, *, key=KEY, config=None, **config_overrides):
    """A ClaudeAdapter whose SDK client talks to a mock instead of the network."""
    recorder = Recorder(reply)
    cfg = config or model(**config_overrides)
    client = anthropic.Anthropic(
        api_key=key,
        base_url=cfg.base_url,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(recorder), follow_redirects=False),
    )
    return ClaudeAdapter(cfg, key, client=client), recorder
