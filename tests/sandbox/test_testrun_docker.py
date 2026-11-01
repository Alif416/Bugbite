"""Running tests inside the sandbox. Needs Docker and the internet (pytest is installed from PyPI).

One sandbox is set up once (network then cut); each test writes a fresh project into the repo.
"""

import json

import pytest

from bugbite.config import SandboxConfig
from bugbite.errors import NO_TESTS, InputError
from bugbite.github import RepoRef
from bugbite.sandbox import (
    Sandbox,
    collect_tests,
    ensure_has_tests,
    list_sandbox_containers,
    run_tests,
    setup_repo,
    setup_workspace,
)
from bugbite.sandbox import testrun as testrun_module

pytestmark = [pytest.mark.docker, pytest.mark.internet]

CONFIG = SandboxConfig(max_lifetime_s=1200, setup_timeout_s=300, workspace_mb=1024)

_WRITE = """
import json, os, shutil, subprocess, sys
files = json.loads(sys.argv[1]); root = sys.argv[2]
if os.path.isdir(root):
    for entry in os.listdir(root):
        path = os.path.join(root, entry)
        shutil.rmtree(path) if os.path.isdir(path) and not os.path.islink(path) else os.remove(path)
os.makedirs(root, exist_ok=True)
for name, text in files.items():
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
"""

_SEED = """
import json, os, subprocess, sys
root = "/workspace/origin"
os.makedirs(root)
open(os.path.join(root, "app.py"), "w").write("x = 1\\n")
def git(*a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=root, check=True, capture_output=True)
git("init", "-b", "main"); git("add", "-A"); git("commit", "-m", "init")
"""

MIXED = """
import pytest

def test_pass(): assert True
def test_fail(): assert 1 == 2

@pytest.mark.skip(reason="not now")
def test_skip(): pass

@pytest.mark.xfail(reason="known bug")
def test_xfail(): assert False

@pytest.fixture
def broken(): raise RuntimeError("setup boom")
def test_error(broken): pass

class TestGroup:
    def test_one(self): pass
"""


def write_project(sb, files):
    """Replace the contents of /workspace/repo with these files."""
    result = sb.run(["python", "-c", _WRITE, json.dumps(files), "/workspace/repo"])
    assert result.exit_code == 0, result.stderr


@pytest.fixture(scope="module")
def sb():
    sandbox = Sandbox(CONFIG, network=True, job_id="tests-testrun").start()
    try:
        assert sandbox.run(["python", "-c", _SEED]).exit_code == 0
        result = setup_workspace(sandbox, "file:///workspace/origin")
        assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
        assert sandbox.has_network is False
        yield sandbox
    finally:
        sandbox.close()


# -- outcomes ----------------------------------------------------------------


def test_mixed_outcomes_with_exact_ids_and_counts(sb):
    write_project(sb, {"test_mixed.py": MIXED})
    run = run_tests(sb)
    assert run.status == "ok" and run.reason == ""
    assert run.exit_code == 1
    assert {i: c.outcome for i, c in run.tests.items()} == {
        "test_mixed.py::test_pass": "passed",
        "test_mixed.py::test_fail": "failed",
        "test_mixed.py::test_skip": "skipped",
        "test_mixed.py::test_xfail": "xfailed",
        "test_mixed.py::test_error": "error",
        "test_mixed.py::TestGroup::test_one": "passed",
    }
    assert run.counts == {"passed": 2, "failed": 1, "error": 1, "skipped": 1, "xfailed": 1, "xpassed": 0}
    assert run.ids_with("failed") == ["test_mixed.py::test_fail"]
    assert run.collected == 6
    assert "assert 1 == 2" in run.tests["test_mixed.py::test_fail"].message
    assert "1 failed" in run.output_tail and run.output_truncated is False
    assert run.duration_s > 0 and run.report_missing is False and run.malformed_lines == 0


def test_all_passing(sb):
    write_project(sb, {"test_ok.py": "def test_a(): pass\ndef test_b(): pass\n"})
    run = run_tests(sb)
    assert (run.status, run.exit_code, run.counts["passed"]) == ("ok", 0, 2)


def test_select_one_file_and_one_node_id(sb):
    write_project(
        sb,
        {"test_a.py": "def test_x(): pass\ndef test_y(): pass\n", "test_b.py": "def test_z(): pass\n"},
    )
    assert sorted(run_tests(sb, ["test_a.py"]).tests) == ["test_a.py::test_x", "test_a.py::test_y"]
    assert sorted(run_tests(sb, ["test_a.py::test_y"]).tests) == ["test_a.py::test_y"]
    both = run_tests(sb, ["test_a.py::test_x", "test_b.py"])
    assert sorted(both.tests) == ["test_a.py::test_x", "test_b.py::test_z"]


def test_a_target_that_looks_like_an_option_never_reaches_pytest(sb):
    write_project(sb, {"test_a.py": "def test_x(): pass\n"})
    with pytest.raises(ValueError):
        run_tests(sb, ["--pdb"])


def test_nonexistent_target_is_reported_not_ok(sb):
    write_project(sb, {"test_a.py": "def test_x(): pass\n"})
    run = run_tests(sb, ["nope.py"])
    assert run.status != "ok"
    assert run.tests == {}


# -- repo configuration --------------------------------------------------------


def test_repo_addopts_is_respected(sb):
    write_project(
        sb,
        {
            "pytest.ini": "[pytest]\naddopts = -k keepme\n",
            "test_a.py": "def test_keepme(): pass\ndef test_other(): pass\n",
        },
    )
    run = run_tests(sb)
    assert run.status == "ok"
    assert list(run.tests) == ["test_a.py::test_keepme"]


def test_unknown_option_in_addopts_is_a_collection_error(sb):
    write_project(
        sb,
        {"pytest.ini": "[pytest]\naddopts = --cov=app\n", "test_a.py": "def test_x(): pass\n"},
    )
    run = run_tests(sb)
    assert run.status == "collection_error"
    assert "usage error" in run.reason and "--cov" in run.reason
    assert run.tests == {}


def test_import_error_is_a_collection_error_with_the_module_named(sb):
    write_project(
        sb,
        {"test_bad.py": "import module_that_does_not_exist\ndef test_a(): pass\n", "test_ok.py": "def test_b(): pass\n"},
    )
    run = run_tests(sb)
    assert run.status == "collection_error"
    assert [e.id for e in run.collection_errors] == ["test_bad.py"]
    assert "module_that_does_not_exist" in run.reason


# -- no tests and collection -----------------------------------------------------


def test_no_tests_status_and_rejection(sb):
    write_project(sb, {"app.py": "x = 1\n"})
    run = run_tests(sb)
    assert run.status == "no_tests" and run.exit_code == 5
    with pytest.raises(InputError) as info:
        ensure_has_tests(sb)
    assert info.value.code == NO_TESTS


def test_collection_errors_are_not_a_rejection(sb):
    write_project(sb, {"test_bad.py": "import module_that_does_not_exist\n"})
    run = ensure_has_tests(sb)  # does not raise
    assert run.status == "collection_error"


def test_collect_lists_ids_without_running_anything(sb):
    write_project(sb, {"test_mixed.py": MIXED})
    run = collect_tests(sb)
    assert run.status == "ok"
    assert run.collected == 6 and len(run.collected_ids) == 6
    assert "test_mixed.py::TestGroup::test_one" in run.collected_ids
    assert run.tests == {}
    assert ensure_has_tests(sb).collected == 6


# -- timeouts, isolation, integrity ------------------------------------------------


def test_timeout_keeps_partial_results_and_sandbox_survives(sb):
    write_project(
        sb,
        {"test_slow.py": "import time\ndef test_quick(): pass\ndef test_hang(): time.sleep(120)\n"},
    )
    run = run_tests(sb, timeout=6)
    assert run.status == "timeout"
    assert run.reason.startswith("The run hit the time limit")
    assert run.tests["test_slow.py::test_quick"].outcome == "passed"
    assert "test_slow.py::test_hang" not in run.tests
    assert sb.run("echo alive").stdout == "alive\n"


def test_runs_never_mix_results(sb):
    write_project(sb, {"test_first.py": "def test_one(): pass\n"})
    assert list(run_tests(sb).tests) == ["test_first.py::test_one"]
    write_project(sb, {"test_second.py": "def test_two(): assert False\n"})
    second = run_tests(sb)
    assert list(second.tests) == ["test_second.py::test_two"]
    assert second.counts["passed"] == 0


def test_plugin_and_report_stay_outside_the_repo(sb):
    write_project(sb, {"test_a.py": "def test_x(): pass\n"})
    run_tests(sb)
    assert sb.run("ls -A /workspace/repo").stdout.split() == ["test_a.py"]  # no cache, bytecode, report, or plugin
    assert sb.run("ls /workspace/.bugbite").stdout.split() == ["bugbite_report.py", "report.jsonl"]


def test_corrupted_plugin_is_crashed_never_a_wrong_ok(sb, tmp_path, monkeypatch):
    broken = tmp_path / "bugbite_report.py"
    broken.write_text("raise RuntimeError('plugin is broken')\n")
    monkeypatch.setattr(testrun_module, "PLUGIN_SOURCE", broken)
    write_project(sb, {"test_a.py": "def test_x(): pass\n"})
    run = run_tests(sb)
    assert run.status == "crashed"
    assert run.tests == {} and run.status != "ok"


def test_a_test_cannot_use_the_network(sb):
    probe = (
        "import socket\n"
        "def test_net():\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
    )
    write_project(sb, {"test_net.py": probe})
    run = run_tests(sb)
    assert run.tests["test_net.py::test_net"].outcome == "failed"


def test_output_tail_is_bounded(sb):
    write_project(sb, {"test_noisy.py": "def test_noisy():\n    print('x' * 100000)\n    assert False\n"})
    run = run_tests(sb)
    assert run.status == "ok"
    assert len(run.output_tail) <= 20_000


# -- other pytest versions and a real repo ------------------------------------------


def test_old_pytest_version_works_with_the_plugin():
    with Sandbox(CONFIG, network=True, job_id="tests-testrun-old") as old:
        old.run(["python", "-c", _SEED])
        old.run(
            ["python", "-c", "open('/workspace/origin/requirements.txt','w').write('pytest==7.4.4\\n')"]
        )
        old.run(["git", "-C", "/workspace/origin", "add", "-A"])
        old.run(["git", "-C", "/workspace/origin", "-c", "user.name=t", "-c", "user.email=t@x", "commit", "-m", "req"])
        result = setup_workspace(old, "file:///workspace/origin")
        assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
        write_project(old, {"test_mixed.py": MIXED})
        assert "7.4.4" in old.run([testrun_module.PYTHON, "-m", "pytest", "--version"], workdir="/workspace/repo").stderr + old.run(
            [testrun_module.PYTHON, "-m", "pytest", "--version"], workdir="/workspace/repo"
        ).stdout
        run = run_tests(old)
        assert run.status == "ok"
        assert run.counts == {"passed": 2, "failed": 1, "error": 1, "skipped": 1, "xfailed": 1, "xpassed": 0}


def test_real_repo_end_to_end():
    pinned = "672971d66a2ef9f85151e53283113f33d642dabd"  # pallets/itsdangerous
    with Sandbox(CONFIG, network=True, job_id="tests-testrun-real") as real:
        setup = setup_repo(real, RepoRef("pallets", "itsdangerous"), ref=pinned)
        assert setup.ok, [(s.name, s.output_tail[-300:]) for s in setup.steps if not s.ok]
        assert ensure_has_tests(real).collected > 100
        run = run_tests(real)
        assert run.status == "ok", (run.reason, run.output_tail[-500:])
        assert run.exit_code == 0
        assert run.counts["failed"] == 0 and run.counts["error"] == 0
        assert run.counts["passed"] > 100
        assert run.collected == len(run.tests)


def test_no_containers_left_behind_by_the_per_test_sandboxes(sb):
    assert list_sandbox_containers() == [sb.container_name]
