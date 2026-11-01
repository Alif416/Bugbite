"""Opt-in smoke test against the real GitHub API.

Skipped unless BUGBITE_LIVE_TESTS=1. Uses GITHUB_TOKEN if set, otherwise
makes anonymous requests (60 per hour).
"""

import os

import pytest

from bugbite.github import GitHubClient, fetch_job_context, parse_job_input

pytestmark = pytest.mark.skipif(
    os.environ.get("BUGBITE_LIVE_TESTS") != "1",
    reason="live GitHub tests are opt-in: set BUGBITE_LIVE_TESTS=1",
)


def test_fetch_real_issue():
    job = parse_job_input("https://github.com/psf/requests/issues/1", "https://github.com/psf/requests")
    with GitHubClient(os.environ.get("GITHUB_TOKEN")) as client:
        ctx = fetch_job_context(client, job, max_comments=5)
    assert ctx.repo.language == "Python"
    assert ctx.issue.number == 1
    assert ctx.issue.title
