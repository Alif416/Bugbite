"""What a model call costs. Pure functions over exact decimals; no I/O.

A call is priced on one rate card, chosen by its prompt length (input, cache-read, and
cache-write tokens together). A prompt longer than the model's `long_prompt` threshold, if
it has one, uses the long-prompt card for the whole call. See AD-066.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from bugbite.adapter.types import Usage
from bugbite.config import MILLION, ZERO, Pricing, RateCard

TIER_STANDARD = "standard"
TIER_LONG_PROMPT = "long_prompt"


def money_text(amount: Decimal) -> str:
    """One canonical plain-text form for stored money: no exponent and no trailing zeros, so equal
    amounts always read the same however they were summed (`0.0003`, never `0.00030` or `3E-4`)."""
    text = format(amount.normalize(), "f")
    return "0" if text in ("-0", "") else text


@dataclass(frozen=True)
class CallCost:
    tier: str
    prompt_tokens: int
    input_usd: Decimal
    output_usd: Decimal
    cache_read_usd: Decimal
    cache_write_usd: Decimal
    total_usd: Decimal
    estimated: bool  # the token counts were estimated because the server reported none
    free: bool  # the model has no price: cost is exactly zero

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe: money as strings so no precision is lost."""
        return {
            "tier": self.tier,
            "prompt_tokens": self.prompt_tokens,
            "input_usd": money_text(self.input_usd),
            "output_usd": money_text(self.output_usd),
            "cache_read_usd": money_text(self.cache_read_usd),
            "cache_write_usd": money_text(self.cache_write_usd),
            "total_usd": money_text(self.total_usd),
            "estimated": self.estimated,
            "free": self.free,
        }


def rate_card(pricing: Pricing, prompt_tokens: int) -> tuple[str, RateCard]:
    """The rate card that applies to a call with this many prompt tokens."""
    long = pricing.long_prompt
    if long is not None and prompt_tokens > long.over_tokens:
        return TIER_LONG_PROMPT, long.rates
    return TIER_STANDARD, pricing.standard


def compute_cost(pricing: Pricing, usage: Usage, estimated: bool = False) -> CallCost:
    prompt_tokens = usage.prompt_tokens
    tier, rates = rate_card(pricing, prompt_tokens)
    input_usd = Decimal(usage.input_tokens) * rates.input / MILLION
    output_usd = Decimal(usage.output_tokens) * rates.output / MILLION
    cache_read_usd = Decimal(usage.cache_read_tokens) * rates.cache_read / MILLION
    cache_write_usd = Decimal(usage.cache_write_tokens) * rates.cache_write / MILLION
    return CallCost(
        tier=tier,
        prompt_tokens=prompt_tokens,
        input_usd=input_usd,
        output_usd=output_usd,
        cache_read_usd=cache_read_usd,
        cache_write_usd=cache_write_usd,
        total_usd=input_usd + output_usd + cache_read_usd + cache_write_usd,
        estimated=estimated,
        free=pricing.is_free,
    )


def worst_case_cost(pricing: Pricing, prompt_tokens: int, max_output_tokens: int, margin: Any = 1) -> Decimal:
    """The most a call could cost.

    Every prompt token is priced at the larger of the input and cache-write rates, every
    allowed output token at the output rate, on the card the projected prompt size selects.
    `margin` scales the prompt estimate (estimates from character counts tend to run low).
    Enforcing a cap with this is left to the agent loop and the spend-control phase.
    """
    for name, value in (("prompt_tokens", prompt_tokens), ("max_output_tokens", max_output_tokens)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    factor = Decimal(str(margin))
    if not factor.is_finite() or factor < 0:
        raise ValueError(f"margin must be a non-negative number, got {margin!r}")
    projected = math.ceil(Decimal(prompt_tokens) * factor)
    _, rates = rate_card(pricing, projected)
    prompt_rate = max(rates.input, rates.cache_write)
    return (Decimal(projected) * prompt_rate + Decimal(max_output_tokens) * rates.output) / MILLION


def format_usd(amount: Decimal, places: int = 6) -> str:
    """Dollars without scientific notation, for reports and logs."""
    if places < 0:
        raise ValueError("places must not be negative")
    return f"${amount:.{places}f}"


__all__ = [
    "TIER_LONG_PROMPT",
    "TIER_STANDARD",
    "ZERO",
    "CallCost",
    "compute_cost",
    "format_usd",
    "money_text",
    "rate_card",
    "worst_case_cost",
]
