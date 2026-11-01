import httpx
import pytest

from bugbite.errors import ISSUE_NOT_FOUND, NOT_AN_ISSUE, NOT_PYTHON, REPO_NOT_FOUND, InputError
from bugbite.github import fetch_job_context, parse_job_input

from .conftest import BASE, comment_json, issue_json, repo_json

JOB = parse_job_input("https://github.com/octo/hello/issues/7", "https://github.com/octo/hello")


def router(repo=None, issue=None, comments=None):
    repo = repo_json() if repo is None else repo
    issue = issue_json() if issue is None else issue
    comments = [comment_json(1), comment_json(2)] if comments is None else comments

    def handler(request):
        path = request.url.path
        if path == "/repos/octo/hello":
            return httpx.Response(200, json=repo)
        if path == "/repos/octo/hello/issues/7":
            return httpx.Response(200, json=issue)
        if path == "/repos/octo/hello/issues/7/comments":
            return httpx.Response(200, json=comments)
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


def test_python_repo_returns_full_context(make_client):
    client, _ = make_client(router())
    ctx = fetch_job_context(client, JOB)
    assert ctx.repo.full_name == "octo/hello"
    assert ctx.issue.title == "Crash on empty input"
    assert ctx.issue.labels == ("bug", "good first issue")
    assert [c.body for c in ctx.comments] == ["comment 1", "comment 2"]
    assert ctx.comments_truncated is False


def test_call_order_is_repo_then_issue_then_comments(make_client):
    client, rec = make_client(router())
    fetch_job_context(client, JOB)
    assert rec.paths == [
        "/repos/octo/hello",
        "/repos/octo/hello/issues/7",
        "/repos/octo/hello/issues/7/comments",
    ]


@pytest.mark.parametrize("language", ["JavaScript", "Go", "python", "Jupyter Notebook"])
def test_non_python_repo_rejected_before_issue_call(make_client, language):
    client, rec = make_client(router(repo=repo_json(language=language)))
    with pytest.raises(InputError) as info:
        fetch_job_context(client, JOB)
    assert info.value.code == NOT_PYTHON
    assert language in info.value.message
    assert rec.paths == ["/repos/octo/hello"]


def test_unknown_language_rejected(make_client):
    client, rec = make_client(router(repo=repo_json(language=None)))
    with pytest.raises(InputError) as info:
        fetch_job_context(client, JOB)
    assert info.value.code == NOT_PYTHON
    assert "unknown" in info.value.message
    assert rec.paths == ["/repos/octo/hello"]


def test_redirect_to_different_repo_rejected(make_client):
    def handler(request):
        if request.url.path == "/repos/octo/hello":
            return httpx.Response(301, headers={"location": f"{BASE}/repositories/42"})
        return httpx.Response(200, json=repo_json(full_name="someone/else"))

    client, rec = make_client(handler)
    with pytest.raises(InputError) as info:
        fetch_job_context(client, JOB)
    assert info.value.code == REPO_NOT_FOUND
    assert "someone/else" in info.value.message
    assert "/repos/octo/hello/issues/7" not in rec.paths


def test_case_difference_in_full_name_is_fine(make_client):
    client, _ = make_client(router(repo=repo_json(full_name="Octo/Hello")))
    assert fetch_job_context(client, JOB).repo.full_name == "Octo/Hello"


def test_archived_repo_is_accepted_and_flagged(make_client):
    client, _ = make_client(router(repo=repo_json(archived=True)))
    assert fetch_job_context(client, JOB).repo.archived is True


def test_pull_request_number_rejected_and_comments_not_fetched(make_client):
    client, rec = make_client(router(issue=issue_json(pull_request={"url": "x"})))
    with pytest.raises(InputError) as info:
        fetch_job_context(client, JOB)
    assert info.value.code == NOT_AN_ISSUE
    assert "/repos/octo/hello/issues/7/comments" not in rec.paths


def test_missing_issue(make_client):
    def handler(request):
        if request.url.path == "/repos/octo/hello":
            return httpx.Response(200, json=repo_json())
        return httpx.Response(404, json={"message": "Not Found"})

    client, _ = make_client(handler)
    with pytest.raises(InputError) as info:
        fetch_job_context(client, JOB)
    assert info.value.code == ISSUE_NOT_FOUND


def test_comment_cap_is_passed_through(make_client):
    client, _ = make_client(router(comments=[comment_json(n) for n in range(10)]))
    ctx = fetch_job_context(client, JOB, max_comments=4)
    assert len(ctx.comments) == 4
    assert ctx.comments_truncated is True
