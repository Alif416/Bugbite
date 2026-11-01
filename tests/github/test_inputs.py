import pytest

from bugbite.errors import (
    EMPTY_INPUT,
    NOT_A_REPO_URL,
    NOT_AN_ISSUE_URL,
    REPO_MISMATCH,
    InputError,
)
from bugbite.github import IssueRef, JobInput, RepoRef, parse_job_input

ISSUE = "https://github.com/octo/hello/issues/7"
REPO = "https://github.com/octo/hello"


def test_matching_pair():
    job = parse_job_input(ISSUE, REPO)
    assert job == JobInput(RepoRef("octo", "hello"), IssueRef(RepoRef("octo", "hello"), 7))


def test_repo_comparison_is_case_insensitive():
    job = parse_job_input(ISSUE, "https://github.com/OCTO/Hello.git")
    assert job.issue.number == 7
    assert job.repo.full_name == "OCTO/Hello"


def test_mismatch_names_both_repos():
    with pytest.raises(InputError) as info:
        parse_job_input(ISSUE, "https://github.com/other/thing")
    assert info.value.code == REPO_MISMATCH
    assert "octo/hello" in info.value.message
    assert "other/thing" in info.value.message


def test_invalid_issue_url():
    with pytest.raises(InputError) as info:
        parse_job_input(REPO, REPO)
    assert info.value.code == NOT_AN_ISSUE_URL


def test_invalid_repo_url():
    with pytest.raises(InputError) as info:
        parse_job_input(ISSUE, ISSUE)
    assert info.value.code == NOT_A_REPO_URL


def test_empty_input():
    with pytest.raises(InputError) as info:
        parse_job_input("", REPO)
    assert info.value.code == EMPTY_INPUT
    with pytest.raises(InputError) as info:
        parse_job_input(ISSUE, None)
    assert info.value.code == EMPTY_INPUT


def test_parsing_makes_no_network_call(monkeypatch):
    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    assert parse_job_input(ISSUE, REPO).issue.number == 7
