"""Why a replay stopped or could not start."""

from __future__ import annotations

REQUEST_MISMATCH = "request_mismatch"  # the request the code built is not the recorded one
TOOL_MISMATCH = "tool_mismatch"  # the tool call the loop made is not the recorded one
EXTRA_MODEL_CALL = "extra_model_call"  # the code made more model calls than were recorded
EXTRA_TOOL_CALL = "extra_tool_call"  # the code made more tool calls than were recorded
RECORDING_ENDED = "recording_ended"  # an incomplete recording ran out (only with allow_partial)
PROVIDER_BUG = "provider_bug"  # the recorded run hit a bug in the provider adapter; it cannot be replayed


class ReplayError(Exception):
    """The recording cannot be replayed at all (partial without permission, unsupported settings, unusable manifest)."""


class ReplayDivergence(BaseException):
    """The current code did something the recording did not.

    A `BaseException` on purpose: the code under replay has broad `except Exception` handlers (the loop turns a failing tool into an
    error result), and those must not be able to swallow the stop (AD-125). `replay()` catches it and reports it.
    """

    def __init__(self, kind: str, call: int, message: str, *, fields: tuple[str, ...] = (), path: str | None = None) -> None:
        super().__init__(message)
        self.kind, self.call, self.message, self.fields, self.path = kind, call, message, tuple(fields), path

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"ReplayDivergence({self.kind!r}, call={self.call}, fields={self.fields!r}, path={self.path!r})"
