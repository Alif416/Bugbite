import pytest

from bugbite import errors
from bugbite.errors import (
    ALL_ADAPTER_CODES,
    ALL_API_CODES,
    ALL_CODES,
    ALL_SANDBOX_CODES,
    AdapterError,
    GitHubAPIError,
    InputError,
    SandboxError,
)


def test_codes_are_stable():
    assert ALL_CODES == {
        "invalid_url",
        "not_github",
        "not_an_issue_url",
        "not_a_repo_url",
        "repo_mismatch",
        "empty_input",
        "repo_not_found",
        "not_python",
        "issue_not_found",
        "not_an_issue",
        "no_tests",
    }


def test_api_codes_are_stable():
    assert ALL_API_CODES == {
        "rate_limited",
        "network_error",
        "server_error",
        "auth_failed",
        "unexpected_response",
    }


@pytest.mark.parametrize("code", sorted(ALL_API_CODES))
def test_api_error_carries_code_and_message(code):
    err = GitHubAPIError(code, "try again later")
    assert err.code == code
    assert err.message == "try again later"
    assert str(err) == "try again later"


def test_api_error_validates_code_and_message():
    with pytest.raises(ValueError):
        GitHubAPIError("made_up", "x")
    with pytest.raises(ValueError):
        GitHubAPIError("rate_limited", "")
    with pytest.raises(ValueError):
        GitHubAPIError("invalid_url", "x")  # an InputError code, not an API one


@pytest.mark.parametrize("code", sorted(ALL_CODES))
def test_error_carries_code_and_message(code):
    err = InputError(code, "something readable")
    assert err.code == code
    assert err.message == "something readable"
    assert str(err) == "something readable"


def test_unknown_code_rejected():
    with pytest.raises(ValueError):
        InputError("made_up", "x")


def test_empty_message_rejected():
    with pytest.raises(ValueError):
        InputError(errors.INVALID_URL, "")


def test_sandbox_codes_are_stable():
    assert ALL_SANDBOX_CODES == {
        "docker_unavailable",
        "image_unavailable",
        "start_failed",
        "exec_failed",
        "sandbox_closed",
        "backstop_timeout",
        "workspace_full",
    }


@pytest.mark.parametrize("code", sorted(ALL_SANDBOX_CODES))
def test_sandbox_error_carries_code_and_message(code):
    err = SandboxError(code, "docker is down")
    assert err.code == code
    assert err.message == "docker is down"
    assert str(err) == "docker is down"


def test_sandbox_error_validates_code_and_message():
    with pytest.raises(ValueError):
        SandboxError("made_up", "x")
    with pytest.raises(ValueError):
        SandboxError("start_failed", "")
    with pytest.raises(ValueError):
        SandboxError("rate_limited", "x")  # a GitHubAPIError code


def test_adapter_codes_are_stable():
    assert ALL_ADAPTER_CODES == {
        "rate_limited",
        "auth_failed",
        "context_too_long",
        "invalid_request",
        "server_error",
        "network_error",
        "timeout",
        "bad_response",
    }


@pytest.mark.parametrize("code", sorted(ALL_ADAPTER_CODES))
def test_adapter_error_carries_code_and_message(code):
    err = AdapterError(code, "the provider said no")
    assert (err.code, err.message, str(err)) == (code, "the provider said no", "the provider said no")
    assert err.retry_after_s is None and err.status_code is None


def test_adapter_error_carries_retry_and_status():
    err = AdapterError("rate_limited", "slow down", retry_after_s=2.5, status_code=429)
    assert err.retry_after_s == 2.5 and err.status_code == 429


def test_adapter_error_validates_arguments():
    with pytest.raises(ValueError):
        AdapterError("made_up", "x")
    with pytest.raises(ValueError):
        AdapterError("timeout", "")
    with pytest.raises(ValueError):
        AdapterError("timeout", "x", retry_after_s=-1)
    with pytest.raises(ValueError):
        AdapterError("start_failed", "x")  # a SandboxError code, not an adapter one
