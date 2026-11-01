"""The pre-steps against a real sandbox. Only Docker is needed, except for the test that really runs pytest."""

import json

import pytest

from bugbite.agent import format_issue_task, run_prestep
from bugbite.agent import prestep as ps
from bugbite.config import SandboxConfig
from bugbite.github import CommentData, IssueData, JobContext, RepoInfo
from bugbite.sandbox import Sandbox, list_sandbox_containers, setup_workspace

pytestmark = pytest.mark.docker

_SEED = r"""
import os, subprocess
root = "/workspace/origin"
os.makedirs(root + "/pkg"); os.makedirs(root + "/tests")
open(root + "/pkg/__init__.py", "w").write("")
open(root + "/pkg/calc.py", "w").write("def add(a, b):\n    return a - b\n\n\ndef double(x):\n    return add(x, x)\n")
open(root + "/tests/test_calc.py", "w").write("from pkg.calc import add\n\n\nclass TestAdd:\n    def test_add(self):\n        assert add(1, 2) == 3\n")
os.symlink("/etc/passwd", root + "/pkg/passwd_link.py")
def git(*a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=root, check=True, capture_output=True)
git("init", "-b", "main"); git("add", "-A"); git("commit", "-m", "init")
"""

ISSUE = '''add(1, 2) returns -1.

Traceback (most recent call last):
  File "/home/me/proj/pkg/calc.py", line 6, in double
    return add(x, x)
  File "/home/me/proj/pkg/passwd_link.py", line 1, in <module>
    x
AssertionError: -1 != 3

The test tests/test_calc.py::TestAdd::test_add fails for me.
'''


def context():
    repo = RepoInfo("octo/hello", False, "Python", "main", False, False, "https://github.com/octo/hello")
    return JobContext(repo, IssueData(1, "Wrong sum", ISSUE, (), "open", "me", "https://github.com/octo/hello/issues/1", False), (), False)


def fixture(network):
    config = SandboxConfig(max_lifetime_s=900, setup_timeout_s=300, workspace_mb=1024, test_timeout_s=120)
    sb = Sandbox(config, network=True, job_id="tests-prestep").start()
    assert sb.run(["python", "-c", _SEED]).exit_code == 0
    if network:
        result = setup_workspace(sb, "file:///workspace/origin")
        assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    else:
        sb.disconnect_network()
        assert sb.run("git clone -q /workspace/origin /workspace/repo").exit_code == 0
    return sb


def test_snippets_and_files_from_a_real_clone_without_running_pytest():
    before = set(list_sandbox_containers())
    sb = fixture(network=False)
    try:
        result = run_prestep(sb, context(), runner=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip the real run")))
        text = result.text
        assert "pkg/calc.py line 6, in double:" in text and "|      6|     return add(x, x)" in text and "|      2|     return a - b" in text
        assert "| AssertionError: -1 != 3" in text
        assert "root:" not in text and "passwd_link" not in text.split("Tests named")[0].split("Files mentioned")[0].replace("/home/me/proj/", "")
        assert result.report.snippets == 1 and result.report.mapped_frames == 2  # the symlink frame maps by name but resolves outside the repo: not read
        assert "running the named tests failed (RuntimeError)" in result.report.notes
        assert format_issue_task(context(), checks=text).count(ps.HEADER) == 1
    finally:
        sb.close()
    assert set(list_sandbox_containers()) <= before


@pytest.mark.internet
def test_the_named_failing_test_is_really_run():
    before = set(list_sandbox_containers())
    sb = fixture(network=True)
    try:
        result = run_prestep(sb, context())
        assert "Tests named in the issue, run for you (tests/test_calc.py::TestAdd::test_add):" in result.text
        assert "| Ran 1 tests: 1 failed." in result.text and "| FAILED tests/test_calc.py::TestAdd::test_add" in result.text
        assert result.report.tests_run == 1 and result.report.test_status == "ok" and result.report.notes == ()
        assert result.report.tool_calls_done_in_code == 2
        json.dumps(result.report.to_dict())
    finally:
        sb.close()
    assert set(list_sandbox_containers()) <= before
