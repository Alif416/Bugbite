from pathlib import Path

import pytest
import yaml

from bugbite.config import ConfigError, SandboxConfig, load_app_config, load_models_config, load_sandbox_config

ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path, data):
    path = tmp_path / "app.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_defaults():
    cfg = SandboxConfig()
    assert cfg.image == "python:3.11-slim"
    assert cfg.cpus == 1
    assert cfg.memory_mb == 2048
    assert cfg.pids_limit == 256
    assert cfg.command_timeout_s == 120
    assert cfg.max_output_bytes == 1_048_576
    assert cfg.max_lifetime_s == 1800
    assert cfg.workspace_mb == 1024


def test_no_section_gives_defaults(tmp_path):
    assert load_sandbox_config(write(tmp_path, {"default_model": "a"})) == SandboxConfig()


def test_partial_section_fills_from_defaults(tmp_path):
    cfg = load_sandbox_config(write(tmp_path, {"sandbox": {"memory_mb": 512, "cpus": 0.5}}))
    assert cfg.memory_mb == 512
    assert cfg.cpus == 0.5
    assert cfg.pids_limit == 256


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(ConfigError, match="memory_gb"):
        load_sandbox_config(write(tmp_path, {"sandbox": {"memory_gb": 2}}))


@pytest.mark.parametrize("field", ["cpus", "memory_mb", "pids_limit", "command_timeout_s", "max_output_bytes", "max_lifetime_s", "workspace_mb"])
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_rejected(tmp_path, field, value):
    with pytest.raises(ConfigError, match=field):
        load_sandbox_config(write(tmp_path, {"sandbox": {field: value}}))


@pytest.mark.parametrize("field", ["cpus", "memory_mb", "pids_limit"])
@pytest.mark.parametrize("value", ["lots", True, None])
def test_wrong_type_rejected(tmp_path, field, value):
    with pytest.raises(ConfigError, match=field):
        load_sandbox_config(write(tmp_path, {"sandbox": {field: value}}))


def test_float_for_integer_field_rejected(tmp_path):
    with pytest.raises(ConfigError, match="memory_mb"):
        load_sandbox_config(write(tmp_path, {"sandbox": {"memory_mb": 1.5}}))


@pytest.mark.parametrize("image", ["", "  ", 5])
def test_bad_image_rejected(tmp_path, image):
    with pytest.raises(ConfigError, match="image"):
        load_sandbox_config(write(tmp_path, {"sandbox": {"image": image}}))


def test_section_must_be_mapping(tmp_path):
    with pytest.raises(ConfigError, match="mapping"):
        load_sandbox_config(write(tmp_path, {"sandbox": ["a"]}))


def test_shipped_config_loads_and_matches_defaults():
    assert load_sandbox_config(ROOT / "config" / "app.yaml") == SandboxConfig()


def test_app_config_still_accepts_sandbox_section():
    models = load_models_config(ROOT / "config" / "models.yaml")
    assert load_app_config(ROOT / "config" / "app.yaml", models).default_model in models
