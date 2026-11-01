"""The `pricing` block of a model entry: parsing, exact decimals, and every rejection."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from bugbite.config import ConfigError, Pricing, load_models_config, pricing_is_stale

ROOT = Path(__file__).resolve().parent.parent

BASE = {
    "provider": "openai_compatible",
    "base_url": "http://localhost:11434/v1",
    "model_name": "m",
    "context_window": 100_000,
    "native_tool_calling": True,
    "per_issue_cap_usd": 0.1,
    "allow_private_code": True,
}


def load(pricing=..., provider="openai_compatible", **extra):
    entry = {**BASE, "provider": provider, **extra}
    if pricing is not ...:
        entry["pricing"] = pricing
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "models.yaml"
        path.write_text(yaml.safe_dump({"models": {"m": entry}}))
        return load_models_config(path)["m"]


PAID = {"input": 0.10, "output": 0.50, "as_of": "2026-11-01"}


# -- valid blocks ------------------------------------------------------------------------------


def test_a_free_model_with_explicit_zeros_needs_no_date():
    model = load({"input": 0, "output": 0})
    assert model.is_free and model.pricing.is_free and model.pricing.as_of is None


def test_a_paid_model_with_everything():
    pricing = load(
        {
            "as_of": "2026-11-01", "source": "https://example.com/pricing",
            "input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125,
            "long_prompt": {"over_tokens": 100000, "input": 0.5, "output": 2.5, "cache_read": 0.05, "cache_write": 0.625},
        },
        provider="claude",
    ).pricing  # fmt: skip
    assert (pricing.input, pricing.output, pricing.cache_read, pricing.cache_write) == (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125"))
    assert pricing.long_prompt.over_tokens == 100000
    assert (pricing.long_prompt.input, pricing.long_prompt.output) == (Decimal("0.5"), Decimal("2.5"))
    assert (pricing.long_prompt.cache_read, pricing.long_prompt.cache_write) == (Decimal("0.05"), Decimal("0.625"))
    assert pricing.as_of == "2026-11-01" and pricing.source == "https://example.com/pricing"
    assert not pricing.is_free


def test_values_are_exact_decimals_not_binary_floats():
    pricing = load({**PAID, "input": 0.1, "output": 0.3}).pricing
    assert pricing.input == Decimal("0.1") and pricing.input != Decimal(0.1)
    assert pricing.output == Decimal("0.3") and pricing.output != Decimal(0.3)
    assert all(isinstance(v, Decimal) for v in (pricing.input, pricing.output, pricing.cache_read, pricing.cache_write))


def test_whole_numbers_and_scientific_notation_are_accepted():
    pricing = load({"as_of": "2026-11-01", "input": 2, "output": 1e-05}).pricing
    assert pricing.input == Decimal(2) and pricing.output == Decimal("0.00001")


def test_as_of_may_be_written_as_a_yaml_date():
    assert load({**PAID, "as_of": datetime.date(2026, 11, 1)}).pricing.as_of == "2026-11-01"


def test_omitted_cache_rates_default_to_the_input_rate_for_other_providers():
    pricing = load(PAID).pricing
    assert pricing.cache_read == pricing.input and pricing.cache_write == pricing.input


def test_omitted_long_prompt_cache_rates_default_to_the_long_input_rate():
    long = load({**PAID, "long_prompt": {"over_tokens": 10, "input": 0.5, "output": 2}}).pricing.long_prompt
    assert long.cache_read == long.input == Decimal("0.5") and long.cache_write == long.input


def test_per_token_helpers_are_dollars_per_single_token():
    model = load(PAID)
    assert model.price_per_input_token == Decimal("0.10") / 1_000_000
    assert model.price_per_output_token == Decimal("0.50") / 1_000_000


def test_pricing_of_builds_from_plain_numbers():
    pricing = Pricing.of(0.1, 0.5, 0.01, 0.125, long_prompt=(100, 1, 2, 0.1, 1.25), as_of="2026-11-01")
    assert pricing.cache_read == Decimal("0.01") and pricing.long_prompt.cache_write == Decimal("1.25")
    assert Pricing.of(1, 2).cache_write == Decimal(1)  # defaults to the input rate
    assert Pricing.free().is_free


# -- rejections ------------------------------------------------------------------------------------


def rejects(pricing, match, **kwargs):
    with pytest.raises(ConfigError, match=match):
        load(pricing, **kwargs)


def test_the_pricing_block_is_required():
    rejects(..., "pricing")


@pytest.mark.parametrize("bad", [None, [], "free", 5])
def test_the_pricing_block_must_be_a_mapping(bad):
    rejects(bad, "pricing")


@pytest.mark.parametrize("missing", ["input", "output"])
def test_input_and_output_are_required(missing):
    block = {k: v for k, v in PAID.items() if k != missing}
    rejects(block, missing)


@pytest.mark.parametrize("field", ["input", "output", "cache_read", "cache_write"])
@pytest.mark.parametrize("value", [-1, -0.001, float("inf"), float("-inf"), float("nan"), True, False, "0.10", None, [1]])
def test_bad_rates_are_rejected_naming_the_field(field, value):
    block = {**PAID, "cache_read": 0.01, "cache_write": 0.1, field: value}
    rejects(block, field)


def test_unknown_keys_in_the_block_are_rejected():
    rejects({**PAID, "cache_reads": 0.01}, "cache_reads")


@pytest.mark.parametrize("old", ["price_per_input_token", "price_per_output_token"])
def test_the_old_flat_fields_are_rejected_with_a_hint(old):
    with pytest.raises(ConfigError, match="pricing") as info:
        load(PAID, **{old: 0.000001})
    assert old in str(info.value)


def test_a_paid_model_needs_the_date_its_prices_were_read():
    rejects({"input": 0.1, "output": 0.5}, "as_of")
    rejects({"input": 0, "output": 0.5}, "as_of")  # one non-zero rate is enough to make it paid
    rejects({"input": 0, "output": 0, "long_prompt": {"over_tokens": 10, "input": 1, "output": 1}}, "as_of")


@pytest.mark.parametrize("bad", ["2026-13-45", "yesterday", "", 5, "11/01/2026", datetime.datetime(2026, 11, 1, 10, 0)])
def test_as_of_must_be_a_real_date(bad):
    rejects({**PAID, "as_of": bad}, "as_of")


@pytest.mark.parametrize("bad", ["", "  ", 5, ["x"]])
def test_source_must_be_text_when_given(bad):
    rejects({**PAID, "source": bad}, "source")


@pytest.mark.parametrize("missing", ["cache_read", "cache_write"])
def test_claude_models_must_state_their_cache_rates(missing):
    block = {**PAID, "cache_read": 0.01, "cache_write": 0.125}
    del block[missing]
    rejects(block, missing, provider="claude")


def test_claude_long_prompt_cards_must_state_cache_rates_too():
    block = {**PAID, "cache_read": 0.01, "cache_write": 0.125, "long_prompt": {"over_tokens": 10, "input": 1, "output": 2}}
    rejects(block, "cache_read", provider="claude")


@pytest.mark.parametrize("missing", ["over_tokens", "input", "output"])
def test_long_prompt_needs_threshold_input_and_output(missing):
    card = {"over_tokens": 100, "input": 1, "output": 2}
    del card[missing]
    rejects({**PAID, "long_prompt": card}, missing)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "100", None])
def test_long_prompt_threshold_must_be_a_positive_whole_number(bad):
    rejects({**PAID, "long_prompt": {"over_tokens": bad, "input": 1, "output": 2}}, "over_tokens")


def test_long_prompt_unknown_keys_and_wrong_types():
    rejects({**PAID, "long_prompt": {"over_tokens": 10, "input": 1, "output": 2, "cache": 1}}, "cache")
    rejects({**PAID, "long_prompt": [1, 2]}, "long_prompt")
    rejects({**PAID, "long_prompt": {"over_tokens": 10, "input": -1, "output": 2}}, "input")


# -- age and staleness -----------------------------------------------------------------------------------


def test_age_in_days():
    pricing = Pricing.of(1, 2, as_of="2026-11-01")
    assert pricing.age_days(datetime.date(2026, 11, 1)) == 0
    assert pricing.age_days(datetime.date(2026, 12, 1)) == 30
    assert Pricing.of(1, 2).age_days() is None


def test_staleness_boundary_is_exactly_thirty_days():
    pricing = Pricing.of(1, 2, as_of="2026-11-01")
    assert pricing_is_stale(pricing, datetime.date(2026, 12, 1)) is False  # 30 days old
    assert pricing_is_stale(pricing, datetime.date(2026, 12, 2)) is True  # 31 days old
    assert pricing_is_stale(pricing, datetime.date(2026, 11, 20), max_age_days=10) is True


def test_undated_paid_prices_are_stale_and_free_prices_never_are():
    assert pricing_is_stale(Pricing.of(1, 2)) is True
    assert pricing_is_stale(Pricing.free(), datetime.date(2099, 1, 1)) is False


# -- the shipped file ------------------------------------------------------------------------------------


def test_the_shipped_models_file():
    models = load_models_config(ROOT / "config" / "models.yaml")
    haiku = models["haiku"].pricing
    assert (haiku.input, haiku.output, haiku.cache_read, haiku.cache_write) == (Decimal("0.10"), Decimal("0.50"), Decimal("0.01"), Decimal("0.125"))
    long = haiku.long_prompt
    assert (long.over_tokens, long.input, long.output, long.cache_read, long.cache_write) == (
        100_000, Decimal("0.50"), Decimal("2.50"), Decimal("0.05"), Decimal("0.625"),
    )  # fmt: skip
    assert haiku.as_of == "2026-11-01" and "pricing" in haiku.source
    assert models["local-free"].is_free and models["groq-free"].is_free
    assert not models["haiku"].is_free
