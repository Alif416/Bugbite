"""A virtual clock for replays: it moves only when the recording says time passed (AD-123)."""

from __future__ import annotations


class ReplayClock:
    """Starts at 0. `advance_to` sets it to a recorded time and never moves it backwards; `sleep` moves it forward without waiting."""

    def __init__(self) -> None:
        self._now = 0.0

    def now(self) -> float:
        return self._now

    __call__ = now

    def advance_to(self, t: float) -> None:
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t != t:
            raise ValueError(f"a time must be a number, got {t!r}")
        if t > self._now:
            self._now = float(t)

    def sleep(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds != seconds or seconds < 0:
            raise ValueError(f"cannot sleep for {seconds!r} seconds")
        self._now += seconds
