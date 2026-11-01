"""Combined, validated job input: an issue and the repo it belongs to."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bugbite.errors import REPO_MISMATCH, InputError
from bugbite.github.urls import IssueRef, RepoRef, parse_issue_url, parse_repo_url


@dataclass(frozen=True)
class JobInput:
    repo: RepoRef
    issue: IssueRef


def parse_job_input(issue_url: Any, repo_url: Any) -> JobInput:
    """Parse both URLs and require that the issue belongs to the given repo."""
    issue = parse_issue_url(issue_url)
    repo = parse_repo_url(repo_url)
    if issue.repo.full_name.lower() != repo.full_name.lower():
        raise InputError(
            REPO_MISMATCH,
            f"The issue is in {issue.repo.full_name} but the repository URL is {repo.full_name}. "
            "They must refer to the same repository.",
        )
    return JobInput(repo=repo, issue=issue)
