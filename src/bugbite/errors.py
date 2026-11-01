"""Errors caused by bad user input (as opposed to bad system config).

Each error carries a stable `code` so the CLI, API, and dashboard can map it
to their own output without parsing message text.
"""

from __future__ import annotations

INVALID_URL = "invalid_url"
NOT_GITHUB = "not_github"
NOT_AN_ISSUE_URL = "not_an_issue_url"
NOT_A_REPO_URL = "not_a_repo_url"
REPO_MISMATCH = "repo_mismatch"
EMPTY_INPUT = "empty_input"

ALL_CODES = frozenset(
    {INVALID_URL, NOT_GITHUB, NOT_AN_ISSUE_URL, NOT_A_REPO_URL, REPO_MISMATCH, EMPTY_INPUT}
)


class InputError(Exception):
    """User input was rejected. `code` is stable; `message` is user-facing."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown InputError code: {code!r}")
        if not message:
            raise ValueError("InputError needs a non-empty message")
        super().__init__(message)
        self.code = code
        self.message = message
