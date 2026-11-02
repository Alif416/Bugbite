"""The stand-in for the real provider: serves the recorded answers in order and checks every request (AD-121, AD-122, AD-124)."""

from __future__ import annotations

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.codec import request_fingerprint, request_to_dict
from bugbite.adapter.types import GenerationRequest, GenerationResponse
from bugbite.config import ModelConfig
from bugbite.recorder import ModelCallRecord

from .clock import ReplayClock
from .diff import at_path, excerpts, first_difference, fingerprint_differences
from .errors import EXTRA_MODEL_CALL, PROVIDER_BUG, RECORDING_ENDED, REQUEST_MISMATCH, ReplayDivergence


class ReplayProvider(ModelAdapter):
    """Sits where the Claude or OpenAI-compatible adapter sits. Call n gets recorded call n.

    Before answering it fingerprints the request it was given and compares it with the recorded fingerprint; on any difference it
    raises `ReplayDivergence` and serves nothing more. Then it moves the clock to the recorded time and returns the recorded response
    or raises the recorded `AdapterError`.
    """

    def __init__(self, config: ModelConfig, recorded: list[ModelCallRecord], clock: ReplayClock, *, complete: bool = True) -> None:
        super().__init__(config)
        self._recorded = list(recorded)
        self._clock = clock
        self._complete = complete
        self.served = 0

    @property
    def unused(self) -> int:
        return len(self._recorded) - self.served

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        number = self.served + 1
        if self.served >= len(self._recorded):
            if not self._complete:
                raise ReplayDivergence(RECORDING_ENDED, number, f"The recording ends after {len(self._recorded)} model call(s) (it is incomplete); the code asked for call {number}.")
            raise ReplayDivergence(EXTRA_MODEL_CALL, number, f"The code made model call {number}, but the recording has only {len(self._recorded)}.")
        record = self._recorded[self.served]
        if record.exception is not None:
            raise ReplayDivergence(PROVIDER_BUG, number, f"Model call {number} hit a bug in the provider adapter when it was recorded ({record.exception}); it cannot be replayed.")
        fingerprint = request_fingerprint(request)
        fields = fingerprint_differences(record.request, fingerprint)
        if fields:
            path = None
            if isinstance(record.request.get("full"), dict):
                path = first_difference(record.request["full"], request_to_dict(request))
            message = f"Model call {number}: the request is not the recorded one (differs in: {', '.join(fields)})."
            if path is not None:
                before, now = excerpts(at_path(record.request["full"], path), at_path(request_to_dict(request), path))
                message += f" First difference at {path}: recorded {before}, now {now}."
            raise ReplayDivergence(REQUEST_MISMATCH, number, message, fields=tuple(fields), path=path)
        self.served += 1
        self._clock.advance_to(record.t)
        if record.error is not None:
            raise record.error
        assert record.response is not None
        return record.response
