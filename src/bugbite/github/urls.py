"""Offline parsing of GitHub repo and issue URLs.

The parsed values later feed `git clone` and API calls, so parsing is strict:
only github.com hosts, only GitHub-legal owner and repo names. No network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from bugbite.errors import (
    EMPTY_INPUT,
    INVALID_URL,
    NOT_A_REPO_URL,
    NOT_AN_ISSUE_URL,
    NOT_GITHUB,
    InputError,
)

_ALLOWED_HOSTS = frozenset({"github.com", "www.github.com"})
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
_NUMBER_RE = re.compile(r"[1-9][0-9]{0,9}")
_MAX_ISSUE_NUMBER = 2_147_483_647
_NON_ISSUE_SECTIONS = frozenset(
    {"pull", "pulls", "discussions", "actions", "commit", "commits", "tree", "blob", "releases"}
)


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class IssueRef:
    repo: RepoRef
    number: int


def _show(value: Any) -> str:
    """Quote the offending input safely for an error message."""
    text = repr(value)
    return text if len(text) <= 200 else text[:197] + "..."


def _split(raw: Any, what: str) -> list[str]:
    """Validate scheme and host, and return the non-empty path segments."""
    if not isinstance(raw, str) or not raw.strip():
        raise InputError(EMPTY_INPUT, f"The {what} is empty. Please provide a GitHub URL.")
    url = raw.strip()
    if any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in url):
        raise InputError(INVALID_URL, f"The {what} {_show(url)} contains illegal characters.")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise InputError(INVALID_URL, f"The {what} {_show(url)} is not a valid URL.") from None
    if parts.scheme not in ("http", "https") or not host:
        raise InputError(
            INVALID_URL, f"The {what} {_show(url)} must be a full http(s) URL such as https://github.com/owner/repo."
        )
    if parts.username is not None or parts.password is not None or port is not None:
        raise InputError(INVALID_URL, f"The {what} {_show(url)} must not contain credentials or a port.")
    if host not in _ALLOWED_HOSTS:
        raise InputError(NOT_GITHUB, f"The {what} {_show(url)} is not on github.com. Only GitHub is supported.")
    path = parts.path.strip("/")
    segments = path.split("/") if path else []
    if any(not seg for seg in segments):
        raise InputError(INVALID_URL, f"The {what} {_show(url)} has an empty path segment.")
    return segments


def _repo_from(segments: list[str], url_for_msg: str, what: str) -> RepoRef:
    owner, name = segments[0], segments[1]
    if not _OWNER_RE.fullmatch(owner):
        raise InputError(INVALID_URL, f"The {what} {_show(url_for_msg)} has an invalid owner name.")
    if not _REPO_RE.fullmatch(name) or name in (".", ".."):
        raise InputError(INVALID_URL, f"The {what} {_show(url_for_msg)} has an invalid repository name.")
    return RepoRef(owner=owner, name=name)


def parse_repo_url(url: Any) -> RepoRef:
    """Parse https://github.com/owner/name (optional .git, slash, query, fragment)."""
    segments = _split(url, "repository URL")
    if len(segments) != 2:
        raise InputError(
            NOT_A_REPO_URL,
            f"The repository URL {_show(url)} must look like https://github.com/owner/repo.",
        )
    name = segments[1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return _repo_from([segments[0], name], url, "repository URL")


def parse_issue_url(url: Any) -> IssueRef:
    """Parse https://github.com/owner/name/issues/123 (optional slash, query, fragment)."""
    segments = _split(url, "issue URL")
    if len(segments) != 4 or segments[2] != "issues":
        hint = ""
        if len(segments) >= 3 and segments[2] in _NON_ISSUE_SECTIONS:
            hint = f" It points at '{segments[2]}', not an issue."
        raise InputError(
            NOT_AN_ISSUE_URL,
            f"The issue URL {_show(url)} must look like https://github.com/owner/repo/issues/123.{hint}",
        )
    repo = _repo_from(segments[:2], url, "issue URL")
    number_text = segments[3]
    if not _NUMBER_RE.fullmatch(number_text) or int(number_text) > _MAX_ISSUE_NUMBER:
        raise InputError(
            INVALID_URL,
            f"The issue URL {_show(url)} has an invalid issue number; it must be a positive whole number.",
        )
    return IssueRef(repo=repo, number=int(number_text))
