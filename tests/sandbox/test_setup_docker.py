"""Workspace, network cutting, and repo setup against real Docker.

Repos are built inside the container (file:// URLs), so GitHub is not needed.
Tests marked `internet` also reach PyPI (and one reaches GitHub).
"""

import json

import docker
import pytest

from bugbite.config import SandboxConfig
from bugbite.github import RepoRef
from bugbite.sandbox import Sandbox, list_sandbox_containers, setup_repo, setup_workspace
from bugbite.sandbox.image import SANDBOX_IMAGE
from bugbite.sandbox.setup import (
    CLONE_FAILED,
    INSTALL_FAILED,
    SETUP_TIMEOUT,
    WORKSPACE_FULL_REASON,
)

pytestmark = pytest.mark.docker

CONFIG = SandboxConfig(max_lifetime_s=900, setup_timeout_s=300, workspace_mb=512)

_MAKE_REPO = """
import json, os, subprocess, sys
files = json.loads(sys.argv[1]); root = sys.argv[2]
os.makedirs(root, exist_ok=True)
for name, text in files.items():
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
def git(*args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          cwd=root, check=True, capture_output=True, text=True).stdout.strip()
if not os.path.isdir(os.path.join(root, ".git")):
    git("init", "-b", "main")
git("add", "-A")
git("commit", "-m", sys.argv[3])
print(git("rev-parse", "HEAD"))
"""


def commit_files(sb, files, path="/workspace/origin", message="commit"):
    """Create or extend a git repo inside the container; return the new commit hash."""
    result = sb.run(["python", "-c", _MAKE_REPO, json.dumps(files), path, message])
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def url(path="/workspace/origin"):
    return f"file://{path}"


@pytest.fixture
def make_sandbox():
    made = []

    def factory(config=CONFIG, **kwargs):
        sb = Sandbox(config, job_id="tests-setup", **kwargs)
        made.append(sb)
        return sb.start()

    yield factory
    for sb in made:
        sb.close()


@pytest.fixture(scope="module")
def docker_client():
    client = docker.from_env()
    yield client
    client.close()


# -- image and workspace ---------------------------------------------------


def test_default_image_is_built_once_and_has_git(docker_client, make_sandbox):
    sb = make_sandbox(SandboxConfig())
    assert sb.config.image == SANDBOX_IMAGE
    first_id = docker_client.images.get(SANDBOX_IMAGE).id
    assert sb.run("git --version").exit_code == 0
    sb2 = make_sandbox(SandboxConfig())
    assert docker_client.images.get(SANDBOX_IMAGE).id == first_id
    assert sb2.run("git --version").exit_code == 0


def test_workspace_is_a_disk_volume_owned_by_the_sandbox_user(make_sandbox):
    sb = make_sandbox()
    mounts = sb.run("grep ' /workspace ' /proc/mounts").stdout
    assert mounts and "tmpfs" not in mounts.split()[2]
    assert sb.run("stat -c %u /workspace").stdout.strip() == "1000"
    assert sb.run("echo ok > /workspace/probe && cat /workspace/probe").stdout == "ok\n"


def test_workspace_volume_is_removed_with_the_container(docker_client):
    sb = Sandbox(CONFIG, job_id="tests-setup").start()
    volume = sb.inspect()["Mounts"][0]["Name"]
    assert volume in {v.name for v in docker_client.volumes.list()}
    sb.close()
    assert volume not in {v.name for v in docker_client.volumes.list()}


# -- network ---------------------------------------------------------------


def test_network_can_be_cut_and_cutting_is_idempotent(make_sandbox):
    sb = make_sandbox(network=True)
    assert sb.has_network is True
    sb.disconnect_network()
    sb.disconnect_network()
    assert sb.has_network is False
    interfaces = sb.run("sed -n '3,$p' /proc/net/dev | cut -d: -f1").stdout.split()
    assert "eth0" not in interfaces
    assert sb.run("cat /proc/net/route").stdout.splitlines()[1:] == []
    probe = "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"
    assert sb.run(["python", "-c", probe]).exit_code != 0


def test_disconnecting_a_sandbox_that_never_had_network_is_a_no_op(make_sandbox):
    sb = make_sandbox(network=False)
    assert sb.has_network is False
    sb.disconnect_network()
    assert sb.has_network is False


# -- clone (no internet needed) --------------------------------------------


def test_clone_checkout_and_git_diff_then_network_cut(make_sandbox):
    sb = make_sandbox(network=True)
    head = commit_files(sb, {"hello.txt": "one\n"})
    result = setup_workspace(sb, url())
    assert result.head_commit == head
    # No packaging file: the venv step succeeds offline; the pytest step needs PyPI, so
    # accept either outcome here, but the clone must have worked and the network must be cut.
    assert [s.name for s in result.steps[:2]] == ["git-clone", "git-rev-parse"]
    assert result.steps[0].ok and result.steps[1].ok
    assert sb.has_network is False
    assert sb.run("cat /workspace/repo/hello.txt").stdout == "one\n"
    sb.run("echo two >> /workspace/repo/hello.txt")
    diff = sb.run(["git", "-C", "/workspace/repo", "diff", "--stat"])
    assert "hello.txt" in diff.stdout


def test_clone_is_shallow(make_sandbox):
    sb = make_sandbox()
    commit_files(sb, {"a.txt": "1"}, message="first")
    commit_files(sb, {"a.txt": "2"}, message="second")
    setup_workspace(sb, url())
    count = sb.run(["git", "-C", "/workspace/repo", "rev-list", "--count", "HEAD"]).stdout.strip()
    assert count == "1"


def test_pinned_ref_checks_out_exactly_that_commit(make_sandbox):
    sb = make_sandbox()
    first = commit_files(sb, {"a.txt": "old\n"}, message="first")
    second = commit_files(sb, {"a.txt": "new\n"}, message="second")
    assert first != second
    # file:// remotes only serve reachable refs by name unless uploadpack allows SHAs
    sb.run(["git", "-C", "/workspace/origin", "config", "uploadpack.allowAnySHA1InWant", "true"])
    result = setup_workspace(sb, url(), ref=first)
    assert result.head_commit == first
    assert sb.run("cat /workspace/repo/a.txt").stdout == "old\n"


def test_pinned_branch_ref(make_sandbox):
    sb = make_sandbox()
    commit_files(sb, {"a.txt": "x"})
    result = setup_workspace(sb, url(), ref="main")
    assert result.head_commit and result.steps[0].name == "git-init"
    assert any(s.name == "git-checkout" and s.ok for s in result.steps)


def test_bad_ref_is_rejected_before_anything_runs(make_sandbox):
    sb = make_sandbox(network=True)
    with pytest.raises(ValueError):
        setup_workspace(sb, url(), ref="--upload-pack=touch /workspace/pwned")
    assert sb.run("test -e /workspace/pwned").exit_code != 0
    assert sb.has_network is False  # the network is cut even when setup raises


def test_bad_clone_url_is_rejected(make_sandbox):
    sb = make_sandbox(network=True)
    with pytest.raises(ValueError):
        setup_workspace(sb, "--upload-pack=evil")
    assert sb.has_network is False


def test_missing_repo_is_clone_failed_and_network_is_cut(make_sandbox):
    sb = make_sandbox(network=True)
    result = setup_workspace(sb, url("/workspace/does-not-exist"))
    assert result.ok is False
    assert result.failure_reason == CLONE_FAILED
    assert result.head_commit is None
    assert result.steps[-1].ok is False and result.steps[-1].output_tail
    assert sb.has_network is False


def test_workspace_over_cap_is_reported_and_network_cut(make_sandbox):
    sb = make_sandbox(SandboxConfig(max_lifetime_s=900, setup_timeout_s=300, workspace_mb=1), network=True)
    sb.run("mkdir -p /workspace/origin && head -c 4194304 /dev/urandom > /workspace/origin/big.bin")
    commit_files(sb, {"small.txt": "x"})  # commits big.bin too (random bytes do not compress)
    result = setup_workspace(sb, url())
    assert result.ok is False
    assert result.failure_reason == WORKSPACE_FULL_REASON
    assert result.head_commit  # the clone itself worked
    assert sb.has_network is False


def test_setup_timeout_is_reported_and_network_cut(make_sandbox):
    sb = make_sandbox(SandboxConfig(max_lifetime_s=900, setup_timeout_s=1, workspace_mb=512), network=True)
    commit_files(sb, {"a.txt": "x"})
    result = setup_workspace(sb, url())
    assert result.ok is False
    assert result.failure_reason == SETUP_TIMEOUT
    assert any(s.timed_out for s in result.steps)
    assert sb.has_network is False


def test_unreachable_requirement_is_install_failed_with_output_tail(make_sandbox):
    sb = make_sandbox(network=False)  # no network at all: pip cannot reach an index
    commit_files(sb, {"requirements.txt": "definitely-not-a-real-package-xyz==1.0\n"})
    result = setup_workspace(sb, url())
    assert result.ok is False
    assert result.failure_reason == INSTALL_FAILED
    failed = result.steps[-1]
    assert failed.name == "requirements" and failed.ok is False
    assert failed.output_tail
    assert failed.command[-2:] == ("-r", "requirements.txt")


def test_no_sandbox_containers_are_left_by_these_tests(make_sandbox):
    # Only the one created by this test may exist while the module runs.
    sb = make_sandbox()
    assert list_sandbox_containers() == [sb.container_name]


# -- full installs (need PyPI) ---------------------------------------------


def pip_show(sb, package):
    return sb.run(["/workspace/.venv/bin/python", "-m", "pip", "show", package])


@pytest.mark.internet
def test_packaging_repo_with_test_extra(make_sandbox):
    sb = make_sandbox(network=True)
    pyproject = (
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'demo'\nversion = '0.1'\n"
        "[project.optional-dependencies]\ntest = ['iniconfig']\n"
    )
    commit_files(sb, {"pyproject.toml": pyproject, "demo.py": "x = 1\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert result.failure_reason is None
    assert pip_show(sb, "iniconfig").exit_code == 0  # the [test] extra was installed
    assert pip_show(sb, "pytest").exit_code == 0
    assert result.workspace_mb and result.workspace_mb <= CONFIG.workspace_mb
    assert [s.name for s in result.steps if s.name == "project"] == ["project"]
    assert sb.has_network is False
    probe = "import socket; socket.create_connection(('pypi.org', 443), timeout=3)"
    assert sb.run(["/workspace/.venv/bin/python", "-c", probe]).exit_code != 0


@pytest.mark.internet
def test_pep735_dependency_group_is_installed(make_sandbox):
    sb = make_sandbox(network=True)
    pyproject = (
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'demo'\nversion = '0.1'\n"
        "[dependency-groups]\ntests = ['iniconfig']\ndocs = ['definitely-not-a-real-package-xyz']\n"
    )
    commit_files(sb, {"pyproject.toml": pyproject, "demo.py": "x = 1\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    names = [s.name for s in result.steps]
    assert "pip-upgrade" in names and "dependency-group:tests" in names
    assert "dependency-group:docs" not in names  # only test-like groups are installed
    assert pip_show(sb, "iniconfig").exit_code == 0


@pytest.mark.internet
def test_failed_dependency_group_is_a_warning_not_a_failure(make_sandbox):
    sb = make_sandbox(network=True)
    pyproject = (
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'demo'\nversion = '0.1'\n"
        "[dependency-groups]\ntests = ['definitely-not-a-real-package-xyz==9.9']\n"
    )
    commit_files(sb, {"pyproject.toml": pyproject, "demo.py": "x = 1\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert any("dependency-group:tests" in w for w in result.warnings), result.warnings


@pytest.mark.internet
def test_extras_fallback_to_plain_install(make_sandbox):
    sb = make_sandbox(network=True)
    pyproject = (
        "[build-system]\nrequires = ['setuptools']\nbuild-backend = 'setuptools.build_meta'\n"
        "[project]\nname = 'demo'\nversion = '0.1'\n"
        "[project.optional-dependencies]\ntest = ['definitely-not-a-real-package-xyz==9.9']\n"
    )
    commit_files(sb, {"pyproject.toml": pyproject, "demo.py": "x = 1\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    project_attempts = [s for s in result.steps if s.name == "project"]
    assert [s.ok for s in project_attempts] == [False, True]
    assert project_attempts[0].command[-1] == ".[test,tests,testing]"
    assert project_attempts[1].command[-1] == "."


@pytest.mark.internet
def test_requirements_only_repo(make_sandbox):
    sb = make_sandbox(network=True)
    commit_files(sb, {"requirements.txt": "iniconfig==2.0.0\n", "app.py": "print('hi')\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert "2.0.0" in pip_show(sb, "iniconfig").stdout


@pytest.mark.internet
def test_repo_with_nothing_to_install_still_gets_pytest(make_sandbox):
    sb = make_sandbox(network=True)
    commit_files(sb, {"app.py": "print('hi')\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert any("No packaging file" in w for w in result.warnings), result.warnings
    assert pip_show(sb, "pytest").exit_code == 0


@pytest.mark.internet
def test_pinned_pytest_is_not_overridden(make_sandbox):
    sb = make_sandbox(network=True)
    commit_files(sb, {"requirements.txt": "pytest==7.4.4\n"})
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert "7.4.4" in sb.run(["/workspace/.venv/bin/python", "-m", "pytest", "--version"]).stdout + sb.run(
        ["/workspace/.venv/bin/python", "-m", "pytest", "--version"]
    ).stderr


@pytest.mark.internet
def test_optional_test_requirements_failure_is_a_warning(make_sandbox):
    sb = make_sandbox(network=True)
    commit_files(
        sb,
        {"requirements.txt": "iniconfig==2.0.0\n", "requirements-dev.txt": "definitely-not-a-real-package-xyz==1.0\n"},
    )
    result = setup_workspace(sb, url())
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert any("requirements-dev.txt" in w for w in result.warnings), result.warnings


@pytest.mark.internet
def test_real_github_clone_at_a_pinned_commit(make_sandbox):
    sb = make_sandbox(network=True)
    pinned = "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d"  # octocat/Hello-World
    result = setup_repo(sb, RepoRef("octocat", "Hello-World"), ref=pinned)
    assert result.ok, [(s.name, s.output_tail[-300:]) for s in result.steps if not s.ok]
    assert result.head_commit == pinned
    assert sb.has_network is False
