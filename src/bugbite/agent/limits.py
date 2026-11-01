"""The hard limits on one job (README FR5.4): steps, cost and wall-clock time."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bugbite.config import AppConfig, ModelConfig

DEFAULT_COST_MARGIN = Decimal("1.25")  # a guess, not yet checked against real token counts (AD-098)


def _decimal(name: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{name} must be a number, got {value!r}")
    try:
        number = Decimal(str(value))  # through text, so 0.1 is exactly 0.1
    except InvalidOperation:
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


@dataclass(frozen=True)
class Limits:
    """`max_steps` counts model calls. A cost or time limit of None means no such limit."""

    max_steps: int
    max_cost_usd: Decimal | None = None
    max_wall_clock_s: float | None = None
    cost_margin: Decimal = DEFAULT_COST_MARGIN

    def __post_init__(self) -> None:
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps < 1:
            raise ValueError(f"max_steps must be an integer of at least 1, got {self.max_steps!r}")
        if self.max_cost_usd is not None:
            cost = _decimal("max_cost_usd", self.max_cost_usd)
            if cost < 0:
                raise ValueError(f"max_cost_usd must not be negative, got {self.max_cost_usd!r}")
            object.__setattr__(self, "max_cost_usd", cost)
        if self.max_wall_clock_s is not None:
            seconds = _decimal("max_wall_clock_s", self.max_wall_clock_s)
            if seconds <= 0:
                raise ValueError(f"max_wall_clock_s must be greater than zero, got {self.max_wall_clock_s!r}")
            object.__setattr__(self, "max_wall_clock_s", float(seconds))
        margin = _decimal("cost_margin", self.cost_margin)
        if margin < 1:
            raise ValueError(f"cost_margin must be at least 1, got {self.cost_margin!r}")
        object.__setattr__(self, "cost_margin", margin)


def limits_from_config(app: "AppConfig", model: "ModelConfig") -> Limits:
    """Steps and time from the app config; cost is the lower of the app cap and the model's own cap."""
    try:
        return Limits(
            max_steps=app.max_steps,
            max_cost_usd=min(_decimal("max_cost_usd", app.max_cost_usd), _decimal("per_issue_cap_usd", model.per_issue_cap_usd)),
            max_wall_clock_s=app.max_wall_clock_s,
        )
    except ValueError as exc:
        raise ValueError(f"cannot build limits from config ({model.name}): {exc}") from None
