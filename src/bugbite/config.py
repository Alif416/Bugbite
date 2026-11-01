"""Typed config loading and validation.

App and model settings come from YAML files. Secrets come only from
environment variables, never from YAML.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when a config file or secret is missing or invalid."""


# Providers that have (or will have) an adapter. Adding one means adding an adapter too.
SUPPORTED_PROVIDERS = ("claude", "openai_compatible")
DEFAULT_MAX_OUTPUT_TOKENS = 4096
PROMPT_CACHING_MODES = ("auto", "explicit", "off")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


MILLION = Decimal(1_000_000)
ZERO = Decimal(0)


def _money(value: Any) -> Decimal:
    """An exact decimal from a number or numeric text; `0.10` is exactly one tenth, never a binary float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"not a number: {value!r}")
    return Decimal(str(value))


@dataclass(frozen=True)
class RateCard:
    """Dollars per million tokens for each kind of token."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


@dataclass(frozen=True)
class LongPrompt:
    """A second rate card for calls whose prompt is longer than `over_tokens`."""

    over_tokens: int
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal

    @property
    def rates(self) -> RateCard:
        return RateCard(self.input, self.output, self.cache_read, self.cache_write)


@dataclass(frozen=True)
class Pricing:
    """What a model costs, in US dollars per million tokens, with where and when the numbers came from."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal
    long_prompt: LongPrompt | None = None
    as_of: str | None = None  # ISO date the prices were read from the provider
    source: str | None = None

    @classmethod
    def free(cls) -> "Pricing":
        return cls(ZERO, ZERO, ZERO, ZERO)

    @classmethod
    def of(
        cls,
        input: Any,
        output: Any,
        cache_read: Any = None,
        cache_write: Any = None,
        *,
        long_prompt: tuple[int, Any, Any, Any, Any] | None = None,
        as_of: str | None = None,
        source: str | None = None,
    ) -> "Pricing":
        """Build from plain numbers (for tests and code); cache rates default to the input rate."""
        base_in = _money(input)
        long = None
        if long_prompt is not None:
            over, l_in, l_out, l_read, l_write = long_prompt
            long = LongPrompt(over, _money(l_in), _money(l_out), _money(l_read), _money(l_write))
        return cls(
            base_in,
            _money(output),
            base_in if cache_read is None else _money(cache_read),
            base_in if cache_write is None else _money(cache_write),
            long,
            as_of,
            source,
        )

    @property
    def standard(self) -> RateCard:
        return RateCard(self.input, self.output, self.cache_read, self.cache_write)

    @property
    def is_free(self) -> bool:
        rates = [self.input, self.output, self.cache_read, self.cache_write]
        if self.long_prompt is not None:
            rates += [self.long_prompt.input, self.long_prompt.output, self.long_prompt.cache_read, self.long_prompt.cache_write]
        return all(rate == 0 for rate in rates)

    def age_days(self, today: datetime.date | None = None) -> int | None:
        """Days since the prices were read, or None if no date was recorded."""
        if self.as_of is None:
            return None
        return ((today or datetime.date.today()) - datetime.date.fromisoformat(self.as_of)).days


def pricing_is_stale(pricing: Pricing, today: datetime.date | None = None, max_age_days: int = 30) -> bool:
    """True if paid prices are undated or older than `max_age_days`. Free prices are never stale."""
    if pricing.is_free:
        return False
    age = pricing.age_days(today)
    return age is None or age > max_age_days


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: str
    base_url: str
    model_name: str
    context_window: int
    native_tool_calling: bool
    pricing: Pricing
    per_issue_cap_usd: float
    allow_private_code: bool
    api_key_env: str | None = None  # name of the environment variable holding the key; None for keyless models
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    prompt_caching: str = "auto"  # auto | explicit | off; ignored by providers without prompt caching

    @property
    def integration(self) -> str:
        """How tools are used with this model: natively or through the text-action fallback."""
        return "native" if self.native_tool_calling else "text_action"

    @property
    def is_free(self) -> bool:
        return self.pricing.is_free

    # Read-only conveniences: dollars per single token, at the standard rates.
    @property
    def price_per_input_token(self) -> Decimal:
        return self.pricing.input / MILLION

    @property
    def price_per_output_token(self) -> Decimal:
        return self.pricing.output / MILLION


@dataclass(frozen=True)
class AppConfig:
    default_model: str
    max_steps: int
    max_cost_usd: float
    max_wall_clock_s: int
    total_budget_usd: float


@dataclass(frozen=True)
class SandboxConfig:
    """Sandbox container settings. All values must be positive."""

    image: str = "bugbite-sandbox:py3.11-1"
    cpus: float = 1
    memory_mb: int = 2048
    pids_limit: int = 256
    command_timeout_s: int = 120
    max_output_bytes: int = 1_048_576
    max_lifetime_s: int = 1800
    workspace_mb: int = 2048  # soft cap on /workspace disk use
    setup_timeout_s: int = 900  # per clone/install step
    test_timeout_s: int = 300  # per full test run


_MODEL_FIELDS: dict[str, type | tuple[type, ...]] = {
    "provider": str,
    "base_url": str,
    "model_name": str,
    "context_window": int,
    "native_tool_calling": bool,
    "per_issue_cap_usd": (int, float),
    "allow_private_code": bool,
}
_OPTIONAL_MODEL_FIELDS = ("api_key_env", "max_output_tokens", "prompt_caching", "pricing")
_REMOVED_FIELDS = ("price_per_input_token", "price_per_output_token")
_NON_NEGATIVE = (
    "context_window",
    "per_issue_cap_usd",
)

_APP_FIELDS: dict[str, type | tuple[type, ...]] = {
    "default_model": str,
    "max_steps": int,
    "max_cost_usd": (int, float),
    "max_wall_clock_s": int,
    "total_budget_usd": (int, float),
}
_APP_NON_NEGATIVE = ("max_steps", "max_cost_usd", "max_wall_clock_s", "total_budget_usd")


def _read_yaml(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file ({exc.strerror})") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _check_fields(
    where: str,
    data: dict[str, Any],
    spec: dict[str, type | tuple[type, ...]],
    non_negative: tuple[str, ...],
) -> None:
    for field, expected in spec.items():
        if field not in data:
            raise ConfigError(f"{where}: missing required field '{field}'")
        value = data[field]
        # bool is a subclass of int; do not accept it for numeric fields.
        is_bool_ok = expected is bool or (isinstance(expected, tuple) and bool in expected)
        if not isinstance(value, expected) or (isinstance(value, bool) and not is_bool_ok):
            raise ConfigError(f"{where}: field '{field}' has the wrong type")
        if field in non_negative and value < 0:
            raise ConfigError(f"{where}: field '{field}' must not be negative")


_PRICING_KEYS = {"input", "output", "cache_read", "cache_write", "long_prompt", "as_of", "source"}
_LONG_PROMPT_KEYS = {"over_tokens", "input", "output", "cache_read", "cache_write"}


def _rate(where: str, block: dict[str, Any], key: str) -> Decimal:
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: '{key}' must be a number of dollars per million tokens")
    try:
        rate = Decimal(str(value))
    except InvalidOperation:  # pragma: no cover - str of an int/float always parses
        raise ConfigError(f"{where}: '{key}' is not a valid number") from None
    if not rate.is_finite():
        raise ConfigError(f"{where}: '{key}' must be a finite number")
    if rate < 0:
        raise ConfigError(f"{where}: '{key}' must not be negative")
    return rate


def _parse_pricing(where: str, raw: dict[str, Any]) -> Pricing:
    """Read the `pricing` block: dollars per million tokens, plus where and when the numbers came from."""
    for old in _REMOVED_FIELDS:
        if old in raw:
            raise ConfigError(f"{where}: field '{old}' was replaced by the 'pricing' block (dollars per million tokens)")
    if "pricing" not in raw:
        raise ConfigError(f"{where}: missing required field 'pricing' (free models write explicit zeros)")
    block = raw["pricing"]
    here = f"{where}: pricing"
    if not isinstance(block, dict):
        raise ConfigError(f"{here}: expected a mapping")
    unknown = sorted(str(k) for k in block if k not in _PRICING_KEYS)
    if unknown:
        raise ConfigError(f"{here}: unknown field '{unknown[0]}'")
    for key in ("input", "output"):
        if key not in block:
            raise ConfigError(f"{here}: missing required field '{key}'")
    needs_cache_rates = raw.get("provider") == "claude"  # Anthropic always bills cache reads and writes

    def card(section: dict[str, Any], label: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        rate_in, rate_out = _rate(label, section, "input"), _rate(label, section, "output")
        rates = {}
        for key in ("cache_read", "cache_write"):
            if key in section:
                rates[key] = _rate(label, section, key)
            elif needs_cache_rates:
                raise ConfigError(f"{label}: missing required field '{key}' (this provider bills cache tokens)")
            else:
                rates[key] = rate_in
        return rate_in, rate_out, rates["cache_read"], rates["cache_write"]

    rate_in, rate_out, cache_read, cache_write = card(block, here)

    long_prompt = None
    if "long_prompt" in block:
        section = block["long_prompt"]
        label = f"{here}.long_prompt"
        if not isinstance(section, dict):
            raise ConfigError(f"{label}: expected a mapping")
        unknown = sorted(str(k) for k in section if k not in _LONG_PROMPT_KEYS)
        if unknown:
            raise ConfigError(f"{label}: unknown field '{unknown[0]}'")
        for key in ("over_tokens", "input", "output"):
            if key not in section:
                raise ConfigError(f"{label}: missing required field '{key}'")
        over = section["over_tokens"]
        if isinstance(over, bool) or not isinstance(over, int) or over <= 0:
            raise ConfigError(f"{label}: 'over_tokens' must be a whole number greater than zero")
        long_prompt = LongPrompt(over, *card(section, label))

    as_of = block.get("as_of")
    if isinstance(as_of, datetime.datetime):
        raise ConfigError(f"{here}: 'as_of' must be a date such as 2026-11-01, not a date and time")
    if isinstance(as_of, datetime.date):
        as_of = as_of.isoformat()
    if as_of is not None:
        try:
            if not isinstance(as_of, str):
                raise ValueError
            datetime.date.fromisoformat(as_of)
        except ValueError:
            raise ConfigError(f"{here}: 'as_of' must be a real date such as 2026-11-01") from None
    source = block.get("source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ConfigError(f"{here}: 'source' must be a non-empty string")

    pricing = Pricing(rate_in, rate_out, cache_read, cache_write, long_prompt, as_of, source)
    if not pricing.is_free and as_of is None:
        raise ConfigError(f"{here}: 'as_of' is required for a model that costs money (the date the prices were read)")
    return pricing


def _check_model_values(where: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Check the values the adapters depend on, and return the optional fields to use."""
    if raw["provider"] not in SUPPORTED_PROVIDERS:
        known = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(f"{where}: field 'provider' must be one of: {known} (got {raw['provider']!r})")
    if not raw["base_url"].startswith(("http://", "https://")):
        raise ConfigError(f"{where}: field 'base_url' must start with http:// or https://")
    if raw["context_window"] <= 0:
        raise ConfigError(f"{where}: field 'context_window' must be greater than zero")

    extras: dict[str, Any] = {"pricing": _parse_pricing(where, raw)}
    key_env = raw.get("api_key_env")
    if key_env is not None:
        if not isinstance(key_env, str) or not _ENV_NAME.fullmatch(key_env):
            raise ConfigError(f"{where}: field 'api_key_env' must be an environment variable name")
        extras["api_key_env"] = key_env

    if "prompt_caching" in raw:
        mode = raw["prompt_caching"]
        if mode not in PROMPT_CACHING_MODES:
            raise ConfigError(f"{where}: field 'prompt_caching' must be one of: {', '.join(PROMPT_CACHING_MODES)}")
        extras["prompt_caching"] = mode

    if "max_output_tokens" in raw:
        limit = raw["max_output_tokens"]
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ConfigError(f"{where}: field 'max_output_tokens' has the wrong type")
        if limit <= 0:
            raise ConfigError(f"{where}: field 'max_output_tokens' must be greater than zero")
        if limit >= raw["context_window"]:
            raise ConfigError(f"{where}: field 'max_output_tokens' must be smaller than 'context_window'")
        extras["max_output_tokens"] = limit
    else:
        # The default must also fit small context windows.
        extras["max_output_tokens"] = min(DEFAULT_MAX_OUTPUT_TOKENS, raw["context_window"] // 2) or 1
    return extras


def load_models_config(path: str | Path) -> dict[str, ModelConfig]:
    path = Path(path)
    data = _read_yaml(path)
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise ConfigError(f"{path}: expected a non-empty 'models' mapping")
    result: dict[str, ModelConfig] = {}
    for name, raw in models.items():
        where = f"{path}: model '{name}'"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: expected a mapping")
        for old in _REMOVED_FIELDS:
            if old in raw:
                raise ConfigError(f"{where}: field '{old}' was replaced by the 'pricing' block (dollars per million tokens)")
        unknown = sorted(str(key) for key in raw if key not in _MODEL_FIELDS and key not in _OPTIONAL_MODEL_FIELDS)
        if unknown:
            raise ConfigError(f"{where}: unknown field '{unknown[0]}'")
        _check_fields(where, raw, _MODEL_FIELDS, _NON_NEGATIVE)
        extras = _check_model_values(where, raw)
        result[str(name)] = ModelConfig(
            name=str(name),
            provider=raw["provider"],
            base_url=raw["base_url"],
            model_name=raw["model_name"],
            context_window=raw["context_window"],
            native_tool_calling=raw["native_tool_calling"],
            per_issue_cap_usd=float(raw["per_issue_cap_usd"]),
            allow_private_code=raw["allow_private_code"],
            **extras,
        )
    return result


def load_app_config(
    path: str | Path, models: dict[str, ModelConfig] | None = None
) -> AppConfig:
    """Load app config. If `models` is given, `default_model` must be one of them."""
    path = Path(path)
    data = _read_yaml(path)
    _check_fields(str(path), data, _APP_FIELDS, _APP_NON_NEGATIVE)
    if models is not None and data["default_model"] not in models:
        raise ConfigError(
            f"{path}: default_model '{data['default_model']}' is not defined in the models config"
        )
    return AppConfig(
        default_model=data["default_model"],
        max_steps=data["max_steps"],
        max_cost_usd=float(data["max_cost_usd"]),
        max_wall_clock_s=data["max_wall_clock_s"],
        total_budget_usd=float(data["total_budget_usd"]),
    )


def load_sandbox_config(path: str | Path) -> SandboxConfig:
    """Load the optional `sandbox:` section of app.yaml, filling gaps from defaults."""
    path = Path(path)
    data = _read_yaml(path)
    section = data.get("sandbox")
    if section is None:
        return SandboxConfig()
    where = f"{path}: sandbox"
    if not isinstance(section, dict):
        raise ConfigError(f"{where}: expected a mapping")
    defaults = SandboxConfig()
    known = set(defaults.__dataclass_fields__)
    unknown = sorted(str(key) for key in section if key not in known)
    if unknown:
        raise ConfigError(f"{where}: unknown field '{unknown[0]}'")
    merged: dict[str, Any] = {**defaults.__dict__, **section}
    image = merged["image"]
    if not isinstance(image, str) or not image.strip():
        raise ConfigError(f"{where}: field 'image' must be a non-empty string")
    for field in known - {"image"}:
        value = merged[field]
        expected = (int, float) if field == "cpus" else int
        if isinstance(value, bool) or not isinstance(value, expected):
            raise ConfigError(f"{where}: field '{field}' has the wrong type")
        if value <= 0:
            raise ConfigError(f"{where}: field '{field}' must be greater than zero")
    return SandboxConfig(**merged)


def get_secret(name: str) -> str:
    """Read a secret from the environment. Never logs or echoes the value."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"secret '{name}' is not set in the environment")
    return value
