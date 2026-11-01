"""The last gate before the network: refuses every call the privacy rule forbids."""

from __future__ import annotations

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.types import GenerationRequest, GenerationResponse
from bugbite.privacy import Sensitivity, may_receive, refusal_for


class PrivacyGuardAdapter(ModelAdapter):
    """Wraps a raw adapter and, on every call, checks that its model may receive this data.

    The decision is made before the request is looked at, and a refused call never reaches the
    inner adapter. `sensitivity` is required: there is no way to build a guard without saying
    what kind of data it protects. `create_adapter` puts this innermost, so the metering and
    text-action layers can only reach the network through it.
    """

    def __init__(self, inner: ModelAdapter, sensitivity: Sensitivity) -> None:
        if not isinstance(sensitivity, Sensitivity):
            raise TypeError(f"sensitivity must be a Sensitivity, got {sensitivity!r}")
        super().__init__(inner.config)
        self._inner = inner
        self.sensitivity = sensitivity

    @property
    def inner(self) -> ModelAdapter:
        return self._inner

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not may_receive(self.config, self.sensitivity):
            raise refusal_for(self.config, self.sensitivity)
        return self._inner.generate(request)

    def estimate_tokens(self, request: GenerationRequest) -> int:
        return self._inner.estimate_tokens(request)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def __repr__(self) -> str:
        return f"PrivacyGuardAdapter({self._inner!r}, {self.sensitivity.value})"
