from decimal import Decimal
from pathlib import Path

import pytest
from claude_helpers import KEY

from bugbite.adapter import ClaudeAdapter, create_adapter, registered_providers
from bugbite.config import ConfigError, load_models_config

ROOT = Path(__file__).resolve().parents[2]
MODELS = load_models_config(ROOT / "config" / "models.yaml")


def test_both_real_providers_are_registered():
    assert {"claude", "openai_compatible"} <= set(registered_providers())


def test_create_adapter_builds_the_claude_adapter_for_the_shipped_haiku_entry():
    adapter = create_adapter(MODELS["haiku"], api_key=KEY)
    try:
        assert isinstance(adapter, ClaudeAdapter) and adapter.name == "haiku"
        assert KEY not in repr(adapter)
    finally:
        adapter.close()


def test_a_key_is_required():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        create_adapter(MODELS["haiku"])


def test_the_shipped_haiku_entry_has_the_verified_values():
    haiku = MODELS["haiku"]
    assert haiku.provider == "claude" and haiku.model_name == "claude-haiku-5-5"
    assert haiku.base_url == "https://api.anthropic.com"
    assert haiku.context_window == 1_000_000
    assert (haiku.pricing.input, haiku.pricing.output) == (Decimal("0.10"), Decimal("0.50"))
    assert (haiku.pricing.cache_read, haiku.pricing.cache_write) == (Decimal("0.01"), Decimal("0.125"))
    assert haiku.api_key_env == "ANTHROPIC_API_KEY" and haiku.native_tool_calling is True
    assert haiku.prompt_caching == "auto" and haiku.allow_private_code is False
    assert 0 < haiku.max_output_tokens < haiku.context_window


def test_the_haiku_entry_records_where_its_numbers_came_from_and_when():
    pricing = MODELS["haiku"].pricing
    assert pricing.as_of == "2026-11-01"
    assert pricing.source and pricing.source.startswith("https://") and "pricing" in pricing.source
    block = (ROOT / "config" / "models.yaml").read_text().split("haiku:")[1].split("local-free:")[0]
    assert "official" in block.lower() and "re-check" in block.lower()
    assert "confirm" not in block  # nothing in this entry is an unverified placeholder any more


def test_the_haiku_entry_models_the_long_prompt_tier():
    long = MODELS["haiku"].pricing.long_prompt
    assert long is not None and long.over_tokens == 100_000
    assert (long.input, long.output) == (Decimal("0.50"), Decimal("2.50"))
    assert (long.cache_read, long.cache_write) == (Decimal("0.05"), Decimal("0.625"))
