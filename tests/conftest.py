"""Shared pytest setup.

Tests marked `docker` need a reachable Docker daemon; tests marked `internet`
need pypi.org and github.com. When unavailable they are skipped with a visible
reason instead of failing.
"""

import pytest


def _docker_unavailable_reason() -> str | None:
    try:
        import docker

        client = docker.from_env(timeout=5)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:
        return f"Docker daemon not reachable ({type(exc).__name__}); start Docker to run these tests"
    return None


def _internet_unavailable_reason() -> str | None:
    import socket

    for host in ("pypi.org", "github.com"):
        try:
            socket.create_connection((host, 443), timeout=4).close()
        except OSError:
            return f"No internet access to {host}; connect to the internet to run these tests"
    return None


def pytest_collection_modifyitems(config, items):
    for marker, check in (("docker", _docker_unavailable_reason), ("internet", _internet_unavailable_reason)):
        marked = [item for item in items if item.get_closest_marker(marker)]
        if not marked:
            continue
        reason = check()
        if reason is None:
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in marked:
            item.add_marker(skip)
