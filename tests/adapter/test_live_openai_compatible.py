"""Opt-in checks against the real Groq free tier.

Runs only when BUGBITE_LIVE_TESTS=1 and GROQ_API_KEY are both set. It makes two
small calls, which count against the free tier's rate limits. If it was not run,
the P9 validation file must say so.
"""

import os
from pathlib import Path

import pytest

from bugbite.adapter import (
    GenerationRequest,
    Message,
    TextBlock,
    ToolDefinition,
    ToolResultBlock,
    create_adapter,
)
from bugbite.config import load_models_config

pytestmark = pytest.mark.skipif(
    os.environ.get("BUGBITE_LIVE_TESTS") != "1" or not os.environ.get("GROQ_API_KEY"),
    reason="live model tests are opt-in: set BUGBITE_LIVE_TESTS=1 and GROQ_API_KEY",
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def adapter():
    models = load_models_config(ROOT / "config" / "models.yaml")
    adapter = create_adapter(models["groq-free"], api_key=os.environ["GROQ_API_KEY"])
    yield adapter
    adapter.close()


def test_plain_text_call(adapter):
    request = GenerationRequest(
        system=(TextBlock("Answer in one short sentence."),),
        messages=(Message.user("What is the capital of France?"),),
        max_output_tokens=200,
    )
    response = adapter.generate(request)
    print(f"model={response.model} usage={response.usage} estimated={response.usage_estimated} latency={response.latency_s:.2f}s")
    assert "paris" in response.text.lower()
    assert response.stop_reason in ("end_turn", "max_tokens")
    assert response.usage.total > 0


def test_one_tool_call_and_the_follow_up(adapter):
    tool = ToolDefinition(
        "get_weather",
        "Get the current weather for a city.",
        {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    )
    request = GenerationRequest(messages=(Message.user("What is the weather in Paris? Use the tool."),), tools=(tool,), max_output_tokens=300)
    first = adapter.generate(request)
    assert first.stop_reason == "tool_use" and first.tool_calls
    call = first.tool_calls[0]
    assert call.name == "get_weather" and call.error is None
    follow_up = GenerationRequest(
        tools=(tool,),
        max_output_tokens=300,
        messages=(
            *request.messages,
            Message.assistant(*first.blocks),
            Message.tool_results(ToolResultBlock(call.id, "Sunny, 21 degrees C")),
        ),
    )
    second = adapter.generate(follow_up)
    assert second.text.strip() or second.tool_calls
