"""How the Claude adapter reports failures. Mock transport, no network."""

import logging
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx2
import pytest
from claude_helpers import KEY, adapter_for, message

from bugbite.adapter import GenerationRequest, Message
from bugbite.errors import (
    AUTH_FAILED_MODEL,
    BAD_RESPONSE,
    CONTEXT_TOO_LONG,
    INVALID_REQUEST,
    NETWORK_ERROR_MODEL,
    RATE_LIMITED_MODEL,
    SERVER_ERROR_MODEL,
    TIMEOUT_MODEL,
    AdapterError,
)

REQUEST = GenerationRequest(messages=(Message.user("my private source code"),))


def fail_with(reply):
    adapter, rec = adapter_for(reply)
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    return info.value, rec


def api_error(status, text="something went wrong", headers=None, error_type="api_error"):
    return httpx2.Response(status, json={"type": "error", "error": {"type": error_type, "message": text}}, headers=headers)


@pytest.mark.parametrize(
    "status, expected",
    [
        (400, INVALID_REQUEST), (401, AUTH_FAILED_MODEL), (402, AUTH_FAILED_MODEL), (403, AUTH_FAILED_MODEL),
        (404, INVALID_REQUEST), (408, TIMEOUT_MODEL), (413, CONTEXT_TOO_LONG), (418, INVALID_REQUEST),
        (422, INVALID_REQUEST), (429, RATE_LIMITED_MODEL), (500, SERVER_ERROR_MODEL), (502, SERVER_ERROR_MODEL),
        (503, SERVER_ERROR_MODEL), (529, SERVER_ERROR_MODEL),
    ],
)  # fmt: skip
def test_status_mapping(status, expected):
    error, rec = fail_with(api_error(status))
    assert error.code == expected and error.status_code == status
    assert len(rec.requests) == 1  # the SDK did not retry


@pytest.mark.parametrize(
    "wording",
    [
        "prompt is too long: 250000 tokens > 200000 maximum",
        "input length and `max_tokens` exceed context limit: 190000 + 20000 > 200000",
        "The request exceeds the context window of this model",
        "This model's maximum context length is 8192 tokens",
        "too many tokens in the request",
    ],
)
@pytest.mark.parametrize("status", [400, 422])
def test_context_overflow_wording(status, wording):
    assert fail_with(api_error(status, wording, error_type="invalid_request_error"))[0].code == CONTEXT_TOO_LONG


def test_context_wording_on_another_status_does_not_change_the_code():
    assert fail_with(api_error(500, "prompt is too long"))[0].code == SERVER_ERROR_MODEL


# -- messages -----------------------------------------------------------------------------------------------


def test_the_apis_own_message_is_included_without_the_sdks_body_dump():
    error, _ = fail_with(api_error(404, "model: claude-haiku-9 not found", error_type="not_found_error"))
    assert "model: claude-haiku-9 not found" in error.message and "api.anthropic.com" in error.message
    assert "Error code:" not in error.message and "{'type'" not in error.message


@pytest.mark.parametrize(
    "response, fragment",
    [
        (httpx2.Response(400, json={"error": "plain string error"}), "plain string error"),
        (httpx2.Response(400, json={"message": "top-level message"}), "top-level message"),
        (httpx2.Response(502, text="<html>bad gateway</html>"), "bad gateway"),
    ],
)
def test_other_error_body_shapes(response, fragment):
    assert fragment in fail_with(response)[0].message


@pytest.mark.parametrize("response", [httpx2.Response(400, json={}), httpx2.Response(500, text=""), httpx2.Response(502, json=[1, 2])])
def test_empty_or_odd_bodies_still_give_a_clear_message(response):
    error, _ = fail_with(response)
    assert "HTTP" in error.message and "api.anthropic.com" in error.message


def test_long_messages_are_shortened_and_whitespace_collapsed():
    error, _ = fail_with(api_error(400, "word " * 500))
    assert len(error.message) < 400 and error.message.endswith("...")
    error, _ = fail_with(api_error(400, "line one\n\n   line   two"))
    assert "line one line two" in error.message


def test_request_content_never_appears_in_error_messages():
    for status in (400, 401, 404, 429, 500, 529):
        assert "private source code" not in fail_with(api_error(status))[0].message


# -- credentials never leak ------------------------------------------------------------------------------------------


def test_a_provider_echoing_the_key_gets_it_redacted():
    error, _ = fail_with(api_error(401, f"invalid x-api-key: {KEY}"))
    assert KEY not in error.message and "[redacted]" in error.message


def test_bearer_tokens_are_redacted():
    error, _ = fail_with(api_error(401, "bad header Authorization: Bearer abc123def456"))
    assert "abc123def456" not in error.message and "Bearer [redacted]" in error.message


def test_the_key_is_in_no_error_attribute_or_log(caplog):
    with caplog.at_level(logging.DEBUG):
        for status in (400, 401, 429, 500):
            error, _ = fail_with(api_error(status, f"echo {KEY}"))
            assert KEY not in repr(error) and KEY not in str(error.args) and KEY not in error.message
        adapter, _ = adapter_for(message())
        adapter.generate(REQUEST)
    assert KEY not in caplog.text


# -- retry-after ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("header, expected", [("9", 9.0), ("1.5", 1.5), (" 30 ", 30.0)])
def test_retry_after_in_seconds(header, expected):
    error, _ = fail_with(api_error(429, headers={"retry-after": header}))
    assert error.code == RATE_LIMITED_MODEL and error.retry_after_s == expected


def test_retry_after_as_an_http_date():
    when = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=40), usegmt=True)
    assert 30 < fail_with(api_error(429, headers={"retry-after": when}))[0].retry_after_s <= 41


@pytest.mark.parametrize("header", ["", "soon", "-5"])
def test_unusable_retry_after_is_none(header):
    assert fail_with(api_error(429, headers={"retry-after": header}))[0].retry_after_s is None


def test_overloaded_errors_carry_retry_after_too():
    assert fail_with(api_error(529, headers={"retry-after": "12"}))[0].retry_after_s == 12.0


# -- transport failures --------------------------------------------------------------------------------------------------------


def raising(exc_type):
    def reply(request):
        raise exc_type("boom", request=request)

    return reply


@pytest.mark.parametrize("exc", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.WriteTimeout, httpx2.PoolTimeout])
def test_timeouts(exc):
    error, rec = fail_with(raising(exc))
    assert error.code == TIMEOUT_MODEL and "timed out" in error.message and len(rec.requests) == 1


@pytest.mark.parametrize("exc", [httpx2.ConnectError, httpx2.ReadError, httpx2.RemoteProtocolError])
def test_connection_problems(exc):
    error, _ = fail_with(raising(exc))
    assert error.code == NETWORK_ERROR_MODEL and "api.anthropic.com" in error.message


def test_transport_errors_never_leak_the_key_or_chain_it():
    def reply(request):
        raise httpx2.ConnectError(f"failed with {KEY}", request=request)

    error, _ = fail_with(reply)
    assert KEY not in error.message and error.__cause__ is None


def test_redirects_are_not_followed():
    error, rec = fail_with(httpx2.Response(302, headers={"location": "https://elsewhere.example/v1/messages"}))
    assert error.code == BAD_RESPONSE and len(rec.requests) == 1
