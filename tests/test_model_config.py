from pathlib import Path

import pytest
import yaml

from bugbite.config import SUPPORTED_PROVIDERS, ConfigError, ModelConfig, Pricing, load_models_config

ROOT = Path(__file__).resolve().parent.parent

BASE = {
    "provider": "claude",
    "base_url": "https://api.example.com",
    "model_name": "m",
    "context_window": 100_000,
    "native_tool_calling": True,
    "pricing": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 1.25, "as_of": "2026-11-01"},
    "per_issue_cap_usd": 0.1,
    "allow_private_code": False,
}


def load(tmp_path, **overrides):
    entry = {**BASE, **overrides}
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"models": {"m": entry}}))
    return load_models_config(path)["m"]


def test_new_fields_have_defaults(tmp_path):
    model = load(tmp_path)
    assert model.api_key_env is None
    assert model.max_output_tokens == 4096


def test_new_fields_load(tmp_path):
    model = load(tmp_path, api_key_env="MY_KEY_2", max_output_tokens=1024)
    assert (model.api_key_env, model.max_output_tokens) == ("MY_KEY_2", 1024)


def test_integration_follows_native_tool_calling(tmp_path):
    assert load(tmp_path, native_tool_calling=True).integration == "native"
    assert load(tmp_path, native_tool_calling=False).integration == "text_action"


def test_constructing_directly_keeps_working_without_the_new_fields():
    model = ModelConfig("n", "claude", "http://x", "m", 1000, True, Pricing.free(), 0, False)
    assert model.api_key_env is None and model.max_output_tokens == 4096


def test_default_output_cap_shrinks_for_small_context_windows(tmp_path):
    model = load(tmp_path, context_window=2000)
    assert 0 < model.max_output_tokens < 2000
    assert load(tmp_path, context_window=1).max_output_tokens == 1  # never zero


@pytest.mark.parametrize("provider", SUPPORTED_PROVIDERS)
def test_supported_providers_load(tmp_path, provider):
    assert load(tmp_path, provider=provider).provider == provider


@pytest.mark.parametrize("provider", ["openai", "anthropic", "Claude", "", "ollama"])
def test_unknown_provider_is_rejected_and_the_choices_are_listed(tmp_path, provider):
    with pytest.raises(ConfigError, match="provider") as info:
        load(tmp_path, provider=provider)
    assert "claude" in str(info.value) and "openai_compatible" in str(info.value)


@pytest.mark.parametrize("url", ["api.example.com", "ftp://x", "", "localhost:11434"])
def test_base_url_must_be_http(tmp_path, url):
    with pytest.raises(ConfigError, match="base_url"):
        load(tmp_path, base_url=url)


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "https://api.example.com"])
def test_http_and_https_urls_are_accepted(tmp_path, url):
    assert load(tmp_path, base_url=url).base_url == url


@pytest.mark.parametrize("window", [0, -5])
def test_context_window_must_be_positive(tmp_path, window):
    with pytest.raises(ConfigError, match="context_window"):
        load(tmp_path, context_window=window)


@pytest.mark.parametrize("limit", [0, -1])
def test_max_output_tokens_must_be_positive(tmp_path, limit):
    with pytest.raises(ConfigError, match="max_output_tokens"):
        load(tmp_path, max_output_tokens=limit)


@pytest.mark.parametrize("limit", [100_000, 200_000])
def test_max_output_tokens_must_be_smaller_than_the_context_window(tmp_path, limit):
    with pytest.raises(ConfigError, match="smaller than 'context_window'"):
        load(tmp_path, max_output_tokens=limit)


@pytest.mark.parametrize("limit", ["many", 1.5, True])
def test_max_output_tokens_type(tmp_path, limit):
    with pytest.raises(ConfigError, match="max_output_tokens"):
        load(tmp_path, max_output_tokens=limit)


@pytest.mark.parametrize("name", ["", "has space", "1STARTS_WITH_DIGIT", "bad-dash", 5, ["X"]])
def test_api_key_env_must_be_a_variable_name(tmp_path, name):
    with pytest.raises(ConfigError, match="api_key_env"):
        load(tmp_path, api_key_env=name)


def test_api_key_env_may_be_null_for_keyless_models(tmp_path):
    assert load(tmp_path, api_key_env=None).api_key_env is None


def test_unknown_fields_are_rejected_so_typos_do_not_pass_silently(tmp_path):
    with pytest.raises(ConfigError, match="max_output_token"):
        load(tmp_path, max_output_token=100)


def test_the_shipped_models_file_loads_with_the_new_fields():
    models = load_models_config(ROOT / "config" / "models.yaml")
    assert models["haiku"].api_key_env == "ANTHROPIC_API_KEY"
    assert models["haiku"].integration == "native"
    assert models["local-free"].api_key_env is None
    assert models["local-free"].integration == "text_action"
    assert all(m.provider in SUPPORTED_PROVIDERS for m in models.values())
    assert all(0 < m.max_output_tokens < m.context_window for m in models.values())


# -- prompt_caching ---------------------------------------------------------------------------------


def test_prompt_caching_defaults_to_auto(tmp_path):
    assert load(tmp_path).prompt_caching == "auto"


@pytest.mark.parametrize("mode", ["auto", "explicit", "off"])
def test_prompt_caching_modes_load(tmp_path, mode):
    assert load(tmp_path, prompt_caching=mode).prompt_caching == mode


@pytest.mark.parametrize("mode", ["on", "AUTO", "", None, True, 1])
def test_unknown_prompt_caching_modes_are_rejected(tmp_path, mode):
    with pytest.raises(ConfigError, match="prompt_caching") as info:
        load(tmp_path, prompt_caching=mode)
    assert "auto" in str(info.value) and "explicit" in str(info.value) and "off" in str(info.value)


def test_constructing_a_model_directly_defaults_to_auto():
    assert ModelConfig("n", "claude", "http://x", "m", 1000, True, 0, 0, 0, False).prompt_caching == "auto"
