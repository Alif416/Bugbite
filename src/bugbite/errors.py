"""Errors raised for problems outside the program's own bugs.

Two families, because callers present them differently:

- `InputError`: the user can fix it (bad URL, repo not found, not Python).
- `GitHubAPIError`: the provider or network failed (rate limit, timeout).

Each carries a stable `code` so the CLI, API, and dashboard can map it to
their own output without parsing message text.
"""

from __future__ import annotations

# InputError codes
INVALID_URL = "invalid_url"
NOT_GITHUB = "not_github"
NOT_AN_ISSUE_URL = "not_an_issue_url"
NOT_A_REPO_URL = "not_a_repo_url"
REPO_MISMATCH = "repo_mismatch"
EMPTY_INPUT = "empty_input"
REPO_NOT_FOUND = "repo_not_found"
NOT_PYTHON = "not_python"
ISSUE_NOT_FOUND = "issue_not_found"
NOT_AN_ISSUE = "not_an_issue"

ALL_CODES = frozenset(
    {
        INVALID_URL,
        NOT_GITHUB,
        NOT_AN_ISSUE_URL,
        NOT_A_REPO_URL,
        REPO_MISMATCH,
        EMPTY_INPUT,
        REPO_NOT_FOUND,
        NOT_PYTHON,
        ISSUE_NOT_FOUND,
        NOT_AN_ISSUE,
    }
)

# GitHubAPIError codes
RATE_LIMITED = "rate_limited"
NETWORK_ERROR = "network_error"
SERVER_ERROR = "server_error"
AUTH_FAILED = "auth_failed"
UNEXPECTED_RESPONSE = "unexpected_response"

ALL_API_CODES = frozenset(
    {RATE_LIMITED, NETWORK_ERROR, SERVER_ERROR, AUTH_FAILED, UNEXPECTED_RESPONSE}
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


class GitHubAPIError(Exception):
    """GitHub or the network failed. `code` is stable; `message` is user-facing."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_API_CODES:
            raise ValueError(f"unknown GitHubAPIError code: {code!r}")
        if not message:
            raise ValueError("GitHubAPIError needs a non-empty message")
        super().__init__(message)
        self.code = code
        self.message = message
