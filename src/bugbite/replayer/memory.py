"""An in-memory stand-in for the recording writer, so a replay produces events to compare without touching the disk."""

from __future__ import annotations

import json
import threading
from typing import Any

from bugbite.adapter.codec import canonical_json

from .clock import ReplayClock


class MemoryWriter:
    """Has the methods `RecordingAdapter` and `RunRecorder` use on a `RunWriter`. Never writes a file.

    Each event gets a sequence number and the replay clock's time, and is passed through JSON like a real recording would be, so
    replayed and recorded events compare as plain data.
    """

    def __init__(self, clock: ReplayClock, *, record_requests: bool = False) -> None:
        self.record_requests = record_requests
        self.events: list[dict[str, Any]] = []
        self.errors = 0
        self.last_error: str | None = None
        self.outcome: dict[str, Any] | None = None
        self._clock = clock
        self._lock = threading.Lock()
        self._calls = self._assigned = 0

    def next_call_number(self) -> int:
        with self._lock:
            self._calls += 1
            return self._calls

    def take_unassigned_calls(self) -> list[int]:
        with self._lock:
            numbers = list(range(self._assigned + 1, self._calls + 1))
            self._assigned = self._calls
            return numbers

    def note_error(self, exc: BaseException) -> None:
        with self._lock:
            self.errors += 1
            self.last_error = type(exc).__name__

    def write(self, event: dict[str, Any]) -> bool:
        with self._lock:
            record = json.loads(canonical_json({"seq": len(self.events) + 1, "t": round(self._clock.now(), 6), **event}))
            self.events.append(record)
            return True

    def finish(self, outcome: dict[str, Any] | None = None, **_: Any) -> None:
        self.outcome = outcome
