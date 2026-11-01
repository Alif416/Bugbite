from pathlib import Path

import pytest
import yaml

from bugbite.config import (
    ConfigError,
    get_secret,
    load_app_config,
    load_models_config,
)

ROOT = Path(__file__).resolve().parent.parent

VALID_MODEL = {
    "provider": "p",
    "base_url": "http://x",
    "model_name": "m",
    "context_window": 1000,
    "native_tool_calling": True,
    "price_per_input_token": 0.1,
    "price_per_output_token": 0.2,
    "per_issue_cap_usd": 0.5,
    "allow_private_code": False,
}
VALID_APP = {
    "default_model": "a",
    "max_steps": 10,
    "max_cost_usd": 0.1,
    "max_wall_clock_s": 60,
    "total_budget_usd": 5,
}


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data))
    return path


def models_file(tmp_path, **overrides):
    model = {**VALID_MODEL, **overrides}
    return write(tmp_path, "models.yaml", {"models": {"a": model}})


def test_valid_models_load_with_all_fields(tmp_path):
    models = load_models_config(models_file(tmp_path))
    m = models["a"]
    assert m.name == "a"
    assert m.provider == "p"
    assert m.context_window == 1000
    assert m.native_tool_calling is True
    assert m.price_per_output_token == 0.2
    assert m.allow_private_code is False


def test_valid_app_loads(tmp_path):
    cfg = load_app_config(write(tmp_path, "app.yaml", VALID_APP))
    assert cfg.max_steps == 10
    assert cfg.total_budget_usd == 5.0


def test_missing_field_names_the_field(tmp_path):
    bad = {k: v for k, v in VALID_MODEL.items() if k != "context_window"}
    path = write(tmp_path, "models.yaml", {"models": {"a": bad}})
    with pytest.raises(ConfigError, match="context_window"):
        load_models_config(path)


def test_missing_app_field(tmp_path):
    bad = {k: v for k, v in VALID_APP.items() if k != "max_steps"}
    with pytest.raises(ConfigError, match="max_steps"):
        load_app_config(write(tmp_path, "app.yaml", bad))


def test_wrong_type(tmp_path):
    with pytest.raises(ConfigError, match="context_window"):
        load_models_config(models_file(tmp_path, context_window="big"))


def test_bool_rejected_for_numeric_field(tmp_path):
    with pytest.raises(ConfigError, match="per_issue_cap_usd"):
        load_models_config(models_file(tmp_path, per_issue_cap_usd=True))


@pytest.mark.parametrize(
    "field",
    ["price_per_input_token", "price_per_output_token", "per_issue_cap_usd"],
)
def test_negative_price_or_cap(tmp_path, field):
    with pytest.raises(ConfigError, match=field):
        load_models_config(models_file(tmp_path, **{field: -1}))


def test_negative_app_value(tmp_path):
    with pytest.raises(ConfigError, match="max_cost_usd"):
        load_app_config(write(tmp_path, "app.yaml", {**VALID_APP, "max_cost_usd": -0.1}))


def test_unknown_default_model(tmp_path):
    models = load_models_config(models_file(tmp_path))
    app = write(tmp_path, "app.yaml", {**VALID_APP, "default_model": "nope"})
    with pytest.raises(ConfigError, match="nope"):
        load_app_config(app, models)


def test_default_model_resolves(tmp_path):
    models = load_models_config(models_file(tmp_path))
    cfg = load_app_config(write(tmp_path, "app.yaml", VALID_APP), models)
    assert cfg.default_model in models


def test_unreadable_and_invalid_files(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_app_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_app_config(bad)


def test_secret_from_env(monkeypatch):
    monkeypatch.setenv("BUGBITE_TEST_SECRET", "s3cret")
    assert get_secret("BUGBITE_TEST_SECRET") == "s3cret"


def test_missing_secret_does_not_leak(monkeypatch):
    monkeypatch.delenv("BUGBITE_TEST_SECRET", raising=False)
    with pytest.raises(ConfigError, match="BUGBITE_TEST_SECRET"):
        get_secret("BUGBITE_TEST_SECRET")


def test_shipped_example_configs_are_valid():
    models = load_models_config(ROOT / "config" / "models.yaml")
    app = load_app_config(ROOT / "config" / "app.yaml", models)
    assert app.default_model in models
    free = [m for m in models.values() if m.price_per_input_token == 0]
    assert free, "expected at least one free-model entry"
