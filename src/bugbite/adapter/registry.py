"""Create adapters from model config. Adapters register themselves by provider name."""

from __future__ import annotations

from typing import Callable

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.ledger import CostLedger
from bugbite.adapter.metered import MeteredAdapter
from bugbite.adapter.privacy_guard import PrivacyGuardAdapter
from bugbite.adapter.recording import RecordingAdapter, RecordingSink
from bugbite.adapter.text_action import TextActionAdapter
from bugbite.config import ConfigError, ModelConfig
from bugbite.privacy import Sensitivity

AdapterFactory = Callable[[ModelConfig, "str | None"], ModelAdapter]

_factories: dict[str, AdapterFactory] = {}


def register_adapter(provider: str, factory: AdapterFactory) -> None:
    """Register the factory for a provider. The factory receives (model config, API key or None)."""
    if not isinstance(provider, str) or not provider:
        raise ConfigError("provider name must be a non-empty string")
    if provider in _factories:
        raise ConfigError(f"an adapter for provider '{provider}' is already registered")
    _factories[provider] = factory


def unregister_adapter(provider: str) -> None:
    _factories.pop(provider, None)


def registered_providers() -> list[str]:
    return sorted(_factories)


def create_adapter(
    model: ModelConfig,
    *,
    api_key: str | None = None,
    ledger: CostLedger | None = None,
    sensitivity: Sensitivity = Sensitivity.PRIVATE,
    recorder: RecordingSink | None = None,
    provider_adapter: ModelAdapter | None = None,
) -> ModelAdapter:
    """Build the adapter for a model.

    The caller reads the environment variable named by `model.api_key_env` and
    passes the key in; nothing here reads the environment. With a `ledger`, the adapter is
    wrapped so that every call's tokens and cost are recorded there. A model without native tool
    calling is wrapped so that it can still be given tools (the text-action fallback).

    `sensitivity` says what kind of data the job holds; the privacy guard (innermost layer) refuses
    every call that the rule forbids. It defaults to PRIVATE: forgetting to say what the data is
    makes a model that cannot take private code refuse instead of leak.

    With a `recorder` (a `bugbite.recorder.RunWriter`), every call to the provider is recorded by a layer directly
    above the provider adapter and inside the guard (AD-118).

    With a `provider_adapter`, it is used as the provider instead of building one from the registry, and no
    key is needed. The replayer passes its stand-in here, so the guard, metering, recording and text-action
    layers are the real ones (AD-124).
    """
    if provider_adapter is not None:
        provider = provider_adapter
    else:
        factory = _factories.get(model.provider)
        if factory is None:
            known = ", ".join(registered_providers()) or "none"
            raise ConfigError(
                f"no adapter is registered for provider '{model.provider}' (registered: {known})"
            )
        if model.api_key_env and not api_key:
            raise ConfigError(
                f"model '{model.name}' needs an API key: read the {model.api_key_env} environment variable and pass it as api_key"
            )
        provider = factory(model, api_key)
    if recorder is not None:
        provider = RecordingAdapter(provider, recorder)  # records what the provider really returned
    adapter = PrivacyGuardAdapter(provider, sensitivity)  # the last gate before the network
    if ledger is not None:
        adapter = MeteredAdapter(adapter, ledger)  # inside the text-action wrapper, so a repair is its own entry
    if not model.native_tool_calling:
        adapter = TextActionAdapter(adapter)  # the caller sees tool calling whatever the model supports
    return adapter
