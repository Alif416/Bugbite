from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from bugbite.adapter._http import MAX_PROVIDER_MESSAGE_CHARS, parse_retry_after, redact, shorten


def test_shorten_collapses_whitespace_and_cuts():
    assert shorten("a  b\n\tc") == "a b c"
    assert shorten("x" * 1000).endswith("...") and len(shorten("x" * 1000)) == MAX_PROVIDER_MESSAGE_CHARS
    assert shorten("short") == "short" and shorten("") == ""
    assert shorten("x" * 50, limit=10) == "xxxxxxx..."


def test_redact_removes_the_key_and_bearer_tokens():
    key = "sk-test-0123456789"
    assert redact(f"bad key {key} here", key) == "bad key [redacted] here"
    assert redact("Authorization: Bearer abc.def", None) == "Authorization: Bearer [redacted]"
    assert redact(f"{key} and {key}", key) == "[redacted] and [redacted]"


@pytest.mark.parametrize("key", [None, "", "abc"])
def test_redact_ignores_missing_or_very_short_keys(key):
    assert redact("plain abc text", key) == "plain abc text"


@pytest.mark.parametrize("value, expected", [("7", 7.0), ("1.5", 1.5), (" 30 ", 30.0), ("0", 0.0)])
def test_retry_after_seconds(value, expected):
    assert parse_retry_after(value) == expected


def test_retry_after_dates():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=40), usegmt=True)
    past = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=40), usegmt=True)
    assert 30 < parse_retry_after(future) <= 41
    assert parse_retry_after(past) == 0.0


@pytest.mark.parametrize("value", [None, "", "soon", "-5", "1e3", "Mon, 99 Foo 2026"])
def test_unusable_retry_after_is_none(value):
    assert parse_retry_after(value) is None


def test_the_openai_adapter_still_exports_the_old_name():
    from bugbite.adapter.openai_compatible import parse_retry_after as old

    assert old is parse_retry_after
