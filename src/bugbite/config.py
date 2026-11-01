"""Typed config loading and validation.

App and model settings come from YAML files. Secrets come only from
environment variables, never from YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Raised when a config file or secret is missing or invalid."""


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

    image: str = "python:3.11-slim"
    cpus: float = 1
    memory_mb: int = 2048
    pids_limit: int = 256
    command_timeout_s: int = 120
    max_output_bytes: int = 1_048_576
    max_lifetime_s: int = 1800
    workspace_mb: int = 1024


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
        _check_fields(where, raw, _MODEL_FIELDS, _NON_NEGATIVE)
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
