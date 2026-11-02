"""The recording layer: written to by the recorder (P22), read back by the replayer (P23) (AD-118).

It sits directly above the provider adapter and inside the privacy guard, so it sees exactly what the provider
returned or failed with, and a call the guard refuses (which is never sent) is never recorded.
"""

from __future__ import annotations

from typing import Any, Protocol

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.codec import error_to_dict, request_fingerprint, request_to_dict, response_to_dict
from bugbite.adapter.types import GenerationRequest, GenerationResponse
from bugbite.errors import AdapterError


class RecordingSink(Protocol):
    """What `RecordingAdapter` needs from a writer (`bugbite.recorder.RunWriter` provides it)."""

    record_requests: bool

    def next_call_number(self) -> int: ...

    def write(self, event: dict[str, Any]) -> bool: ...

    def note_error(self, exc: BaseException) -> None: ...


class RecordingAdapter(ModelAdapter):
    """Behaves exactly like the adapter it wraps and writes each call to a recording.

    The response is returned as the very same object and an error is re-raised as the very same object.
    A problem with the recording itself is noted on the sink and never reaches the caller.
    """

    def __init__(self, inner: ModelAdapter, sink: RecordingSink) -> None:
        super().__init__(inner.config)
        self._inner = inner
        self.sink = sink

    @property
    def inner(self) -> ModelAdapter:
        return self._inner

    def _event(self, call: int, request: GenerationRequest, outcome: dict[str, Any]) -> None:
        try:
            event: dict[str, Any] = {"type": "model_call", "call": call, "request": request_fingerprint(request), **outcome}
            if self.sink.record_requests:
                event["request"]["full"] = request_to_dict(request)
            self.sink.write(event)
        except Exception as exc:  # a recording problem must never reach the job (AD-120)
            try:
                self.sink.note_error(exc)
            except Exception:
                pass

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        try:
            call = self.sink.next_call_number()
        except Exception:
            call = 0  # the sink is broken; the call goes ahead unrecorded
        try:
            response = self._inner.generate(request)
        except AdapterError as error:
            if call:
                self._event(call, request, {"error": error_to_dict(error)})
            raise
        except Exception as exc:
            if call:
                self._event(call, request, {"exception": type(exc).__name__})
            raise
        if call:
            self._event(call, request, {"response": response_to_dict(response)})
        return response

    def estimate_tokens(self, request: GenerationRequest) -> int:
        return self._inner.estimate_tokens(request)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def __repr__(self) -> str:
        return f"RecordingAdapter({self._inner!r})"
