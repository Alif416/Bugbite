"""Sandbox behaviour that needs no Docker daemon."""

from bugbite.errors import DOCKER_UNAVAILABLE, SANDBOX_CLOSED, SandboxError
from bugbite.sandbox import Sandbox

import pytest


def test_unreachable_docker_gives_clear_error(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
    with pytest.raises(SandboxError) as info:
        Sandbox().start()
    assert info.value.code == DOCKER_UNAVAILABLE
    assert "Start Docker" in info.value.message


def test_with_block_does_not_run_body_when_docker_is_down(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:1")
    ran = []
    with pytest.raises(SandboxError):
        with Sandbox():
            ran.append(True)
    assert ran == []


def test_run_before_start_raises():
    with pytest.raises(SandboxError) as info:
        Sandbox().run("echo hi")
    assert info.value.code == SANDBOX_CLOSED


def test_close_without_start_is_safe():
    Sandbox().close()
