import pytest

from bugbite.errors import (
    EMPTY_INPUT,
    INVALID_URL,
    NOT_A_REPO_URL,
    NOT_AN_ISSUE_URL,
    NOT_GITHUB,
    InputError,
)
from bugbite.github import IssueRef, RepoRef, parse_issue_url, parse_repo_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/hello",
        "https://github.com/octo/hello/",
        "https://github.com/octo/hello.git",
        "http://github.com/octo/hello",
        "https://www.github.com/octo/hello",
        "https://GitHub.com/octo/hello",
        "  https://github.com/octo/hello  ",
        "https://github.com/octo/hello?tab=readme#top",
    ],
)
def test_repo_url_accepted(url):
    assert parse_repo_url(url) == RepoRef("octo", "hello")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/hello/issues/12",
        "https://github.com/octo/hello/issues/12/",
        "https://github.com/octo/hello/issues/12?x=1",
        "https://github.com/octo/hello/issues/12#issuecomment-99",
        "https://www.github.com/octo/hello/issues/12",
    ],
)
def test_issue_url_accepted(url):
    ref = parse_issue_url(url)
    assert ref == IssueRef(RepoRef("octo", "hello"), 12)


def test_names_keep_case():
    assert parse_repo_url("https://github.com/OcTo/Hello.Py") == RepoRef("OcTo", "Hello.Py")


def test_dotted_repo_names_allowed():
    assert parse_repo_url("https://github.com/octo/.github").name == ".github"


def code_of(fn, value):
    with pytest.raises(InputError) as info:
        fn(value)
    return info.value.code


@pytest.mark.parametrize("value", ["", "   ", None, "\n"])
def test_empty_input(value):
    assert code_of(parse_repo_url, value) == EMPTY_INPUT
    assert code_of(parse_issue_url, value) == EMPTY_INPUT


@pytest.mark.parametrize("value", [123, ["https://github.com/a/b"], b"https://github.com/a/b"])
def test_non_string_input(value):
    assert code_of(parse_repo_url, value) == EMPTY_INPUT


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/octo/hello",
        "https://bitbucket.org/octo/hello",
        "https://github.com.evil.io/octo/hello",
        "https://evilgithub.com/octo/hello",
        "https://notgithub.com/octo/hello",
        "https://api.github.com/octo/hello",
    ],
)
def test_non_github_hosts_rejected(url):
    assert code_of(parse_repo_url, url) == NOT_GITHUB
    assert code_of(parse_issue_url, url + "/issues/1") == NOT_GITHUB


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com@evil.io/octo/hello",
        "https://user:pw@github.com/octo/hello",
        "https://github.com:8080/octo/hello",
        "https://github.com:evil/octo/hello",
    ],
)
def test_credentials_ports_and_tricks_rejected(url):
    with pytest.raises(InputError):
        parse_repo_url(url)


@pytest.mark.parametrize(
    "url",
    ["octo/hello", "github.com/octo/hello", "ftp://github.com/octo/hello", "file:///etc/passwd", "git@github.com:octo/hello.git"],
)
def test_not_full_http_url(url):
    assert code_of(parse_repo_url, url) == INVALID_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo",
        "https://github.com/",
        "https://github.com",
        "https://github.com/octo/hello/issues/1",
        "https://github.com/octo/hello/tree/main",
    ],
)
def test_not_a_repo_url(url):
    assert code_of(parse_repo_url, url) == NOT_A_REPO_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/hello",
        "https://github.com/octo/hello/issues",
        "https://github.com/octo/hello/pull/5",
        "https://github.com/octo/hello/pulls/5",
        "https://github.com/octo/hello/discussions/5",
        "https://github.com/octo/hello/issues/5/extra",
    ],
)
def test_not_an_issue_url(url):
    assert code_of(parse_issue_url, url) == NOT_AN_ISSUE_URL


def test_pull_request_message_says_so():
    with pytest.raises(InputError, match="pull"):
        parse_issue_url("https://github.com/octo/hello/pull/5")


@pytest.mark.parametrize(
    "number",
    ["0", "-1", "abc", "1.5", "007", "99999999999999999999", "2147483648", "1e3", "%31", "१२"],
)
def test_bad_issue_numbers(number):
    assert code_of(parse_issue_url, f"https://github.com/octo/hello/issues/{number}") == INVALID_URL


def test_large_valid_issue_number():
    assert parse_issue_url("https://github.com/octo/hello/issues/2147483647").number == 2147483647


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/-octo/hello",
        "https://github.com/octo-/hello",
        "https://github.com/oc_to/hello",
        "https://github.com/" + "a" * 40 + "/hello",
        "https://github.com/octo/he llo",
        "https://github.com/octo/..",
        "https://github.com/octo/.",
        "https://github.com/../hello",
        "https://github.com/octo/hel$lo",
        "https://github.com/octo/hel;rm",
        "https://github.com/octo/hel%20lo",
        "https://github.com/octo/hello\\..\\x",
        "https://github.com//hello",
        "https://github.com/octo//hello",
        "https://github.com/octo/" + "r" * 101,
        "https://github.com/octo/hello\x00",
    ],
)
def test_illegal_names_rejected(url):
    with pytest.raises(InputError):
        parse_repo_url(url)


def test_message_quotes_input_but_is_bounded():
    with pytest.raises(InputError) as info:
        parse_repo_url("https://gitlab.com/" + "x" * 1000)
    assert len(info.value.message) < 500
    assert "gitlab.com" in info.value.message
