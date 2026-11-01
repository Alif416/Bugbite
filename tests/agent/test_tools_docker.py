"""The read-only tools against a real sandbox: real GNU grep and python output, real symlinks."""

import pytest

from bugbite.agent.tools import build_read_only_tools
from bugbite.config import SandboxConfig
from bugbite.sandbox import Sandbox, list_sandbox_containers

pytestmark = pytest.mark.docker

CONFIG = SandboxConfig(max_lifetime_s=300, setup_timeout_s=120, workspace_mb=256)

_BUILD = r"""
import os
root = "/workspace/repo"
os.makedirs(root + "/src", exist_ok=True)
os.makedirs(root + "/.git", exist_ok=True)
open(root + "/.git/config", "w").write("[core]\n")
open(root + "/src/app.py", "w").write("def parse(x):\n    return x\n")
open(root + "/my file 'q' \"d\".txt", "w").write("quoted needle\n")
open(root + "/bin.dat", "wb").write(b"\x00needle\x00")
os.symlink("/etc", root + "/etclink")
os.symlink("/etc/passwd", root + "/passwd_link")
os.symlink("src/app.py", root + "/alias.py")
"""


@pytest.fixture(scope="module")
def tools():
    before = set(list_sandbox_containers())
    with Sandbox(CONFIG) as sb:
        done = sb.run(["python", "-c", _BUILD])
        assert done.exit_code == 0, done.stderr
        yield build_read_only_tools(sb)
    assert set(list_sandbox_containers()) <= before


def test_list_read_and_search_on_a_real_repo(tools):
    listing = tools.execute("list_directory", {}).text.splitlines()
    assert listing[0] == "src/" and "etclink@" in listing and ".git/" not in listing and "alias.py@" in listing
    assert tools.execute("read_file", {"path": "src/app.py"}).text == "     1| def parse(x):\n     2|     return x"
    assert tools.execute("search_code", {"pattern": "def parse"}).text == "src/app.py:1:def parse(x):"
    assert tools.execute("search_code", {"pattern": "def parse", "glob": "*.py", "path": "src"}).text == "src/app.py:1:def parse(x):"


def test_odd_file_names_work(tools):
    name = "my file 'q' \"d\".txt"
    assert "quoted needle" in tools.execute("read_file", {"path": name}).text
    assert name + ":1:quoted needle" in tools.execute("search_code", {"pattern": "quoted needle"}).text


def test_binary_files_are_refused_and_skipped(tools):
    assert "binary" in tools.execute("read_file", {"path": "bin.dat"}).text
    assert "bin.dat" not in tools.execute("search_code", {"pattern": "needle"}).text


def test_symlinks_cannot_lead_out_of_the_repo(tools):
    for name, args in [("read_file", {"path": "passwd_link"}), ("read_file", {"path": "etclink/hostname"}),
                       ("list_directory", {"path": "etclink"}), ("search_code", {"pattern": "root", "path": "etclink"})]:
        out = tools.execute(name, args)
        assert out.is_error and "outside the repository" in out.text, (name, out)
    assert "root:" not in tools.execute("search_code", {"pattern": "root:"}).text  # recursive search does not follow them either


def test_symlinks_inside_the_repo_work_and_git_stays_hidden(tools):
    assert "def parse" in tools.execute("read_file", {"path": "alias.py"}).text
    assert tools.execute("read_file", {"path": ".git/config"}).is_error
    assert ".git" not in tools.execute("search_code", {"pattern": "core"}).text
