"""Helpers for GitHub tests. Everything runs on a mock transport: no network."""

import httpx
import pytest

from bugbite.github import GitHubClient

BASE = "https://api.github.com"


def repo_json(**overrides):
    data = {
        "full_name": "octo/hello",
        "private": False,
        "language": "Python",
        "default_branch": "main",
        "archived": False,
        "fork": False,
        "html_url": "https://github.com/octo/hello",
    }
    data.update(overrides)
    return data


def issue_json(**overrides):
    data = {
        "number": 7,
        "title": "Crash on empty input",
        "body": "Steps to reproduce...",
        "labels": [{"name": "bug"}, {"name": "good first issue"}],
        "state": "open",
        "user": {"login": "reporter"},
        "html_url": "https://github.com/octo/hello/issues/7",
    }
    data.update(overrides)
    return data


def comment_json(n=1, **overrides):
    data = {"user": {"login": f"user{n}"}, "body": f"comment {n}", "created_at": "2026-01-01T00:00:00Z"}
    data.update(overrides)
    return data


class Recorder:
    """Collects requests and answers them with `handler`."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def paths(self):
        return [r.url.path for r in self.requests]


@pytest.fixture
def make_client():
    clients = []

    def factory(handler, token=None, **kwargs):
        recorder = Recorder(handler)
        http = httpx.Client(transport=httpx.MockTransport(recorder))
        client = GitHubClient(token, client=http, **kwargs)
        clients.append(http)
        return client, recorder

    yield factory
    for http in clients:
        http.close()


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Offline by default: any real socket use fails the test (live tests opt out)."""
    import os
    import socket

    if os.environ.get("BUGBITE_LIVE_TESTS") == "1" and request.module.__name__.endswith("test_live"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("real network access attempted in an offline test")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
