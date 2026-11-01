"""Opt-in checks against the real Claude API.

Runs only when BUGBITE_LIVE_TESTS=1 and ANTHROPIC_API_KEY are both set. It makes a handful of
small calls to Haiku 5.5 (a fraction of a cent in total) and prints usage and cost from the prices in
config/models.yaml. If it was not run, the P10 validation file must say so.
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
    Usage,
    compute_cost,
    create_adapter,
)
from bugbite.config import load_models_config

pytestmark = pytest.mark.skipif(
    os.environ.get("BUGBITE_LIVE_TESTS") != "1" or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="live model tests are opt-in: set BUGBITE_LIVE_TESTS=1 and ANTHROPIC_API_KEY",
)

ROOT = Path(__file__).resolve().parents[2]

def cost(usage: Usage) -> float:
    """Dollars for one call, from the prices in config/models.yaml (the same function the ledger uses)."""
    pricing = load_models_config(ROOT / "config" / "models.yaml")["haiku"].pricing
    return float(compute_cost(pricing, usage).total_usd)


def report(label, response):
    u = response.usage
    print(
        f"\n[{label}] model={response.model} stop={response.stop_reason} request_id={response.request_id} "
        f"in={u.input_tokens} out={u.output_tokens} cache_write={u.cache_write_tokens} cache_read={u.cache_read_tokens} "
        f"cost=${cost(u):.6f} latency={response.latency_s:.2f}s estimated={response.usage_estimated}"
    )


@pytest.fixture(scope="module")
def adapter():
    models = load_models_config(ROOT / "config" / "models.yaml")
    adapter = create_adapter(models["haiku"], api_key=os.environ["ANTHROPIC_API_KEY"])
    yield adapter
    adapter.close()


def test_plain_text_call(adapter):
    request = GenerationRequest(
        system=(TextBlock("Answer in one short sentence."),),
        messages=(Message.user("What is the capital of France?"),),
        max_output_tokens=200,
    )
    response = adapter.generate(request)
    report("text", response)
    assert "paris" in response.text.lower()
    assert response.stop_reason == "end_turn" and response.usage.total > 0 and not response.usage_estimated
    assert response.model.startswith("claude-haiku")


def test_tool_call_and_follow_up(adapter):
    tool = ToolDefinition(
        "get_weather",
        "Get the current weather for a city.",
        {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    )
    first_request = GenerationRequest(messages=(Message.user("What is the weather in Paris? Use the tool."),), tools=(tool,), max_output_tokens=300)
    first = adapter.generate(first_request)
    report("tool call", first)
    assert first.stop_reason == "tool_use" and first.tool_calls
    call = first.tool_calls[0]
    assert call.name == "get_weather" and call.error is None and "paris" in str(call.arguments).lower()

    second = adapter.generate(
        GenerationRequest(
            tools=(tool,),
            max_output_tokens=300,
            messages=(
                *first_request.messages,
                Message.assistant(*first.blocks),
                Message.tool_results(ToolResultBlock(call.id, "Sunny, 21 degrees C")),
            ),
        )
    )
    report("follow-up", second)
    assert second.text.strip() or second.tool_calls


def test_a_repeated_long_prefix_is_served_from_the_cache(adapter):
    paragraph = (
        "The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump. Sphinx of black quartz, judge my vow. "
    )
    long_context = (paragraph * 40) + "\nUnique marker for this run: bugbite-live-cache-check."
    request = GenerationRequest(
        system=(TextBlock(long_context, cache=True),),
        messages=(Message.user("Reply with the single word: ready."),),
        max_output_tokens=50,
    )
    first = adapter.generate(request)
    second = adapter.generate(request)
    report("cache first", first)
    report("cache second", second)
    assert first.usage.cache_write_tokens > 0 or first.usage.cache_read_tokens > 0
    assert second.usage.cache_read_tokens > 0, "the second identical call should have been served from the cache"
    assert cost(second.usage) < cost(first.usage)
