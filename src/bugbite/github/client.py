"""Minimal GitHub REST client for reading repos, issues, and comments.

The token is supplied by the caller and used only in the Authorization header
for requests to `base_url`. It is never read from the environment, logged,
or included in error messages or `repr`. No retries: errors are raised
immediately (retry and backoff arrive with the queue and resume work).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from bugbite.errors import (
    AUTH_FAILED,
    ISSUE_NOT_FOUND,
    NETWORK_ERROR,
    NOT_AN_ISSUE,
    RATE_LIMITED,
    REPO_NOT_FOUND,
    SERVER_ERROR,
    UNEXPECTED_RESPONSE,
    GitHubAPIError,
    InputError,
)
from bugbite.github.models import CommentData, IssueData, RepoInfo
from bugbite.github.urls import IssueRef, RepoRef

API_URL = "https://api.github.com"
DEFAULT_MAX_CHARS = 20_000
_PER_PAGE = 100


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _field(data: dict[str, Any], key: str, kind: type, what: str) -> Any:
    value = data.get(key)
    if not isinstance(value, kind):
        raise GitHubAPIError(UNEXPECTED_RESPONSE, f"GitHub returned an unexpected {what} response (bad '{key}').")
    return value


def _login(user: Any) -> str:
    if isinstance(user, dict) and isinstance(user.get("login"), str):
        return user["login"]
    return ""


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = API_URL,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self._token = token or None
        self._base_url = base_url.rstrip("/")
        self._max_chars = max_chars
        self._owns_client = client is None
        self._http = client or httpx.Client(timeout=timeout)

    def __repr__(self) -> str:
        return f"GitHubClient(base_url={self._base_url!r}, authenticated={self._token is not None})"

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "bugbite",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        # Only ever send the token to the configured API host.
        if not url.startswith(self._base_url + "/"):
            raise GitHubAPIError(UNEXPECTED_RESPONSE, "GitHub returned a link to an unexpected host; refusing to follow it.")
        try:
            return self._http.get(url, params=params, headers=self._headers(), follow_redirects=True)
        except httpx.TimeoutException:
            raise GitHubAPIError(NETWORK_ERROR, "The request to GitHub timed out.") from None
        except httpx.HTTPError:
            raise GitHubAPIError(NETWORK_ERROR, "Could not reach GitHub (network error).") from None

    def _check(self, resp: httpx.Response) -> None:
        """Raise a GitHubAPIError for any non-success status (404/410 handled by callers)."""
        status = resp.status_code
        if 200 <= status < 300:
            return
        if status == 401:
            raise GitHubAPIError(AUTH_FAILED, "GitHub rejected the token (401). Check that GITHUB_TOKEN is valid.")
        if status in (403, 429):
            remaining = resp.headers.get("x-ratelimit-remaining")
            if status == 429 or remaining == "0" or "rate limit" in resp.text.lower():
                reset = resp.headers.get("x-ratelimit-reset", "")
                when = ""
                if reset.isdigit():
                    stamp = datetime.fromtimestamp(int(reset), tz=timezone.utc)
                    when = f" It resets at {stamp:%Y-%m-%d %H:%M} UTC."
                raise GitHubAPIError(RATE_LIMITED, f"GitHub rate limit reached.{when}")
            raise GitHubAPIError(AUTH_FAILED, "GitHub refused access (403). The token may lack permission for this repository.")
        if status >= 500:
            raise GitHubAPIError(SERVER_ERROR, f"GitHub had a server problem (HTTP {status}).")
        raise GitHubAPIError(UNEXPECTED_RESPONSE, f"GitHub returned an unexpected response (HTTP {status}).")

    @staticmethod
    def _json(resp: httpx.Response, kind: type, what: str) -> Any:
        try:
            data = resp.json()
        except ValueError:
            raise GitHubAPIError(UNEXPECTED_RESPONSE, f"GitHub returned an unreadable {what} response.") from None
        if not isinstance(data, kind):
            raise GitHubAPIError(UNEXPECTED_RESPONSE, f"GitHub returned an unexpected {what} response.")
        return data

    # -- public API ------------------------------------------------------

    def get_repo(self, repo: RepoRef) -> RepoInfo:
        resp = self._get(f"{self._base_url}/repos/{repo.owner}/{repo.name}")
        if resp.status_code == 404:
            hint = "" if self._token else " No GITHUB_TOKEN was provided; set one to access private repositories."
            raise InputError(
                REPO_NOT_FOUND,
                f"Repository {repo.full_name} was not found. It may not exist or may be private.{hint}",
            )
        self._check(resp)
        data = self._json(resp, dict, "repository")
        language = data.get("language")
        if language is not None and not isinstance(language, str):
            raise GitHubAPIError(UNEXPECTED_RESPONSE, "GitHub returned an unexpected repository response (bad 'language').")
        return RepoInfo(
            full_name=_field(data, "full_name", str, "repository"),
            private=_field(data, "private", bool, "repository"),
            language=language,
            default_branch=_field(data, "default_branch", str, "repository"),
            archived=bool(data.get("archived", False)),
            fork=bool(data.get("fork", False)),
            html_url=_field(data, "html_url", str, "repository"),
        )

    def get_issue(self, issue: IssueRef) -> IssueData:
        resp = self._get(f"{self._base_url}/repos/{issue.repo.owner}/{issue.repo.name}/issues/{issue.number}")
        if resp.status_code in (404, 410):
            raise InputError(
                ISSUE_NOT_FOUND,
                f"Issue #{issue.number} was not found in {issue.repo.full_name}. It may not exist or may have been deleted.",
            )
        self._check(resp)
        data = self._json(resp, dict, "issue")
        if "pull_request" in data:
            raise InputError(
                NOT_AN_ISSUE,
                f"#{issue.number} in {issue.repo.full_name} is a pull request, not an issue.",
            )
        title, title_cut = _clip(_field(data, "title", str, "issue"), self._max_chars)
        body, body_cut = _clip(data.get("body") or "", self._max_chars)
        raw_labels = data.get("labels") or []
        labels = tuple(
            item["name"] if isinstance(item, dict) and isinstance(item.get("name"), str) else item
            for item in raw_labels
            if (isinstance(item, dict) and isinstance(item.get("name"), str)) or isinstance(item, str)
        )
        return IssueData(
            number=_field(data, "number", int, "issue"),
            title=title,
            body=body,
            labels=labels,
            state=_field(data, "state", str, "issue"),
            author=_login(data.get("user")),
            html_url=_field(data, "html_url", str, "issue"),
            truncated=title_cut or body_cut,
        )

    def get_comments(self, issue: IssueRef, max_comments: int = 50) -> tuple[tuple[CommentData, ...], bool]:
        """Return (comments, truncated). `truncated` is True if more comments existed."""
        if max_comments < 0:
            raise ValueError("max_comments must not be negative")
        url: str | None = (
            f"{self._base_url}/repos/{issue.repo.owner}/{issue.repo.name}/issues/{issue.number}/comments"
        )
        params: dict[str, Any] | None = {"per_page": _PER_PAGE}
        comments: list[CommentData] = []
        truncated = False
        while url:
            resp = self._get(url, params)
            if resp.status_code in (404, 410):
                raise InputError(
                    ISSUE_NOT_FOUND,
                    f"Issue #{issue.number} was not found in {issue.repo.full_name}. It may not exist or may have been deleted.",
                )
            self._check(resp)
            page = self._json(resp, list, "comments")
            for raw in page:
                if not isinstance(raw, dict):
                    raise GitHubAPIError(UNEXPECTED_RESPONSE, "GitHub returned an unexpected comments response.")
                if len(comments) >= max_comments:
                    truncated = True
                    break
                body, cut = _clip(raw.get("body") or "", self._max_chars)
                comments.append(
                    CommentData(
                        author=_login(raw.get("user")),
                        body=body,
                        created_at=raw.get("created_at") if isinstance(raw.get("created_at"), str) else "",
                        truncated=cut,
                    )
                )
            if truncated:
                break
            url = resp.links.get("next", {}).get("url")
            params = None  # the next URL already carries its query string
        return tuple(comments), truncated
