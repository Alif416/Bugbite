"""Typed config loading and validation.

App and model settings come from YAML files. Secrets come only from
environment variables, never from YAML.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when a config file or secret is missing or invalid."""


# Providers that have (or will have) an adapter. Adding one means adding an adapter too.
SUPPORTED_PROVIDERS = ("claude", "openai_compatible")
DEFAULT_MAX_OUTPUT_TOKENS = 4096
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ModelConfig:
    name: str
    provider: str
    base_url: str
    model_name: str
    context_window: int
    native_tool_calling: bool
    price_per_input_token: float
    price_per_output_token: float
    per_issue_cap_usd: float
    allow_private_code: bool
    api_key_env: str | None = None  # name of the environment variable holding the key; None for keyless models
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    @property
    def integration(self) -> str:
        """How tools are used with this model: natively or through the text-action fallback."""
        return "native" if self.native_tool_calling else "text_action"


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
    "price_per_input_token": (int, float),
    "price_per_output_token": (int, float),
    "per_issue_cap_usd": (int, float),
    "allow_private_code": bool,
}
_OPTIONAL_MODEL_FIELDS = ("api_key_env", "max_output_tokens")
_NON_NEGATIVE = (
    "context_window",
    "price_per_input_token",
    "price_per_output_token",
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


def _check_model_values(where: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Check the values the adapters depend on, and return the optional fields to use."""
    if raw["provider"] not in SUPPORTED_PROVIDERS:
        known = ", ".join(SUPPORTED_PROVIDERS)
        raise ConfigError(f"{where}: field 'provider' must be one of: {known} (got {raw['provider']!r})")
    if not raw["base_url"].startswith(("http://", "https://")):
        raise ConfigError(f"{where}: field 'base_url' must start with http:// or https://")
    if raw["context_window"] <= 0:
        raise ConfigError(f"{where}: field 'context_window' must be greater than zero")

    extras: dict[str, Any] = {}
    key_env = raw.get("api_key_env")
    if key_env is not None:
        if not isinstance(key_env, str) or not _ENV_NAME.fullmatch(key_env):
            raise ConfigError(f"{where}: field 'api_key_env' must be an environment variable name")
        extras["api_key_env"] = key_env

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
            price_per_input_token=float(raw["price_per_input_token"]),
            price_per_output_token=float(raw["price_per_output_token"]),
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
