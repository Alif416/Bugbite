"""Shared pytest setup.

Tests marked `docker` need a reachable Docker daemon. When there is none they
are skipped with a visible reason instead of failing.
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


def pytest_collection_modifyitems(config, items):
    docker_items = [item for item in items if item.get_closest_marker("docker")]
    if not docker_items:
        return
    reason = _docker_unavailable_reason()
    if reason is None:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in docker_items:
        item.add_marker(skip)
