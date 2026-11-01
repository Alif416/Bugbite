from decimal import Decimal
from pathlib import Path

import pytest

from bugbite.agent import Limits, limits_from_config
from bugbite.config import load_app_config, load_models_config

ROOT = Path(__file__).resolve().parents[2]
APP = load_app_config(ROOT / "config" / "app.yaml")
MODELS = load_models_config(ROOT / "config" / "models.yaml")


def test_defaults_and_exact_decimals():
    limits = Limits(5)
    assert limits.max_steps == 5 and limits.max_cost_usd is None and limits.max_wall_clock_s is None
    assert limits.cost_margin == Decimal("1.25")
    assert Limits(5, max_cost_usd=0.1).max_cost_usd == Decimal("0.1")  # not 0.1000000000000000055...
    assert Limits(5, max_cost_usd="0.10").max_cost_usd == Decimal("0.10") and Limits(5, max_cost_usd=0).max_cost_usd == Decimal(0)
    assert Limits(5, max_wall_clock_s=600).max_wall_clock_s == 600.0 and isinstance(Limits(5, max_wall_clock_s=2).max_wall_clock_s, float)
    assert Limits(5, cost_margin=2).cost_margin == Decimal(2)


@pytest.mark.parametrize("steps", [0, -1, True, False, 1.5, None, "3"])
def test_bad_steps(steps):
    with pytest.raises(ValueError, match="max_steps"):
        Limits(steps)


@pytest.mark.parametrize("cost", [-0.01, "abc", True, [1], float("nan"), float("inf"), Decimal("NaN")])
def test_bad_cost(cost):
    with pytest.raises(ValueError, match="max_cost_usd"):
        Limits(3, max_cost_usd=cost)


@pytest.mark.parametrize("seconds", [0, -5, True, "x", float("inf")])
def test_bad_time(seconds):
    with pytest.raises(ValueError, match="max_wall_clock_s"):
        Limits(3, max_wall_clock_s=seconds)


@pytest.mark.parametrize("margin", [0.99, 0, -1, "x", True, float("nan")])
def test_bad_margin(margin):
    with pytest.raises(ValueError, match="cost_margin"):
        Limits(3, cost_margin=margin)


def test_limits_are_frozen():
    with pytest.raises(Exception):
        Limits(3).max_steps = 4  # type: ignore[misc]


def test_haiku_limits_come_from_the_shipped_config():
    limits = limits_from_config(APP, MODELS["haiku"])
    assert (limits.max_steps, limits.max_cost_usd, limits.max_wall_clock_s) == (30, Decimal("0.1"), 600.0)


def test_a_free_model_gets_a_cost_cap_of_zero():
    assert limits_from_config(APP, MODELS["local-free"]).max_cost_usd == Decimal(0)


def test_the_lower_of_the_two_cost_caps_wins_in_both_directions():
    from dataclasses import replace

    app_low = replace(APP, max_cost_usd=0.02)
    assert limits_from_config(app_low, MODELS["haiku"]).max_cost_usd == Decimal("0.02")  # app cap lower than the model's 0.10
    app_high = replace(APP, max_cost_usd=5)
    assert limits_from_config(app_high, MODELS["haiku"]).max_cost_usd == Decimal("0.1")  # model cap lower


@pytest.mark.parametrize("field, value", [("max_steps", 0), ("max_wall_clock_s", 0)])
def test_config_values_that_cannot_be_limits_name_the_field(field, value):
    from dataclasses import replace

    with pytest.raises(ValueError, match=field):
        limits_from_config(replace(APP, **{field: value}), MODELS["haiku"])
