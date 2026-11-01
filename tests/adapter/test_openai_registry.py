from pathlib import Path

import pytest
from chain_helpers import names, raw
from openai_helpers import KEY

from bugbite.adapter import OpenAICompatibleAdapter, TextActionAdapter, create_adapter, registered_providers
from bugbite.config import ConfigError, load_models_config

ROOT = Path(__file__).resolve().parents[2]
MODELS = load_models_config(ROOT / "config" / "models.yaml")


def test_importing_the_package_registers_the_provider():
    assert "openai_compatible" in registered_providers()


def test_create_adapter_builds_it_with_the_key():
    adapter = create_adapter(MODELS["groq-free"], api_key=KEY)
    assert isinstance(raw(adapter), OpenAICompatibleAdapter) and adapter.name == "groq-free"
    assert KEY not in repr(adapter)
    adapter.close()


def test_keyless_local_models_need_no_key():
    adapter = create_adapter(MODELS["local-free"])
    # local-free has no native tool calling, so it comes wrapped in the text-action fallback (P12)
    assert names(adapter) == ["TextActionAdapter", "PrivacyGuardAdapter", "OpenAICompatibleAdapter"]
    adapter.close()


def test_a_model_that_names_a_key_variable_requires_a_key():
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        create_adapter(MODELS["groq-free"])


def test_the_groq_entry_is_safe_and_honest_about_what_is_unverified():
    groq = MODELS["groq-free"]
    assert groq.allow_private_code is False  # hosted free tiers may train on prompts: public repos only
    assert groq.is_free and groq.per_issue_cap_usd == 0
    assert groq.api_key_env == "GROQ_API_KEY" and groq.base_url == "https://api.groq.com/openai/v1"
    block = (ROOT / "config" / "models.yaml").read_text().split("groq-free:")[1]
    assert "UNVERIFIED" in block
    for field in ("model_name", "context_window", "native_tool_calling"):
        line = next(line for line in block.splitlines() if line.strip().startswith(f"{field}:"))
        assert "confirm" in line, f"{field} must be marked as needing confirmation"


def test_env_example_lists_the_groq_key_without_a_value():
    lines = (ROOT / ".env.example").read_text().splitlines()
    assert "GROQ_API_KEY=" in lines
    assert not any("=" in l and l.split("=", 1)[1].strip() for l in lines if not l.startswith("#"))
