"""The edit and run tools against a real sandbox.

Most tests need only Docker. The test that runs pytest through `run_tests` also needs the internet,
because the repo's virtualenv is built with pytest from PyPI.
"""

import json

import pytest

from bugbite.agent.tools import build_agent_tools
from bugbite.config import SandboxConfig
from bugbite.sandbox import Sandbox, list_sandbox_containers, setup_workspace

pytestmark = pytest.mark.docker

CONFIG = SandboxConfig(max_lifetime_s=900, setup_timeout_s=300, workspace_mb=1024, command_timeout_s=20)

_SEED = """
import os, subprocess
root = "/workspace/origin"
os.makedirs(root + "/tests")
open(root + "/app.py", "w").write("def add(a, b):\\n    return a - b\\n")
open(root + "/tests/test_app.py", "w").write("from app import add\\n\\ndef test_add():\\n    assert add(1, 2) == 3\\n")
open(root + "/run.sh", "w").write("#!/bin/sh\\necho hi\\n")
os.chmod(root + "/run.sh", 0o755)
os.symlink("/etc/passwd", root + "/passwd_link")
def git(*a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=root, check=True, capture_output=True)
git("init", "-b", "main"); git("add", "-A"); git("commit", "-m", "init")
"""


@pytest.fixture(scope="module")
def sandbox():
    before = set(list_sandbox_containers())
    sb = Sandbox(CONFIG, network=True, job_id="tests-edit").start()
    try:
        assert sb.run(["python", "-c", _SEED]).exit_code == 0
        sb.disconnect_network()  # these tests do not need pip; they only need the network to be off
        sb.run(["sh", "-c", "git clone -q /workspace/origin /workspace/repo"])
        yield sb
    finally:
        sb.close()
    assert set(list_sandbox_containers()) <= before


@pytest.fixture(scope="module")
def tools(sandbox):
    return build_agent_tools(sandbox)


def test_edit_a_real_file_and_the_change_is_what_git_sees(sandbox, tools):
    out = tools.execute("edit_file", {"path": "app.py", "old_text": "return a - b", "new_text": "return a + b"})
    assert not out.is_error, out.text
    diff = sandbox.run("git diff --stat && git diff", workdir="/workspace/repo").stdout
    assert "1 file changed, 1 insertion(+), 1 deletion(-)" in diff and "+    return a + b" in diff
    sandbox.run("git checkout -- .", workdir="/workspace/repo")


def test_an_executable_keeps_its_mode_and_the_diff_has_no_mode_change(sandbox, tools):
    assert not tools.execute("edit_file", {"path": "run.sh", "old_text": "hi", "new_text": "there"}).is_error
    assert sandbox.run("stat -c %a run.sh", workdir="/workspace/repo").stdout.strip() == "755"
    assert "mode" not in sandbox.run("git diff", workdir="/workspace/repo").stdout
    sandbox.run("git checkout -- .", workdir="/workspace/repo")


def test_create_files_and_folders_owned_by_the_sandbox_user(sandbox, tools):
    assert not tools.execute("edit_file", {"path": "pkg/sub/new.py", "new_text": "x = 1\n"}).is_error
    assert sandbox.run("stat -c %u pkg/sub/new.py", workdir="/workspace/repo").stdout.strip() == "1000"
    assert sandbox.run("git status --porcelain", workdir="/workspace/repo").stdout.strip() == "?? pkg/"
    sandbox.run("rm -rf pkg", workdir="/workspace/repo")


def test_protected_and_escaping_edits_are_refused(sandbox, tools):
    before = sandbox.run("git status --porcelain", workdir="/workspace/repo").stdout
    for args in ({"path": "tests/test_app.py", "old_text": "3", "new_text": "2"},
                 {"path": "pytest.ini", "new_text": "[pytest]\n"},
                 {"path": "passwd_link", "old_text": "root", "new_text": "evil"},
                 {"path": "../escape.txt", "new_text": "x"}):
        assert tools.execute("edit_file", args).is_error, args
    assert sandbox.run("git status --porcelain", workdir="/workspace/repo").stdout == before
    assert sandbox.run("grep -c evil /etc/passwd").stdout.strip() == "0"


def test_run_command_has_no_network_and_the_venv_first_on_path(sandbox, tools):
    out = tools.execute("run_command", {"command": "echo $PATH; python -c 'import socket; socket.create_connection((\"1.1.1.1\", 80), 3)'"}).text
    assert out.startswith("exit code 1") and "/workspace/.venv/bin:/usr/local/bin" in out
    assert "Network is unreachable" in out or "unreachable" in out.lower() or "Errno" in out


def test_run_command_runs_in_the_repo_and_sees_edits(sandbox, tools):
    assert tools.execute("run_command", {"command": "pwd && ls"}).text.startswith("exit code 0\n/workspace/repo\napp.py")


def test_a_sleeping_command_is_stopped_at_the_timeout(sandbox, tools):
    out = tools.execute("run_command", {"command": "sleep 60", "timeout_s": 2})
    assert out.text.startswith("timed out after 2s") and not out.is_error
    assert tools.execute("run_command", {"command": "echo still alive"}).text == "exit code 0\nstill alive"


def test_run_command_refuses_if_the_network_is_back(sandbox, tools):
    client = sandbox._client
    client.api.connect_container_to_network(sandbox._container.id, "bridge")
    try:
        out = tools.execute("run_command", {"command": "echo hi"})
        assert out.is_error and "network" in out.text
    finally:
        sandbox.disconnect_network()
    assert not tools.execute("run_command", {"command": "echo hi"}).is_error


@pytest.mark.internet
def test_edit_then_run_tests_turns_a_failure_into_a_pass():
    with Sandbox(SandboxConfig(max_lifetime_s=900, setup_timeout_s=300, workspace_mb=1024), network=True, job_id="tests-edit-e2e") as sb:
        assert sb.run(["python", "-c", _SEED]).exit_code == 0
        result = setup_workspace(sb, "file:///workspace/origin")
        assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
        tools = build_agent_tools(sb)
        first = tools.execute("run_tests", {})
        assert not first.is_error and "Ran 1 tests: 1 failed." in first.text and "FAILED tests/test_app.py::test_add" in first.text
        assert "assert" in first.text
        assert not tools.execute("edit_file", {"path": "app.py", "old_text": "a - b", "new_text": "a + b"}).is_error
        second = tools.execute("run_tests", {"targets": ["tests/test_app.py::test_add"]})
        assert second.text == "Ran 1 tests: 1 passed."
        assert tools.execute("run_tests", {"keyword": "no_such_test"}).text.startswith("Test run status: no_tests")
        assert "Invalid" in tools.execute("run_tests", {"targets": ["--collect-only"]}).text
