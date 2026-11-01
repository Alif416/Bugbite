"""A wrapper that records the cost of every call made through any adapter (AD-067)."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.cost import compute_cost, worst_case_cost
from bugbite.adapter.ledger import CallRecord, CostLedger
from bugbite.adapter.types import GenerationRequest, GenerationResponse
from bugbite.errors import INVALID_REQUEST, AdapterError


def rejected_locally(error: AdapterError) -> bool:
    """True for a request the adapter refused before sending it (a bad conversation, a temperature the
    model does not accept). Those never reached the provider, so they are not model calls. A provider's
    own 400 carries a status code; a local refusal does not."""
    return error.code == INVALID_REQUEST and error.status_code is None


class MeteredAdapter(ModelAdapter):
    """Behaves exactly like the adapter it wraps, and writes each call to a ledger.

    Responses are returned unchanged (the very same object) and adapter errors are re-raised
    unchanged. A failed call is recorded with its error code and no cost; a request refused locally
    before anything was sent is not a call and is not recorded. Anything that is not an
    `AdapterError` (a bug) passes through without being recorded.
    """

    def __init__(self, inner: ModelAdapter, ledger: CostLedger) -> None:
        super().__init__(inner.config)
        self._inner = inner
        self.ledger = ledger
        self.last_call: CallRecord | None = None

    @property
    def inner(self) -> ModelAdapter:
        return self._inner

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
        try:
            response = self._inner.generate(request)
        except AdapterError as error:
            if not rejected_locally(error):
                self.last_call = self.ledger.record_failure(self.config.name, error, time.monotonic() - started)
            raise
        cost = compute_cost(self.config.pricing, response.usage, estimated=response.usage_estimated)
        self.last_call = self.ledger.record_success(self.config.name, response, cost)
        return response

    def estimate_tokens(self, request: GenerationRequest) -> int:
        return self._inner.estimate_tokens(request)

    def worst_case_cost(self, request: GenerationRequest, margin: Any = 1) -> Decimal:
        """The most the next call could cost; for a later phase to compare against a cap."""
        return worst_case_cost(
            self.config.pricing, self.estimate_tokens(request), self.resolve_max_output_tokens(request), margin
        )

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def __repr__(self) -> str:
        return f"MeteredAdapter({self._inner!r})"
