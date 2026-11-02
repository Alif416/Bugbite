"""Errors from building or reading a code index."""

from __future__ import annotations

SCAN_FAILED = "scan_failed"  # the scanner exited with an error
SCAN_TIMEOUT = "scan_timeout"
OUTPUT_TOO_LARGE = "output_too_large"  # the sandbox cut the scanner's output
BAD_OUTPUT = "bad_output"  # the output was not a valid index (untrusted data)
BAD_LIMITS = "bad_limits"

ALL_CODES = frozenset({SCAN_FAILED, SCAN_TIMEOUT, OUTPUT_TOO_LARGE, BAD_OUTPUT, BAD_LIMITS})


class RetrievalError(Exception):
    """`code` is stable; `message` is user-facing."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown RetrievalError code: {code!r}")
        if not message:
            raise ValueError("RetrievalError needs a non-empty message")
        super().__init__(message)
        self.code = code
        self.message = message
