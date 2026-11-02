"""Rebuilding a model config from the plain copy in a manifest (the prices must come back exactly)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from bugbite.config import LongPrompt, ModelConfig, Pricing

from .errors import ReplayError

_MODEL_KEYS = {"name", "provider", "base_url", "model_name", "context_window", "native_tool_calling", "pricing", "per_issue_cap_usd",
               "allow_private_code", "api_key_env", "max_output_tokens", "prompt_caching"}
_PRICING_KEYS = {"input", "output", "cache_read", "cache_write", "long_prompt", "as_of", "source"}
_LONG_KEYS = {"over_tokens", "input", "output", "cache_read", "cache_write"}


def _money(where: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ReplayError(f"the manifest's {where} is not a price: {value!r}")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ReplayError(f"the manifest's {where} is not a price: {value!r}") from None


def _keys(where: str, data: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != keys:
        raise ReplayError(f"the manifest's {where} is malformed (expected the fields {sorted(keys)})")
    return data


def _check_types(d: dict[str, Any]) -> None:
    def whole(name: str) -> bool:
        return isinstance(d[name], int) and not isinstance(d[name], bool) and d[name] > 0

    problems = [name for name in ("name", "provider", "base_url", "model_name") if not isinstance(d[name], str) or not d[name]]
    problems += [name for name in ("context_window", "max_output_tokens") if not whole(name)]
    problems += [name for name in ("native_tool_calling", "allow_private_code") if not isinstance(d[name], bool)]
    if isinstance(d["per_issue_cap_usd"], bool) or not isinstance(d["per_issue_cap_usd"], (int, float)) or d["per_issue_cap_usd"] < 0:
        problems.append("per_issue_cap_usd")
    if d["api_key_env"] is not None and not isinstance(d["api_key_env"], str):
        problems.append("api_key_env")
    if d["prompt_caching"] not in ("auto", "explicit", "off"):
        problems.append("prompt_caching")
    if problems:
        raise ReplayError(f"the manifest's model is not usable: bad value for {', '.join(problems)}")


def model_from_manifest(data: Any) -> ModelConfig:
    """The `ModelConfig` a recording was made with. Raises `ReplayError` if the manifest's copy is malformed."""
    d = _keys("model", data, _MODEL_KEYS)
    p = _keys("model.pricing", d["pricing"], _PRICING_KEYS)
    long = None
    if p["long_prompt"] is not None:
        lp = _keys("model.pricing.long_prompt", p["long_prompt"], _LONG_KEYS)
        long = LongPrompt(lp["over_tokens"], *(_money(f"long_prompt.{k}", lp[k]) for k in ("input", "output", "cache_read", "cache_write")))
    pricing = Pricing(*(_money(f"pricing.{k}", p[k]) for k in ("input", "output", "cache_read", "cache_write")), long, p["as_of"], p["source"])
    _check_types(d)
    try:
        return ModelConfig(
            d["name"], d["provider"], d["base_url"], d["model_name"], d["context_window"], d["native_tool_calling"], pricing,
            d["per_issue_cap_usd"], d["allow_private_code"], d["api_key_env"], d["max_output_tokens"], d["prompt_caching"])
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"the manifest's model is not usable: {exc}") from None
