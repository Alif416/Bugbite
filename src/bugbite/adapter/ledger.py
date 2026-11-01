"""A running record of what model calls cost. In memory, thread-safe, enforces nothing (AD-067, AD-068)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from bugbite.adapter.cost import CallCost, money_text
from bugbite.adapter.types import GenerationResponse, Usage
from bugbite.config import ZERO
from bugbite.errors import AdapterError


@dataclass(frozen=True)
class CallRecord:
    index: int  # 1-based position in the ledger
    model: str  # the model's name in the config
    request_id: str | None
    stop_reason: str | None
    usage: Usage | None  # None for a failed call
    cost: CallCost | None  # None for a failed call: no cost is invented
    latency_s: float
    at: float  # when the call was recorded, seconds since the epoch
    error_code: str | None = None

    @property
    def failed(self) -> bool:
        return self.error_code is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "model": self.model,
            "request_id": self.request_id,
            "stop_reason": self.stop_reason,
            "usage": None
            if self.usage is None
            else {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cache_read_tokens": self.usage.cache_read_tokens,
                "cache_write_tokens": self.usage.cache_write_tokens,
            },
            "cost": None if self.cost is None else self.cost.to_dict(),
            "latency_s": self.latency_s,
            "at": self.at,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ModelTotals:
    calls: int
    failed_calls: int
    estimated_calls: int
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "estimated_calls": self.estimated_calls,
            "cost_usd": money_text(self.cost_usd),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "latency_s": self.latency_s,
        }


def _totals(records: list[CallRecord]) -> ModelTotals:
    paid = [r for r in records if r.usage is not None and r.cost is not None]
    return ModelTotals(
        calls=len(records),
        failed_calls=sum(1 for r in records if r.failed),
        estimated_calls=sum(1 for r in paid if r.cost.estimated),  # type: ignore[union-attr]
        cost_usd=sum((r.cost.total_usd for r in paid), ZERO),  # type: ignore[union-attr]
        input_tokens=sum(r.usage.input_tokens for r in paid),  # type: ignore[union-attr]
        output_tokens=sum(r.usage.output_tokens for r in paid),  # type: ignore[union-attr]
        cache_read_tokens=sum(r.usage.cache_read_tokens for r in paid),  # type: ignore[union-attr]
        cache_write_tokens=sum(r.usage.cache_write_tokens for r in paid),  # type: ignore[union-attr]
        latency_s=sum(r.latency_s for r in records),
    )


class CostLedger:
    """Every call made through a metered adapter, with exact running totals."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: list[CallRecord] = []

    # -- recording ---------------------------------------------------------------

    def record_success(self, model: str, response: GenerationResponse, cost: CallCost) -> CallRecord:
        return self._append(
            model,
            request_id=response.request_id,
            stop_reason=response.stop_reason,
            usage=response.usage,
            cost=cost,
            latency_s=response.latency_s,
            error_code=None,
        )

    def record_failure(self, model: str, error: AdapterError, latency_s: float) -> CallRecord:
        return self._append(
            model, request_id=None, stop_reason=None, usage=None, cost=None, latency_s=latency_s, error_code=error.code
        )

    def _append(self, model: str, **fields: Any) -> CallRecord:
        with self._lock:
            record = CallRecord(index=len(self._records) + 1, model=model, at=self._clock(), **fields)
            self._records.append(record)
            return record

    # -- reading -------------------------------------------------------------------

    @property
    def calls(self) -> tuple[CallRecord, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def total_usd(self) -> Decimal:
        return self.totals().cost_usd

    def totals(self) -> ModelTotals:
        return _totals(list(self.calls))

    def by_model(self) -> dict[str, ModelTotals]:
        grouped: dict[str, list[CallRecord]] = {}
        for record in self.calls:
            grouped.setdefault(record.model, []).append(record)
        return {name: _totals(records) for name, records in grouped.items()}

    def snapshot(self) -> dict[str, Any]:
        """Everything, as plain JSON-safe data: money is written as strings."""
        records = self.calls
        return {
            "total": _totals(list(records)).to_dict(),
            "by_model": {name: totals.to_dict() for name, totals in self.by_model().items()},
            "calls": [r.to_dict() for r in records],
        }
