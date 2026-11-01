import httpx
import pytest

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
from bugbite.github import GitHubClient, IssueRef, RepoRef

from .conftest import BASE, comment_json, issue_json, repo_json

REPO = RepoRef("octo", "hello")
ISSUE = IssueRef(REPO, 7)
TOKEN = "fake-test-token-not-a-secret-123"


def json_handler(payload, status=200, headers=None):
    return lambda request: httpx.Response(status, json=payload, headers=headers)


# -- repo ---------------------------------------------------------------


def test_get_repo(make_client):
    client, rec = make_client(json_handler(repo_json(private=True, archived=True, fork=True)))
    info = client.get_repo(REPO)
    assert info.full_name == "octo/hello"
    assert info.private and info.archived and info.fork
    assert info.language == "Python"
    assert info.default_branch == "main"
    assert rec.paths == ["/repos/octo/hello"]


def test_repo_without_language(make_client):
    client, _ = make_client(json_handler(repo_json(language=None)))
    assert client.get_repo(REPO).language is None


def test_authorization_header_only_with_token(make_client):
    client, rec = make_client(json_handler(repo_json()), token=TOKEN)
    client.get_repo(REPO)
    assert rec.requests[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert rec.requests[0].headers["accept"] == "application/vnd.github+json"

    client, rec = make_client(json_handler(repo_json()))
    client.get_repo(REPO)
    assert "authorization" not in rec.requests[0].headers


def test_repo_404_without_token_suggests_token(make_client):
    client, _ = make_client(json_handler({"message": "Not Found"}, 404))
    with pytest.raises(InputError) as info:
        client.get_repo(REPO)
    assert info.value.code == REPO_NOT_FOUND
    assert "octo/hello" in info.value.message
    assert "GITHUB_TOKEN" in info.value.message


def test_repo_404_with_token_does_not_suggest_token(make_client):
    client, _ = make_client(json_handler({"message": "Not Found"}, 404), token=TOKEN)
    with pytest.raises(InputError) as info:
        client.get_repo(REPO)
    assert info.value.code == REPO_NOT_FOUND
    assert "GITHUB_TOKEN" not in info.value.message


def test_redirect_is_followed(make_client):
    def handler(request):
        if request.url.path == "/repos/octo/hello":
            return httpx.Response(301, headers={"location": f"{BASE}/repositories/42"})
        return httpx.Response(200, json=repo_json(full_name="octo/renamed"))

    client, rec = make_client(handler)
    assert client.get_repo(REPO).full_name == "octo/renamed"
    assert rec.paths == ["/repos/octo/hello", "/repositories/42"]


# -- issue --------------------------------------------------------------


def test_get_issue(make_client):
    client, rec = make_client(json_handler(issue_json()))
    issue = client.get_issue(ISSUE)
    assert issue.number == 7
    assert issue.title == "Crash on empty input"
    assert issue.body == "Steps to reproduce..."
    assert issue.labels == ("bug", "good first issue")
    assert issue.state == "open"
    assert issue.author == "reporter"
    assert issue.truncated is False
    assert rec.paths == ["/repos/octo/hello/issues/7"]


def test_null_body_and_missing_user(make_client):
    client, _ = make_client(json_handler(issue_json(body=None, user=None)))
    issue = client.get_issue(ISSUE)
    assert issue.body == ""
    assert issue.author == ""


@pytest.mark.parametrize("status", [404, 410])
def test_issue_not_found(make_client, status):
    client, _ = make_client(json_handler({"message": "x"}, status))
    with pytest.raises(InputError) as info:
        client.get_issue(ISSUE)
    assert info.value.code == ISSUE_NOT_FOUND


def test_pull_request_is_not_an_issue(make_client):
    client, _ = make_client(json_handler(issue_json(pull_request={"url": "x"})))
    with pytest.raises(InputError) as info:
        client.get_issue(ISSUE)
    assert info.value.code == NOT_AN_ISSUE
    assert "pull request" in info.value.message


def test_long_body_and_title_are_cut_and_flagged(make_client):
    client, _ = make_client(json_handler(issue_json(body="x" * 50, title="t" * 50)), max_chars=10)
    issue = client.get_issue(ISSUE)
    assert issue.body == "x" * 10
    assert issue.title == "t" * 10
    assert issue.truncated is True


def test_body_exactly_at_limit_is_not_flagged(make_client):
    client, _ = make_client(json_handler(issue_json(body="x" * 10, title="short")), max_chars=10)
    assert client.get_issue(ISSUE).truncated is False


# -- comments -----------------------------------------------------------


def test_get_comments_single_page(make_client):
    client, rec = make_client(json_handler([comment_json(1), comment_json(2)]))
    comments, truncated = client.get_comments(ISSUE)
    assert [c.body for c in comments] == ["comment 1", "comment 2"]
    assert comments[0].author == "user1"
    assert truncated is False
    assert rec.requests[0].url.params["per_page"] == "100"


def test_comments_paginate(make_client):
    def handler(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[comment_json(3)])
        return httpx.Response(
            200,
            json=[comment_json(1), comment_json(2)],
            headers={"link": f'<{BASE}/repos/octo/hello/issues/7/comments?per_page=100&page=2>; rel="next"'},
        )

    client, rec = make_client(handler)
    comments, truncated = client.get_comments(ISSUE)
    assert [c.body for c in comments] == ["comment 1", "comment 2", "comment 3"]
    assert truncated is False
    assert len(rec.requests) == 2


def test_comments_truncated_at_cap(make_client):
    client, _ = make_client(json_handler([comment_json(n) for n in range(5)]))
    comments, truncated = client.get_comments(ISSUE, max_comments=3)
    assert len(comments) == 3
    assert truncated is True


def test_comments_exactly_at_cap_not_truncated(make_client):
    client, _ = make_client(json_handler([comment_json(n) for n in range(3)]))
    comments, truncated = client.get_comments(ISSUE, max_comments=3)
    assert len(comments) == 3
    assert truncated is False


def test_comments_cap_hit_across_pages_stops_fetching(make_client):
    def handler(request):
        return httpx.Response(
            200,
            json=[comment_json(1), comment_json(2)],
            headers={"link": f'<{BASE}/repos/octo/hello/issues/7/comments?page=2>; rel="next"'},
        )

    client, rec = make_client(handler)
    comments, truncated = client.get_comments(ISSUE, max_comments=2)
    assert len(comments) == 2
    assert truncated is True
    assert len(rec.requests) == 2  # the second page was needed to learn more existed


def test_comment_text_is_cut_and_flagged(make_client):
    client, _ = make_client(json_handler([comment_json(1, body="y" * 30), comment_json(2, body=None)]), max_chars=10)
    comments, _ = client.get_comments(ISSUE)
    assert comments[0].body == "y" * 10 and comments[0].truncated is True
    assert comments[1].body == "" and comments[1].truncated is False


def test_deleted_comment_author(make_client):
    client, _ = make_client(json_handler([comment_json(1, user=None)]))
    comments, _ = client.get_comments(ISSUE)
    assert comments[0].author == ""


def test_negative_max_comments_rejected(make_client):
    client, _ = make_client(json_handler([]))
    with pytest.raises(ValueError):
        client.get_comments(ISSUE, max_comments=-1)


def test_comments_404(make_client):
    client, _ = make_client(json_handler({"message": "x"}, 404))
    with pytest.raises(InputError) as info:
        client.get_comments(ISSUE)
    assert info.value.code == ISSUE_NOT_FOUND


def test_next_link_to_other_host_is_refused_and_token_not_sent(make_client):
    def handler(request):
        assert request.url.host == "api.github.com"
        return httpx.Response(
            200,
            json=[comment_json(1)],
            headers={"link": '<https://evil.example/steal?page=2>; rel="next"'},
        )

    client, rec = make_client(handler, token=TOKEN)
    with pytest.raises(GitHubAPIError) as info:
        client.get_comments(ISSUE)
    assert info.value.code == UNEXPECTED_RESPONSE
    assert len(rec.requests) == 1


# -- error mapping ------------------------------------------------------


def test_401_is_auth_failed(make_client):
    client, _ = make_client(json_handler({"message": "Bad credentials"}, 401), token=TOKEN)
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == AUTH_FAILED


def test_403_without_rate_limit_is_auth_failed(make_client):
    client, _ = make_client(json_handler({"message": "Forbidden"}, 403))
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == AUTH_FAILED


def test_403_with_exhausted_limit_is_rate_limited_with_reset_time(make_client):
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"}
    client, _ = make_client(json_handler({"message": "API rate limit exceeded"}, 403, headers))
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == RATE_LIMITED
    assert "2023-11-14 22:13 UTC" in info.value.message


def test_429_is_rate_limited(make_client):
    client, _ = make_client(json_handler({"message": "slow down"}, 429))
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == RATE_LIMITED


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_server_error(make_client, status):
    client, _ = make_client(json_handler({}, status))
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == SERVER_ERROR


def test_other_status_is_unexpected(make_client):
    client, _ = make_client(json_handler({}, 422))
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == UNEXPECTED_RESPONSE


def test_timeout_is_network_error(make_client):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(handler)
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == NETWORK_ERROR
    assert "timed out" in info.value.message


def test_connection_error_is_network_error(make_client):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(handler)
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == NETWORK_ERROR


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json=["not", "a", "dict"]),
        httpx.Response(200, json={"full_name": "octo/hello"}),  # required fields missing
        httpx.Response(200, json=repo_json(private="yes")),
        httpx.Response(200, json=repo_json(language=5)),
    ],
)
def test_malformed_repo_response(make_client, response):
    client, _ = make_client(lambda request: response)
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert info.value.code == UNEXPECTED_RESPONSE


def test_malformed_comments_response(make_client):
    client, _ = make_client(json_handler({"not": "a list"}))
    with pytest.raises(GitHubAPIError) as info:
        client.get_comments(ISSUE)
    assert info.value.code == UNEXPECTED_RESPONSE
    client, _ = make_client(json_handler(["a string, not a comment"]))
    with pytest.raises(GitHubAPIError):
        client.get_comments(ISSUE)


# -- the token never leaks ----------------------------------------------


def test_token_never_in_repr_or_errors(make_client):
    client, _ = make_client(json_handler({"message": "Bad credentials"}, 401), token=TOKEN)
    assert TOKEN not in repr(client)
    assert TOKEN not in str(client)
    assert "authenticated=True" in repr(client)

    cases = [
        (json_handler({}, 401), GitHubAPIError),
        (json_handler({}, 403), GitHubAPIError),
        (json_handler({}, 500), GitHubAPIError),
        (json_handler({}, 404), InputError),
    ]
    for handler, exc_type in cases:
        client, _ = make_client(handler, token=TOKEN)
        with pytest.raises(exc_type) as info:
            client.get_repo(REPO)
        assert TOKEN not in str(info.value)
        assert TOKEN not in repr(info.value)

    def boom(request):
        raise httpx.ConnectError(f"failed with {TOKEN}", request=request)

    client, _ = make_client(boom, token=TOKEN)
    with pytest.raises(GitHubAPIError) as info:
        client.get_repo(REPO)
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None


def test_client_does_not_read_environment(monkeypatch, make_client):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    client, rec = make_client(json_handler(repo_json()))
    client.get_repo(REPO)
    assert "authorization" not in rec.requests[0].headers


def test_owned_client_can_be_closed():
    with GitHubClient() as client:
        assert "authenticated=False" in repr(client)
