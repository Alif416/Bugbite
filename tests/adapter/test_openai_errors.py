"""How failures are reported. Mock transport, no network."""

import logging
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from openai_helpers import KEY, adapter_for, completion, model

from bugbite.adapter import GenerationRequest, Message
from bugbite.adapter.openai_compatible import parse_retry_after
from bugbite.config import ConfigError
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


def fail_with(reply, **kwargs):
    adapter, rec = adapter_for(reply, **kwargs)
    with pytest.raises(AdapterError) as info:
        adapter.generate(REQUEST)
    return info.value, rec


def http(status, body=None, text=None, headers=None):
    if text is not None:
        return httpx.Response(status, text=text, headers=headers)
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


# -- status mapping -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (401, {"error": {"message": "Invalid API key", "type": "invalid_request_error"}}, AUTH_FAILED_MODEL),
        (402, {"error": {"message": "Insufficient credits", "code": 402}}, AUTH_FAILED_MODEL),
        (403, {"error": {"message": "Forbidden"}}, AUTH_FAILED_MODEL),
        (404, {"error": "model 'x' not found, try pulling it first"}, INVALID_REQUEST),
        (422, {"detail": [{"msg": "bad field"}]}, INVALID_REQUEST),
        (400, {"error": {"message": "Unsupported parameter"}}, INVALID_REQUEST),
        (418, {}, INVALID_REQUEST),
        (408, {"error": {"message": "Request timeout"}}, TIMEOUT_MODEL),
        (429, {"error": {"message": "Rate limit reached"}}, RATE_LIMITED_MODEL),
        (500, {"error": {"message": "Internal error"}}, SERVER_ERROR_MODEL),
        (502, {}, SERVER_ERROR_MODEL),
        (503, {"error": "overloaded"}, SERVER_ERROR_MODEL),
        (413, {"error": {"message": "Request too large for model on tokens per minute (TPM): Limit 6000, Requested 9000"}}, CONTEXT_TOO_LONG),
        (301, {}, BAD_RESPONSE),
        (302, {}, BAD_RESPONSE),
        (307, {}, BAD_RESPONSE),
    ],
)
def test_status_mapping(status, body, expected):
    error, rec = fail_with(http(status, body))
    assert error.code == expected and error.status_code == status
    assert len(rec.requests) == 1  # no retries, no redirect following


@pytest.mark.parametrize(
    "body",
    [
        {"error": {"message": "This model's maximum context length is 8192 tokens. However, you requested 9000.", "code": "context_length_exceeded"}},
        {"error": {"message": "Input is too long for the context window"}},
        {"error": {"message": "something", "code": "context_length_exceeded"}},
        {"object": "error", "message": "This model's maximum context length is 4096 tokens", "type": "BadRequestError", "code": 400},
        {"error": {"message": "Please reduce the length of the messages or completion."}},
        {"error": "prompt is too long: 9000 tokens > 8192 maximum"},
        {"error": {"message": "too many tokens in the prompt"}},
    ],
)
@pytest.mark.parametrize("status", [400, 422])
def test_context_overflow_wording_in_many_shapes(status, body):
    assert fail_with(http(status, body))[0].code == CONTEXT_TOO_LONG


def test_context_wording_in_a_non_400_error_does_not_change_the_code():
    assert fail_with(http(500, {"error": {"message": "maximum context length"}}))[0].code == SERVER_ERROR_MODEL


# -- error body shapes and messages ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response, fragment",
    [
        (http(400, {"error": {"message": "nested message", "type": "t"}}), "nested message"),
        (http(400, {"error": "plain string error"}), "plain string error"),
        (http(400, {"message": "top-level message"}), "top-level message"),
        (http(400, text="raw text body"), "raw text body"),
        (http(400, text="<html><body>Bad request</body></html>"), "Bad request"),
    ],
)
def test_the_providers_message_is_included(response, fragment):
    error, _ = fail_with(response)
    assert fragment in error.message and "llm.test" in error.message


@pytest.mark.parametrize("response", [http(400, {}), http(500, text=""), http(502, body=[1, 2])])
def test_empty_or_odd_error_bodies_still_give_a_clear_message(response):
    error, _ = fail_with(response)
    assert "HTTP" in error.message and "llm.test" in error.message


def test_long_provider_messages_are_shortened():
    error, _ = fail_with(http(400, {"error": {"message": "word " * 500}}))
    assert len(error.message) < 400 and error.message.endswith("...")


def test_whitespace_in_provider_messages_is_collapsed():
    error, _ = fail_with(http(400, {"error": {"message": "line one\n\n   line   two\t!"}}))
    assert "line one line two !" in error.message


def test_request_content_never_appears_in_error_messages():
    for status in (400, 401, 404, 429, 500):
        error, _ = fail_with(http(status, {"error": {"message": "nope"}}))
        assert "private source code" not in error.message


def test_a_provider_echoing_the_key_gets_it_redacted():
    body = {"error": {"message": f"Incorrect API key provided: {KEY}. Check your key."}}
    error, _ = fail_with(http(401, body))
    assert KEY not in error.message and "[redacted]" in error.message


def test_bearer_tokens_in_provider_text_are_redacted():
    error, _ = fail_with(http(401, text="Invalid header: Authorization: Bearer abc123def456"))
    assert "abc123def456" not in error.message and "Bearer [redacted]" in error.message


def test_the_key_is_redacted_from_the_code_field_and_plain_text_bodies_too():
    error, _ = fail_with(http(400, {"error": {"message": "x", "code": f"bad-{KEY}"}}))
    assert KEY not in error.message
    error, _ = fail_with(http(500, text=f"upstream said {KEY}"))
    assert KEY not in error.message


# -- retry-after -----------------------------------------------------------------------------------------------------------


def future(seconds):
    return format_datetime(datetime.now(timezone.utc) + timedelta(seconds=seconds), usegmt=True)


@pytest.mark.parametrize("header, expected", [("7", 7.0), ("1.5", 1.5), (" 30 ", 30.0), ("0", 0.0)])
def test_retry_after_in_seconds(header, expected):
    error, _ = fail_with(http(429, {"error": "slow down"}, headers={"retry-after": header}))
    assert error.code == RATE_LIMITED_MODEL and error.retry_after_s == expected


def test_retry_after_as_an_http_date():
    error, _ = fail_with(http(429, {}, headers={"retry-after": future(40)}))
    assert 30 < error.retry_after_s <= 41


def test_retry_after_in_the_past_is_zero():
    past = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=60), usegmt=True)
    assert fail_with(http(429, {}, headers={"retry-after": past}))[0].retry_after_s == 0.0


@pytest.mark.parametrize("header", ["", "soon", "-5", "1e3", "Mon, 99 Foo 2026"])
def test_unusable_retry_after_is_none(header):
    assert fail_with(http(429, {}, headers={"retry-after": header}))[0].retry_after_s is None


def test_no_retry_after_header_is_none_and_other_errors_have_none():
    assert fail_with(http(429, {}))[0].retry_after_s is None
    assert fail_with(http(500, {}, headers={"retry-after": "5"}))[0].retry_after_s is None


def test_parse_retry_after_directly():
    assert parse_retry_after(None) is None and parse_retry_after("12") == 12.0


# -- problems inside a 200 -------------------------------------------------------------------------------------------------


def test_an_error_object_inside_a_200_is_mapped_by_its_code():
    error, _ = fail_with({"error": {"message": "rate limited upstream", "code": 429}})
    assert error.code == RATE_LIMITED_MODEL
    error, _ = fail_with({"error": {"message": "upstream down", "code": 502}})
    assert error.code == SERVER_ERROR_MODEL


def test_an_error_object_inside_a_200_without_a_numeric_code_is_a_bad_response():
    error, _ = fail_with({"error": {"message": "provider hiccup", "code": "weird"}})
    assert error.code == BAD_RESPONSE and "provider hiccup" in error.message


def test_a_choices_list_wins_over_a_stray_error_field():
    body = completion("fine")
    body["error"] = {"message": "ignored"}
    adapter, _ = adapter_for(body)
    assert adapter.generate(REQUEST).text == "fine"


@pytest.mark.parametrize("response", [http(200, text="not json at all"), http(200, text=""), http(200, body=[1, 2, 3]), http(200, body="a string")])
def test_unreadable_200_responses_are_a_bad_response(response):
    error, _ = fail_with(response)
    assert error.code == BAD_RESPONSE


# -- transport failures --------------------------------------------------------------------------------------------------------


def raising(exc_type):
    def reply(request):
        raise exc_type("boom", request=request)

    return reply


@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeouts(exc):
    error, rec = fail_with(raising(exc))
    assert error.code == TIMEOUT_MODEL and "timed out" in error.message and len(rec.requests) == 1


@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.NetworkError])
def test_connection_problems(exc):
    error, _ = fail_with(raising(exc))
    assert error.code == NETWORK_ERROR_MODEL and "llm.test" in error.message


def test_transport_errors_never_leak_the_key_or_chain_it():
    def reply(request):
        raise httpx.ConnectError(f"failed with {KEY}", request=request)

    error, _ = fail_with(reply)
    assert KEY not in error.message and error.__cause__ is None


@pytest.mark.parametrize("url", ["http://", "http://host:notaport/v1", "http://host\x00/v1"])
def test_an_invalid_base_url_is_reported_when_the_adapter_is_built(url):
    with pytest.raises(ConfigError, match="not a valid URL"):
        adapter_for(completion(), config=model(base_url=url))


# -- the key never leaks anywhere ----------------------------------------------------------------------------------------------------


def test_the_key_is_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        for status in (401, 429, 500):
            fail_with(http(status, {"error": {"message": f"details {KEY}"}}))
        adapter, _ = adapter_for(completion())
        adapter.generate(REQUEST)
    assert KEY not in caplog.text


def test_the_key_is_not_in_any_error_attribute():
    for status in (400, 401, 429, 500):
        error, _ = fail_with(http(status, {"error": {"message": f"echo {KEY}"}}))
        assert KEY not in repr(error) and KEY not in str(error.args) and KEY not in error.message
