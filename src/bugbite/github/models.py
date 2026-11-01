"""Data returned by the GitHub client.

Issue and comment text is untrusted input (it may contain prompt-injection
attempts). It is stored as plain data and must stay separate from
instructions when later phases build prompts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    private: bool
    language: str | None
    default_branch: str
    archived: bool
    fork: bool
    html_url: str


@dataclass(frozen=True)
class IssueData:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    state: str
    author: str
    html_url: str
    truncated: bool


@dataclass(frozen=True)
class CommentData:
    author: str
    body: str
    created_at: str
    truncated: bool


@dataclass(frozen=True)
class JobContext:
    repo: RepoInfo
    issue: IssueData
    comments: tuple[CommentData, ...]
    comments_truncated: bool
