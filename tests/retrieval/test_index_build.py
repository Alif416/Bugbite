"""`build_index`: what it asks the sandbox to run, and how it reacts when the sandbox misbehaves."""

import json
from dataclasses import dataclass

import pytest
from idx_helpers import make_repo

from bugbite.retrieval import SCANNER_SOURCE, IndexLimits, RetrievalError, build_index
from bugbite.retrieval import errors as codes
from bugbite.sandbox import CommandResult


def result(stdout="", stderr="", exit_code=0, timed_out=False, truncated=False):
    return CommandResult(exit_code, stdout, stderr, timed_out, 0.0, truncated)


@dataclass
class Fake:
    reply: CommandResult
    calls: list = None

    def run(self, command, **kw):
        self.calls = (self.calls or []) + [(command, kw)]
        return self.reply


def test_it_runs_one_python_command_with_the_scanner_the_root_and_the_limits(tmp_path):
    box = make_repo(tmp_path, {"a.py": "def f(): ...\n"})
    build_index(box, limits=IndexLimits(max_files=7))
    [command] = box.commands
    assert command[:3] == ["python", "-c", SCANNER_SOURCE] and command[3] == "/workspace/repo"
    assert json.loads(command[4])["max_files"] == 7 and set(json.loads(command[4])) == {"max_files", "max_symbols", "max_file_bytes", "max_output_bytes", "max_depth"}
    assert box.writes == [] and box.reads == []


def test_a_timeout_is_passed_on(tmp_path):
    fake = Fake(result("{}"))
    with pytest.raises(RetrievalError):
        build_index(fake, timeout=5)
    assert fake.calls[0][1] == {"timeout": 5}
    fake2 = Fake(result("{}"))
    with pytest.raises(RetrievalError):
        build_index(fake2)
    assert fake2.calls[0][1] == {}


@pytest.mark.parametrize("reply, code", [
    (result(timed_out=True, exit_code=124), codes.SCAN_TIMEOUT),
    (result("{}", truncated=True), codes.OUTPUT_TOO_LARGE),
    (result(exit_code=2, stderr="OSError: boom"), codes.SCAN_FAILED),
    (result("garbage"), codes.BAD_OUTPUT),
    (result('{"schema_version": 1, "files": [{"path": "/etc/passwd"}], "symbols": [], "truncated": []}'), codes.BAD_OUTPUT),
])
def test_sandbox_trouble_becomes_a_clear_error(reply, code):
    with pytest.raises(RetrievalError) as caught:
        build_index(Fake(reply))
    assert caught.value.code == code and caught.value.message


def test_a_failing_scanner_reports_a_short_reason():
    with pytest.raises(RetrievalError, match="OSError: boom") as caught:
        build_index(Fake(result(exit_code=2, stderr="OSError: boom\n" + "x" * 5000)))
    assert len(caught.value.message) < 400


def test_a_missing_repo_folder_is_a_scan_failure(tmp_path):
    box = make_repo(tmp_path, {"a.py": ""})
    with pytest.raises(RetrievalError) as caught:
        build_index(box, root="/workspace/nowhere")
    assert caught.value.code == codes.SCAN_FAILED


@pytest.mark.parametrize("field", ["max_files", "max_symbols", "max_file_bytes", "max_output_bytes", "max_depth"])
@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "5", None])
def test_bad_limits_are_refused(field, bad):
    with pytest.raises(RetrievalError) as caught:
        IndexLimits(**{field: bad})
    assert caught.value.code == codes.BAD_LIMITS and field in caught.value.message


def test_the_default_output_budget_fits_the_sandbox_output_cap():
    from bugbite.config import SandboxConfig

    assert IndexLimits().max_output_bytes < SandboxConfig().max_output_bytes


def test_an_index_at_the_budget_really_fits_in_the_cap(tmp_path):
    files = {f"pkg{i % 20}/mod{i}.py": "".join(f'def function_{j}(a, b: int = {j}) -> int:\n    """Doc {j}."""\n' for j in range(10)) for i in range(400)}
    box = make_repo(tmp_path, files)
    big = build_index(box, limits=IndexLimits(max_output_bytes=60_000))
    assert big.truncated == ("output_budget",)
    out = json.dumps(big.to_json())
    assert len(out) <= 60_000
