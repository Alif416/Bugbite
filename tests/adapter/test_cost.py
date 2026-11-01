"""Cost computation. Every figure is checked by hand against the Haiku 5.5 rate card."""

from decimal import Decimal

import pytest
from claude_helpers import HAIKU_PRICING

from bugbite.adapter import Usage, compute_cost, format_usd, worst_case_cost
from bugbite.adapter.cost import TIER_LONG_PROMPT, TIER_STANDARD, money_text, rate_card
from bugbite.config import Pricing

D = Decimal


# -- the four components ------------------------------------------------------------------------


def test_a_full_call_costs_exactly_three_hundredths_of_a_cent():
    # input 1000 x 0.10 + output 200 x 0.50 + cache reads 5000 x 0.01 + cache writes 400 x 0.125, per million
    cost = compute_cost(HAIKU_PRICING, Usage(input_tokens=1000, output_tokens=200, cache_read_tokens=5000, cache_write_tokens=400))
    assert cost.input_usd == D("0.0001")
    assert cost.output_usd == D("0.0001")
    assert cost.cache_read_usd == D("0.00005")
    assert cost.cache_write_usd == D("0.00005")
    assert cost.total_usd == D("0.0003")
    assert (cost.tier, cost.prompt_tokens, cost.estimated, cost.free) == (TIER_STANDARD, 6400, False, False)


@pytest.mark.parametrize(
    "usage, expected",
    [
        (Usage(input_tokens=100_000), D("0.01")),  # 100,000 is exactly the threshold: still the standard card
        (Usage(output_tokens=1_000_000), D("0.50")),  # output never counts toward prompt length
        (Usage(cache_read_tokens=100_000), D("0.001")),
        (Usage(cache_write_tokens=100_000), D("0.0125")),
        (Usage(), D("0")),
        (Usage(input_tokens=1), D("0.0000001")),
    ],
)
def test_each_kind_of_token_alone(usage, expected):
    assert compute_cost(HAIKU_PRICING, usage).total_usd == expected


def test_a_million_tokens_of_each_prompt_kind_is_priced_on_the_long_card():
    # a one-million-token prompt is far over the threshold, so these are the long-card rates
    assert compute_cost(HAIKU_PRICING, Usage(input_tokens=1_000_000)).total_usd == D("0.50")
    assert compute_cost(HAIKU_PRICING, Usage(cache_read_tokens=1_000_000)).total_usd == D("0.05")
    assert compute_cost(HAIKU_PRICING, Usage(cache_write_tokens=1_000_000)).total_usd == D("0.625")


# -- the long-prompt tier --------------------------------------------------------------------------


def test_a_prompt_of_exactly_the_threshold_is_standard():
    cost = compute_cost(HAIKU_PRICING, Usage(input_tokens=100_000))
    assert cost.tier == TIER_STANDARD and cost.total_usd == D("0.01")


def test_one_token_over_the_threshold_moves_the_whole_call_to_the_long_card():
    cost = compute_cost(HAIKU_PRICING, Usage(input_tokens=100_001, output_tokens=1000))
    # input 100001 x 0.50 + output 1000 x 2.50, per million
    assert cost.tier == TIER_LONG_PROMPT and cost.total_usd == D("0.0525005")


def test_cache_tokens_count_toward_prompt_length():
    cost = compute_cost(HAIKU_PRICING, Usage(input_tokens=60_000, cache_read_tokens=40_001))
    assert cost.prompt_tokens == 100_001 and cost.tier == TIER_LONG_PROMPT
    assert cost.total_usd == D("0.03") + D("0.00200005")  # 60000 x 0.50 + 40001 x 0.05, per million
    just_under = compute_cost(HAIKU_PRICING, Usage(input_tokens=60_000, cache_read_tokens=40_000))
    assert just_under.tier == TIER_STANDARD


def test_cache_writes_also_count_toward_prompt_length():
    assert compute_cost(HAIKU_PRICING, Usage(cache_write_tokens=100_001)).tier == TIER_LONG_PROMPT


def test_output_tokens_do_not_count_toward_prompt_length():
    assert compute_cost(HAIKU_PRICING, Usage(input_tokens=10, output_tokens=500_000)).tier == TIER_STANDARD


def test_a_model_without_a_long_card_never_switches():
    flat = Pricing.of(1, 2, as_of="2026-11-01")
    assert compute_cost(flat, Usage(input_tokens=5_000_000)).tier == TIER_STANDARD
    assert rate_card(flat, 10**9)[0] == TIER_STANDARD


# -- free and estimated ----------------------------------------------------------------------------------


@pytest.mark.parametrize("usage", [Usage(), Usage(input_tokens=10**9, output_tokens=10**9, cache_read_tokens=5, cache_write_tokens=5)])
def test_free_models_cost_exactly_zero(usage):
    cost = compute_cost(Pricing.free(), usage)
    assert cost.total_usd == 0 and cost.free is True
    assert cost.input_usd == cost.output_usd == cost.cache_read_usd == cost.cache_write_usd == 0


def test_estimated_usage_is_flagged():
    assert compute_cost(HAIKU_PRICING, Usage(input_tokens=10), estimated=True).estimated is True
    assert compute_cost(HAIKU_PRICING, Usage(input_tokens=10)).estimated is False


def test_the_cost_converts_to_json_safe_text():
    data = compute_cost(HAIKU_PRICING, Usage(input_tokens=1000, output_tokens=200)).to_dict()
    assert data["total_usd"] == "0.0002" and data["tier"] == "standard"
    assert all(isinstance(v, (str, int, bool)) for v in data.values())


# -- exactness ---------------------------------------------------------------------------------------------


def test_ten_thousand_calls_sum_with_no_drift():
    usage = Usage(input_tokens=7, output_tokens=3, cache_read_tokens=2, cache_write_tokens=1)
    one = compute_cost(HAIKU_PRICING, usage).total_usd
    assert one == D("0.000002345")  # (7 x 0.10 + 3 x 0.50 + 2 x 0.01 + 1 x 0.125) / 1e6
    assert sum((compute_cost(HAIKU_PRICING, usage).total_usd for _ in range(10_000)), D(0)) == D("0.02345")


def test_summing_in_any_order_gives_the_same_total():
    costs = [compute_cost(HAIKU_PRICING, Usage(input_tokens=n, output_tokens=n // 3)).total_usd for n in range(1, 2000, 7)]
    assert sum(costs, D(0)) == sum(reversed(costs), D(0))


# -- worst case -----------------------------------------------------------------------------------------------


def test_worst_case_prices_the_prompt_at_the_larger_of_input_and_cache_write():
    # 20000 x 0.125 (cache write is dearer than input) + 4096 x 0.50, per million
    assert worst_case_cost(HAIKU_PRICING, 20_000, 4096) == D("0.004548")
    flat = Pricing.of(1, 2, cache_write=0.5, as_of="2026-11-01")  # here input is the larger rate
    assert worst_case_cost(flat, 1_000_000, 0) == D("1")


def test_worst_case_switches_tier_on_the_projected_prompt():
    assert worst_case_cost(HAIKU_PRICING, 100_000, 0) == D("0.0125")
    assert worst_case_cost(HAIKU_PRICING, 100_001, 1000) == D("0.065000625")  # 100001 x 0.625 + 1000 x 2.50


def test_worst_case_never_undercuts_the_real_cost():
    for usage in (Usage(input_tokens=5000, output_tokens=300), Usage(cache_write_tokens=5000, output_tokens=300), Usage(cache_read_tokens=5000, output_tokens=300)):
        real = compute_cost(HAIKU_PRICING, usage).total_usd
        assert worst_case_cost(HAIKU_PRICING, usage.prompt_tokens, usage.output_tokens) >= real


def test_margin_scales_the_prompt_estimate():
    assert worst_case_cost(HAIKU_PRICING, 80_000, 0, margin=1.3) == D("0.065")  # 104000 projected: long card, 104000 x 0.625
    assert worst_case_cost(HAIKU_PRICING, 80_000, 0, margin=1) == D("0.01")
    assert worst_case_cost(HAIKU_PRICING, 1000, 0, margin=D("1.5")) == D("0.0001875")


def test_worst_case_for_a_free_model_is_zero():
    assert worst_case_cost(Pricing.free(), 10**6, 10**5, margin=3) == 0


@pytest.mark.parametrize("args", [(-1, 10), (10, -1), (1.5, 10), (10, 2.5), (True, 10), (10, None)])
def test_worst_case_rejects_bad_token_counts(args):
    with pytest.raises(ValueError):
        worst_case_cost(HAIKU_PRICING, *args)


@pytest.mark.parametrize("margin", [-1, float("nan"), float("inf")])
def test_worst_case_rejects_bad_margins(margin):
    with pytest.raises(ValueError):
        worst_case_cost(HAIKU_PRICING, 10, 10, margin=margin)


# -- display -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, places, expected",
    [(D("0.0003"), 6, "$0.000300"), (D("0.000002345"), 6, "$0.000002"), (D("12.5"), 2, "$12.50"), (D("0"), 6, "$0.000000"), (D("1E-7"), 8, "$0.00000010")],
)
def test_format_usd_never_uses_scientific_notation(amount, places, expected):
    assert format_usd(amount, places) == expected


def test_format_usd_rejects_negative_places():
    with pytest.raises(ValueError):
        format_usd(D(1), -1)


@pytest.mark.parametrize(
    "amount, expected",
    [(D("0.00030"), "0.0003"), (D("3E-4"), "0.0003"), (D("0.0003"), "0.0003"), (D("0"), "0"), (D("0.00"), "0"), (D("-0"), "0"),
     (D("12.50"), "12.5"), (D("100"), "100"), (D("1E+2"), "100"), (D("0.000000100"), "0.0000001")],
)  # fmt: skip
def test_money_text_is_one_canonical_form(amount, expected):
    assert money_text(amount) == expected


def test_equal_amounts_summed_differently_read_the_same():
    a = D("0.00005") + D("0.0001") + D("0.00005") + D("0.0001")
    b = D("0.0003")
    assert a == b and money_text(a) == money_text(b) == "0.0003"
