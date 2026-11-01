"""Small safety helpers shared by the real adapters.

Providers sometimes echo credentials inside their own error text, and error text
ends up in logs and reports, so it is always redacted and shortened first.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

MAX_PROVIDER_MESSAGE_CHARS = 300

_BEARER = re.compile(r"(?i)bearer\s+\S+")


def shorten(text: str, limit: int = MAX_PROVIDER_MESSAGE_CHARS) -> str:
    """Collapse whitespace and cut to `limit` characters."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def redact(text: str, api_key: str | None) -> str:
    """Remove the API key and any bearer token from provider-supplied text."""
    if api_key and len(api_key) >= 4:
        text = text.replace(api_key, "[redacted]")
    return _BEARER.sub("Bearer [redacted]", text)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds to wait, from a Retry-After header given as seconds or as an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
