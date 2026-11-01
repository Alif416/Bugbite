import pytest

from bugbite.adapter import (
    ModelAdapter,
    create_adapter,
    register_adapter,
    registered_providers,
    unregister_adapter,
)
from bugbite.adapter.testing import ScriptedAdapter
from bugbite.config import ConfigError, ModelConfig, Pricing


def config(provider="fake", api_key_env=None, name="m"):
    return ModelConfig(
        name=name, provider=provider, base_url="http://x", model_name="x", context_window=1000,
        native_tool_calling=True, pricing=Pricing.free(),
        per_issue_cap_usd=0, allow_private_code=True, api_key_env=api_key_env,
    )  # fmt: skip


@pytest.fixture
def fake_provider():
    seen = {}

    def factory(model, api_key):
        seen["model"], seen["api_key"] = model, api_key
        return ScriptedAdapter(model, [])

    register_adapter("fake", factory)
    yield seen
    unregister_adapter("fake")


def test_register_and_create(fake_provider):
    assert "fake" in registered_providers()
    adapter = create_adapter(config())
    assert isinstance(adapter, ModelAdapter)
    assert fake_provider["model"].name == "m"
    assert fake_provider["api_key"] is None


def test_the_key_passed_in_reaches_the_factory(fake_provider):
    create_adapter(config(api_key_env="FAKE_KEY"), api_key="secret-value")
    assert fake_provider["api_key"] == "secret-value"


def test_a_model_that_names_a_key_variable_requires_a_key(fake_provider):
    with pytest.raises(ConfigError, match="FAKE_KEY") as info:
        create_adapter(config(api_key_env="FAKE_KEY"))
    assert "secret" not in str(info.value)
    with pytest.raises(ConfigError):
        create_adapter(config(api_key_env="FAKE_KEY"), api_key="")


def test_nothing_is_read_from_the_environment(fake_provider, monkeypatch):
    monkeypatch.setenv("FAKE_KEY", "from-the-environment")
    with pytest.raises(ConfigError):
        create_adapter(config(api_key_env="FAKE_KEY"))  # the environment value is ignored on purpose
    create_adapter(config())
    assert fake_provider["api_key"] is None


def test_unknown_provider_names_it_and_lists_what_is_registered(fake_provider):
    with pytest.raises(ConfigError) as info:
        create_adapter(config(provider="nope"))
    assert "nope" in str(info.value) and "fake" in str(info.value)


def test_providers_without_an_adapter_yet_are_reported_clearly():
    # claude and openai_compatible are valid config values but get their adapters in later phases
    for provider in ("claude", "openai_compatible"):
        if provider not in registered_providers():
            with pytest.raises(ConfigError, match=provider):
                create_adapter(config(provider=provider))


def test_duplicate_registration_is_an_error(fake_provider):
    with pytest.raises(ConfigError, match="already registered"):
        register_adapter("fake", lambda model, key: ScriptedAdapter(model, []))


def test_unregister_removes_and_is_safe_twice():
    register_adapter("temp", lambda model, key: ScriptedAdapter(model, []))
    unregister_adapter("temp")
    unregister_adapter("temp")
    assert "temp" not in registered_providers()


@pytest.mark.parametrize("bad", ["", None, 5])
def test_provider_name_must_be_a_non_empty_string(bad):
    with pytest.raises(ConfigError):
        register_adapter(bad, lambda model, key: None)

