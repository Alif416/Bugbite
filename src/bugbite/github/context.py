"""Fetch everything a job starts from, rejecting repos we cannot work on."""

from __future__ import annotations

from bugbite.errors import NOT_PYTHON, REPO_NOT_FOUND, InputError
from bugbite.github.client import GitHubClient
from bugbite.github.inputs import JobInput
from bugbite.github.models import JobContext


def fetch_job_context(client: GitHubClient, job: JobInput, max_comments: int = 50) -> JobContext:
    """Check the repo, then fetch the issue and comments.

    Cheap rejections come first: a non-Python repo is refused before any
    issue call is made.
    """
    repo = client.get_repo(job.repo)

    if repo.full_name.lower() != job.repo.full_name.lower():
        raise InputError(
            REPO_NOT_FOUND,
            f"{job.repo.full_name} now redirects to {repo.full_name}. "
            "Resubmit using the new repository URL.",
        )
    if repo.language != "Python":
        detected = repo.language or "unknown"
        raise InputError(
            NOT_PYTHON,
            f"{repo.full_name} is not a Python repository (GitHub reports its main language as {detected}). "
            "Only Python repositories are supported.",
        )

    issue = client.get_issue(job.issue)
    comments, truncated = client.get_comments(job.issue, max_comments)
    return JobContext(repo=repo, issue=issue, comments=comments, comments_truncated=truncated)
