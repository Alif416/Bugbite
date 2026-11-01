"""Errors raised for problems outside the program's own bugs.

Five families, because callers present them differently:

- `InputError`: the user can fix it (bad URL, repo not found, not Python).
- `GitHubAPIError`: the provider or network failed (rate limit, timeout).
- `SandboxError`: Docker or the sandbox container failed.
- `AdapterError`: a model provider failed or rejected a request.
- `PrivacyError`: the privacy rule refused to send code to a model.

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
NO_TESTS = "no_tests"

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
        NO_TESTS,
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

# SandboxError codes
DOCKER_UNAVAILABLE = "docker_unavailable"
IMAGE_UNAVAILABLE = "image_unavailable"
START_FAILED = "start_failed"
EXEC_FAILED = "exec_failed"
SANDBOX_CLOSED = "sandbox_closed"
BACKSTOP_TIMEOUT = "backstop_timeout"
WORKSPACE_FULL = "workspace_full"

ALL_SANDBOX_CODES = frozenset(
    {
        DOCKER_UNAVAILABLE,
        IMAGE_UNAVAILABLE,
        START_FAILED,
        EXEC_FAILED,
        SANDBOX_CLOSED,
        BACKSTOP_TIMEOUT,
        WORKSPACE_FULL,
    }
)

# AdapterError codes
RATE_LIMITED_MODEL = "rate_limited"
AUTH_FAILED_MODEL = "auth_failed"
CONTEXT_TOO_LONG = "context_too_long"
INVALID_REQUEST = "invalid_request"
SERVER_ERROR_MODEL = "server_error"
NETWORK_ERROR_MODEL = "network_error"
TIMEOUT_MODEL = "timeout"
BAD_RESPONSE = "bad_response"

ALL_ADAPTER_CODES = frozenset(
    {
        RATE_LIMITED_MODEL,
        AUTH_FAILED_MODEL,
        CONTEXT_TOO_LONG,
        INVALID_REQUEST,
        SERVER_ERROR_MODEL,
        NETWORK_ERROR_MODEL,
        TIMEOUT_MODEL,
        BAD_RESPONSE,
    }
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


class SandboxError(Exception):
    """Docker or the sandbox failed. `code` is stable; `message` is user-facing."""

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_SANDBOX_CODES:
            raise ValueError(f"unknown SandboxError code: {code!r}")
        if not message:
            raise ValueError("SandboxError needs a non-empty message")
        super().__init__(message)
        self.code = code
        self.message = message


class AdapterError(Exception):
    """A model provider failed or rejected a request.

    `code` is stable. `retry_after_s` is the provider's suggested wait, if it
    gave one; `status_code` is the HTTP status, if there was one. Messages must
    never contain API keys or request bodies.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after_s: float | None = None,
        status_code: int | None = None,
    ) -> None:
        if code not in ALL_ADAPTER_CODES:
            raise ValueError(f"unknown AdapterError code: {code!r}")
        if not message:
            raise ValueError("AdapterError needs a non-empty message")
        if retry_after_s is not None and retry_after_s < 0:
            raise ValueError("retry_after_s must not be negative")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after_s = retry_after_s
        self.status_code = status_code


# PrivacyError codes
PRIVATE_CODE_BLOCKED = "private_code_blocked"

ALL_PRIVACY_CODES = frozenset({PRIVATE_CODE_BLOCKED})


class PrivacyError(Exception):
    """Private code was about to go to a model that is not allowed to receive it.

    A family of its own on purpose: it is not a user typo (`InputError`) and not a provider
    fault (`AdapterError`), so retry, fallback, and repair logic that catches those cannot
    swallow it by accident. Messages never contain issue text, comments, or code.
    """

    def __init__(self, code: str, message: str) -> None:
        if code not in ALL_PRIVACY_CODES:
            raise ValueError(f"unknown PrivacyError code: {code!r}")
        if not message:
            raise ValueError("PrivacyError needs a non-empty message")
        super().__init__(message)
        self.code = code
        self.message = message
