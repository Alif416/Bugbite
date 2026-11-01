import pytest
from tool_helpers import LocalSandbox

from bugbite.agent.tools import RunCommand, RunTests
from bugbite.agent.tools import edit_run as er
from bugbite.sandbox import CommandResult, SuiteRun
from bugbite.sandbox.testrun import CaseResult, CollectionError


def suite(status="ok", reason="", tests=None, errors=(), tail="", exit_code=1):
    return SuiteRun(
        status=status, reason=reason, exit_code=exit_code, tests=tests or {}, collected=len(tests or {}), collected_ids=(),
        collection_errors=tuple(errors), duration_s=0.1, output_tail=tail, output_truncated=False,
    )


def case(outcome, message=""):
    return CaseResult(outcome, 0.01, message)


# -- summary -------------------------------------------------------------------------------------------------


def test_all_passing_is_one_line():
    text = er.summarise(suite(tests={"t::a": case("passed"), "t::b": case("passed"), "t::c": case("skipped")}, tail="lots of output", exit_code=0))
    assert text == "Ran 3 tests: 1 skipped, 2 passed." or text == "Ran 3 tests: 2 passed, 1 skipped."
    assert "output" not in text


def test_failures_are_listed_with_one_line_reasons_and_the_tail():
    tests = {"t::a": case("passed"), "t::b": case("failed", "\n  assert 1 == 2\nmore lines"), "t::c": case("error", "fixture 'x' not found")}
    text = er.summarise(suite(tests=tests, tail="Traceback ... line 9"))
    assert "Ran 3 tests: 1 error, 1 failed, 1 passed." in text
    assert "FAILED t::b: assert 1 == 2" in text and "ERROR t::c: fixture 'x' not found" in text
    assert text.endswith("End of output:\nTraceback ... line 9") and "more lines" not in text


def test_long_lists_messages_and_tail_are_capped():
    tests = {f"t::{i:03}": case("failed", "x" * 500) for i in range(40)}
    text = er.summarise(suite(tests=tests, tail="y" * 5000))
    assert text.count("FAILED t::") == er.MAX_FAILURES_SHOWN and "[25 more failing tests not shown]" in text
    assert "x" * 201 not in text and "[cut]" in text
    assert text.endswith("y" * er.TEST_TAIL_CHARS) and "y" * (er.TEST_TAIL_CHARS + 1) not in text


def test_collection_errors_are_listed_and_capped():
    errors = [CollectionError(f"tests/test_{i}.py", "ImportError: no module named foo") for i in range(8)]
    text = er.summarise(suite("collection_error", "8 collection error(s); first: tests/test_0.py", errors=errors))
    assert text.startswith("Test run status: collection_error. 8 collection error(s)")
    assert text.count("COLLECTION ERROR") == er.MAX_COLLECTION_ERRORS_SHOWN and "[3 more collection errors not shown]" in text


@pytest.mark.parametrize("status, reason", [
    ("timeout", "The run hit the time limit and was stopped"), ("crashed", "pytest finished but no report was recorded."),
    ("no_tests", "pytest collected no tests."),
])
def test_unfinished_runs_say_so_plainly(status, reason):
    text = er.summarise(suite(status, reason, tests={"t::a": case("passed")}, tail="last words"))
    assert text.startswith(f"Test run status: {status}. {reason}") and "Results recorded before it stopped: 1 passed." in text
    assert text.endswith("End of output:\nlast words")


def test_an_empty_ok_run():
    assert er.summarise(suite()) == "Ran 0 tests: nothing ran."


# -- the tool -------------------------------------------------------------------------------------------------


class Recorder:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result, self.exc = result or suite(tests={"t::a": case("passed")}, exit_code=0), exc

    def __call__(self, sandbox, targets, *, extra_args=()):
        self.calls.append((list(targets), list(extra_args)))
        if self.exc:
            raise self.exc
        return self.result


def test_targets_and_keyword_become_separate_arguments():
    rec = Recorder()
    out = RunTests(None, rec).run({"targets": ["tests/test_a.py::test_x", "tests/test_b.py"], "keyword": "parse and not slow"})
    assert not out.is_error and rec.calls == [(["tests/test_a.py::test_x", "tests/test_b.py"], ["-k", "parse and not slow"])]
    rec2 = Recorder()
    RunTests(None, rec2).run({})
    assert rec2.calls == [([], [])]


@pytest.mark.parametrize("args, fragment", [
    ({"keyword": "-x"}, "must not start"), ({"keyword": "  --pdb"}, "must not start"),
    ({"targets": ["a"] * 21}, "targets"), ({"targets": [""]}, "targets"), ({"targets": "a.py"}, "targets"), ({"targets": [1]}, "targets"),
    ({"keyword": ""}, "keyword"), ({"extra": 1}, "extra"),
])
def test_run_tests_rejects_bad_input(args, fragment):
    rec = Recorder()
    out = RunTests(None, rec).run(args)
    assert out.is_error and fragment in out.text and rec.calls == []


def test_the_runners_own_validation_becomes_an_error_result():
    out = RunTests(None, Recorder(exc=ValueError("test target must not look like an option: '-x'"))).run({"targets": ["-x"]})
    assert out.is_error and "Invalid test target" in out.text


def test_a_failing_test_run_is_a_normal_result_not_an_error():
    rec = Recorder(suite(tests={"t::a": case("failed", "boom")}))
    assert RunTests(None, rec).run({}).is_error is False


# -- run_command ------------------------------------------------------------------------------------------------


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    box = LocalSandbox(root)
    box.allow_shell = True
    return box


def test_exit_code_and_output(sb):
    assert RunCommand(sb).run({"command": "echo hello"}).text == "exit code 0\nhello"
    out = RunCommand(sb).run({"command": "echo out; echo err 1>&2; exit 3"})
    assert out.text == "exit code 3\nout\n[stderr]\nerr" and not out.is_error


def test_empty_output_says_so(sb):
    assert RunCommand(sb).run({"command": "true"}).text == "exit code 0\n(no output)"


def test_long_output_keeps_the_start_and_the_end(sb):
    out = RunCommand(sb).run({"command": "python3 -c \"print('A'*5000); print('B'*5000)\""}).text
    assert out.startswith("exit code 0\nAAAA") and out.endswith("BBBB")
    assert "characters left out" in out and len(out) < er.OUTPUT_HEAD_CHARS + er.OUTPUT_TAIL_CHARS + 200


class Scripted:
    def __init__(self, result, network=False):
        self.result, self.has_network, self.calls = result, network, []
        from bugbite.config import SandboxConfig
        self.config = SandboxConfig(command_timeout_s=50)

    def run(self, command, **kw):
        self.calls.append((command, kw))
        return self.result


def done(**kw):
    base = dict(exit_code=0, stdout="", stderr="", timed_out=False, duration_s=1.0, truncated=False)
    return CommandResult(**{**base, **kw})


def test_timeouts_are_reported_and_clamped_to_the_sandbox_limit():
    box = Scripted(done(exit_code=124, stdout="partial", timed_out=True))
    out = RunCommand(box).run({"command": "sleep 99", "timeout_s": 500})
    assert out.text == "timed out after 50s\npartial"
    assert box.calls[0][1]["timeout"] == 50
    RunCommand(box).run({"command": "x", "timeout_s": 7})
    RunCommand(box).run({"command": "x"})
    assert [c[1]["timeout"] for c in box.calls] == [50, 7, 50]


def test_it_refuses_to_run_when_the_sandbox_has_network():
    box = Scripted(done(stdout="should not run"), network=True)
    out = RunCommand(box).run({"command": "curl example.com"})
    assert out.is_error and "network" in out.text and box.calls == []


def test_the_environment_and_directory_are_constants():
    box = Scripted(done(stdout="x"))
    RunCommand(box).run({"command": "env"})
    command, kw = box.calls[0]
    assert command == "env" and kw["workdir"] == "/workspace/repo"
    assert kw["env"] == {"PATH": "/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def test_the_sandbox_output_limit_is_noted():
    assert "cut the output at its limit" in RunCommand(Scripted(done(stdout="x", truncated=True))).run({"command": "yes"}).text


@pytest.mark.parametrize("args", [{}, {"command": ""}, {"command": 5}, {"command": "x" * 2001}, {"command": "a\x00b"}, {"command": "x", "timeout_s": 0},
                                  {"command": "x", "timeout_s": "5"}, {"command": "x", "timeout_s": True}, {"command": "x", "cwd": "/"}])
def test_run_command_rejects_bad_input(args):
    box = Scripted(done())
    assert RunCommand(box).run(args).is_error and box.calls == []
