"""Create adapters from model config. Adapters register themselves by provider name."""

from __future__ import annotations

from typing import Callable

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.ledger import CostLedger
from bugbite.adapter.metered import MeteredAdapter
from bugbite.adapter.text_action import TextActionAdapter
from bugbite.config import ConfigError, ModelConfig

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


def create_adapter(model: ModelConfig, *, api_key: str | None = None, ledger: CostLedger | None = None) -> ModelAdapter:
    """Build the adapter for a model.

    The caller reads the environment variable named by `model.api_key_env` and
    passes the key in; nothing here reads the environment. With a `ledger`, the adapter is
    wrapped so that every call's tokens and cost are recorded there. A model without native tool
    calling is wrapped so that it can still be given tools (the text-action fallback).
    """
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
    adapter = factory(model, api_key)
    if ledger is not None:
        adapter = MeteredAdapter(adapter, ledger)  # inside the text-action wrapper, so a repair is its own entry
    if not model.native_tool_calling:
        adapter = TextActionAdapter(adapter)  # the caller sees tool calling whatever the model supports
    return adapter
