"""Test-run logic without Docker: the real plugin is driven by the host's pytest."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bugbite.sandbox import build_pytest_command, classify, parse_report
from bugbite.sandbox.container import Sandbox
from bugbite.sandbox.testrun import (
    COLLECTION_ERROR,
    CRASHED,
    NO_TESTS_STATUS,
    OK,
    TIMEOUT,
    ParsedReport,
)

PLUGIN_DIR = Path(__file__).resolve().parents[2] / "src" / "bugbite" / "sandbox" / "plugin"

MIXED = '''
import pytest

def test_pass(): assert True

def test_fail(): assert 1 == 2

@pytest.mark.skip(reason="not now")
def test_skip(): pass

@pytest.mark.xfail(reason="known bug")
def test_xfail(): assert False

@pytest.mark.xfail(reason="fixed?")
def test_xpass(): assert True

@pytest.mark.xfail(strict=True, reason="strict")
def test_strict_xpass(): assert True

@pytest.fixture
def broken(): raise RuntimeError("setup boom")

def test_setup_error(broken): pass

@pytest.fixture
def bad_teardown():
    yield
    raise RuntimeError("teardown boom")

def test_teardown_error(bad_teardown): pass

def test_fail_then_teardown_error(bad_teardown): assert False

@pytest.mark.parametrize("value", ["a b", "x/y", "caf\\u00e9", "[z]", "q'uote", 1, None])
def test_param(value): pass

class TestGroup:
    def test_one(self): pass
    def test_two(self): assert False
'''


def run_pytest(tmp_path, files, *args, with_plugin=True, env_extra=None, report_name="report.jsonl"):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")  # makes tmp_path the rootdir
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    report = tmp_path / report_name
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "BUGBITE_"))}
    env["BUGBITE_REPORT_FILE"] = str(report)
    env["PYTHONPATH"] = str(PLUGIN_DIR) if with_plugin else ""
    env.update(env_extra or {})
    command = [sys.executable, "-m", "pytest", "-p", "bugbite_report", "-p", "no:cacheprovider", "--tb=short", "--color=no", *args]
    proc = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    text = report.read_text() if report.exists() else ""
    return proc, parse_report(text), text


# -- the real plugin ----------------------------------------------------------


def test_every_outcome_is_recorded_exactly(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"test_mixed.py": MIXED})
    assert proc.returncode == 1
    out = {test_id.split("::", 1)[1]: case.outcome for test_id, case in parsed.tests.items()}
    assert out["test_pass"] == "passed"
    assert out["test_fail"] == "failed"
    assert out["test_skip"] == "skipped"
    assert out["test_xfail"] == "xfailed"
    assert out["test_xpass"] == "xpassed"
    assert out["test_strict_xpass"] == "failed"
    assert out["test_setup_error"] == "error"
    assert out["test_teardown_error"] == "error"  # the call passed, teardown failed
    assert out["test_fail_then_teardown_error"] == "failed"  # a failure is not overwritten
    assert out["TestGroup::test_one"] == "passed"
    assert out["TestGroup::test_two"] == "failed"
    assert parsed.exit_status == 1
    assert parsed.collected == len(parsed.tests)
    assert parsed.malformed_lines == 0


def test_recorded_ids_match_pytests_own_ids(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"test_mixed.py": MIXED})
    listing = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path, capture_output=True, text=True,
    )  # fmt: skip
    own_ids = {line for line in listing.stdout.splitlines() if "::" in line}
    assert own_ids and set(parsed.tests) == own_ids


def test_parametrized_ids_with_odd_characters(tmp_path):
    _, parsed, _ = run_pytest(tmp_path, {"test_mixed.py": MIXED})
    params = [i for i in parsed.tests if "::test_param[" in i]
    assert len(params) == 7
    assert any("[a b]" in i for i in params)
    assert any("[x/y]" in i for i in params)
    assert any("[q'uote]" in i for i in params)
    assert all(parsed.tests[i].outcome == "passed" for i in params)


def test_failure_and_skip_messages(tmp_path):
    _, parsed, _ = run_pytest(tmp_path, {"test_mixed.py": MIXED})
    by_name = {i.split("::", 1)[1]: c for i, c in parsed.tests.items()}
    assert "assert 1 == 2" in by_name["test_fail"].message
    assert "not now" in by_name["test_skip"].message
    assert by_name["test_xfail"].message == "known bug"
    assert "setup boom" in by_name["test_setup_error"].message
    assert all(len(c.message) <= 500 for c in parsed.tests.values())
    assert all(c.duration_s >= 0 for c in parsed.tests.values())


def test_all_passing_suite(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"test_ok.py": "def test_a(): pass\ndef test_b(): pass\n"})
    assert proc.returncode == 0
    assert classify(proc.returncode, False, parsed, proc.stdout) == (OK, "")
    assert sorted(c.outcome for c in parsed.tests.values()) == ["passed", "passed"]


def test_deselection_is_reflected_in_collected_count(tmp_path):
    files = {"test_ok.py": "def test_keep(): pass\ndef test_drop(): pass\n"}
    _, parsed, _ = run_pytest(tmp_path, files, "-k", "keep")
    assert list(parsed.tests) == ["test_ok.py::test_keep"]
    assert parsed.collected == 1


def test_selecting_a_single_node_id(tmp_path):
    files = {"test_ok.py": "def test_a(): pass\ndef test_b(): pass\n"}
    _, parsed, _ = run_pytest(tmp_path, files, "--", "test_ok.py::test_b")
    assert list(parsed.tests) == ["test_ok.py::test_b"]


def test_collection_error_is_recorded(tmp_path):
    files = {"test_bad.py": "import not_a_real_module_xyz\ndef test_a(): pass\n", "test_ok.py": "def test_b(): pass\n"}
    proc, parsed, _ = run_pytest(tmp_path, files)
    assert proc.returncode == 2
    assert [e.id for e in parsed.collection_errors] == ["test_bad.py"]
    assert "not_a_real_module_xyz" in parsed.collection_errors[0].message
    status, reason = classify(proc.returncode, False, parsed, proc.stdout)
    assert status == COLLECTION_ERROR
    assert "test_bad.py" in reason and "not_a_real_module_xyz" in reason


def test_no_tests(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"app.py": "x = 1\n"})
    assert proc.returncode == 5
    assert parsed.collected == 0 and parsed.tests == {} and parsed.collection_errors == ()
    assert classify(proc.returncode, False, parsed, proc.stdout)[0] == NO_TESTS_STATUS


def test_usage_error_from_bad_option_is_a_collection_error(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"test_ok.py": "def test_a(): pass\n"}, "--definitely-not-an-option")
    assert proc.returncode == 4
    status, reason = classify(proc.returncode, False, parsed, proc.stdout + proc.stderr)
    assert status == COLLECTION_ERROR
    assert "usage error" in reason and "definitely-not-an-option" in reason


def test_plugin_that_cannot_load_is_crashed_not_ok(tmp_path):
    proc, parsed, _ = run_pytest(tmp_path, {"test_ok.py": "def test_a(): pass\n"}, with_plugin=False)
    assert proc.returncode != 0
    status, reason = classify(proc.returncode, False, parsed, proc.stdout + proc.stderr)
    assert status == CRASHED
    assert "report plugin" in reason


def test_list_ids_mode(tmp_path):
    files = {"test_ok.py": "def test_a(): pass\ndef test_b(): pass\n"}
    proc, parsed, _ = run_pytest(tmp_path, files, "--collect-only", "-q", env_extra={"BUGBITE_LIST_IDS": "1"})
    assert proc.returncode == 0
    assert parsed.collected_ids == ("test_ok.py::test_a", "test_ok.py::test_b")
    assert parsed.tests == {}


def test_ids_are_not_listed_unless_asked(tmp_path):
    _, parsed, _ = run_pytest(tmp_path, {"test_ok.py": "def test_a(): pass\n"})
    assert parsed.collected == 1 and parsed.collected_ids == ()


def test_plugin_appends_and_never_truncates_an_existing_report(tmp_path):
    (tmp_path / "report.jsonl").write_text('{"t": "test", "id": "old::one", "outcome": "passed", "duration": 0}\n')
    _, parsed, text = run_pytest(tmp_path, {"test_ok.py": "def test_a(): pass\n"})
    assert text.startswith('{"t": "test", "id": "old::one"')
    assert set(parsed.tests) == {"old::one", "test_ok.py::test_a"}


def test_partial_results_survive_a_killed_run(tmp_path):
    files = {"test_slow.py": "import time\ndef test_quick(): pass\ndef test_hang(): time.sleep(60)\n"}
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_slow.py").write_text(files["test_slow.py"])
    report = tmp_path / "report.jsonl"
    env = {**os.environ, "PYTHONPATH": str(PLUGIN_DIR), "BUGBITE_REPORT_FILE": str(report)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-p", "bugbite_report", "-p", "no:cacheprovider"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )  # fmt: skip
    deadline = time.time() + 30
    while time.time() < deadline and not (report.exists() and "test_quick" in report.read_text()):
        time.sleep(0.2)
    proc.kill()
    proc.wait()
    parsed = parse_report(report.read_text())
    assert parsed.tests["test_slow.py::test_quick"].outcome == "passed"
    assert "test_slow.py::test_hang" not in parsed.tests
    assert parsed.exit_status is None
    assert classify(-9, True, parsed, "")[0] == TIMEOUT


def test_plugin_source_uses_only_the_standard_library():
    source = (PLUGIN_DIR / "bugbite_report.py").read_text()
    imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {"json", "os"}


# -- parse_report ----------------------------------------------------------------


def lines(*records):
    return "\n".join(json.dumps(r) for r in records) + "\n"


def test_parse_tolerates_blank_and_malformed_lines():
    text = (
        "\n"
        + lines({"t": "collected", "count": 2})
        + "this is not json\n"
        + '{"t": "test", "id": "a::b", "outcome": "passed", "duration": 0.5, "message": ""}\n'
        + '{"t": "test", "id": "a::c", "outcome": "bogus"}\n'  # unknown outcome
        + '{"t": "unknown"}\n'
        + "[1, 2]\n"
        + '{"t": "test", "id": "cut off\n'
    )
    parsed = parse_report(text)
    assert list(parsed.tests) == ["a::b"]
    assert parsed.collected == 2
    assert parsed.malformed_lines == 5


def test_parse_unicode_and_later_duplicate_wins():
    text = lines(
        {"t": "test", "id": "t::x", "outcome": "failed", "duration": 1, "message": "first"},
        {"t": "test", "id": "t::x", "outcome": "passed", "duration": 2, "message": "café ✓"},
    )
    parsed = parse_report(text)
    assert parsed.tests["t::x"].outcome == "passed"
    assert parsed.tests["t::x"].message == "café ✓"


def test_parse_xdist_workers_controller_session_wins():
    text = lines(
        {"t": "collected", "count": 3, "worker": "gw0"},
        {"t": "collected", "count": 4, "worker": "gw1"},
        {"t": "test", "id": "t::a", "outcome": "passed", "worker": "gw0"},
        {"t": "test", "id": "t::b", "outcome": "failed", "worker": "gw1"},
        {"t": "session", "exitstatus": 0, "worker": "gw0"},
        {"t": "session", "exitstatus": 1, "worker": None},
    )
    parsed = parse_report(text)
    assert parsed.collected == 4
    assert parsed.exit_status == 1
    assert set(parsed.tests) == {"t::a", "t::b"}


def test_parse_missing_session_and_empty_input():
    assert parse_report(lines({"t": "collected", "count": 1})).exit_status is None
    empty = parse_report("")
    assert empty.tests == {} and empty.collected is None and empty.exit_status is None


def test_parse_dedupes_collection_errors():
    rec = {"t": "collect_error", "id": "test_x.py", "message": "boom"}
    assert len(parse_report(lines(rec, rec)).collection_errors) == 1


# -- classify (every rule) --------------------------------------------------------


def report(session=0, errors=(), collected=1):
    from bugbite.sandbox.testrun import CollectionError

    return ParsedReport({}, collected, (), tuple(CollectionError(i, m) for i, m in errors), session, 0)


def test_classify_rules():
    assert classify(0, False, report(0), "")[0] == OK
    assert classify(1, False, report(1), "")[0] == OK
    assert classify(1, True, report(None), "")[0] == TIMEOUT  # timeout wins over everything
    assert classify(5, False, report(5, collected=0), "")[0] == NO_TESTS_STATUS
    assert classify(2, False, report(2, errors=[("t.py", "ImportError")]), "")[0] == COLLECTION_ERROR
    assert classify(4, False, report(None), "error: unrecognized arguments: --cov")[0] == COLLECTION_ERROR
    assert classify(4, False, None, "Error importing plugin bugbite_report")[0] == CRASHED
    assert classify(3, False, report(3), "INTERNALERROR")[0] == CRASHED
    assert classify(2, False, report(2), "Interrupted: stopping")[0] == CRASHED  # no collection errors recorded
    assert classify(0, False, report(None), "")[0] == CRASHED  # exited 0 but no session line
    assert classify(0, False, None, "")[0] == CRASHED  # report file missing
    assert classify(137, False, None, "Killed")[0] == CRASHED
    assert classify(127, False, None, "not found")[0] == CRASHED


def test_classify_reasons_are_readable():
    out = "line one\n__main__.py: error: unrecognized arguments: --cov\n  rootdir: /x\n"
    _, reason = classify(4, False, None, out)
    assert reason.endswith("unrecognized arguments: --cov")
    assert classify(1, True, None, "")[1].startswith("The run hit the time limit")
    assert "137" in classify(137, False, None, "Killed")[1]


# -- targets and command -----------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", "-x", "--pdb", "--rootdir=/", " -x", "a\nb", "a\x00b", "a\tb"])
def test_bad_targets_are_rejected(bad):
    with pytest.raises(ValueError):
        build_pytest_command([bad])


def test_non_string_target_rejected():
    with pytest.raises(ValueError):
        build_pytest_command([None])


@pytest.mark.parametrize(
    "good",
    ["tests/test_a.py", "tests/", "tests/test_a.py::TestX::test_y", "tests/t.py::test_p[a-b]", "t.py::test_p[a b]", "t.py::test_p['q']"],
)
def test_good_targets_are_accepted(good):
    assert build_pytest_command([good])[-2:] == ["--", good]


def test_command_shape_and_no_shell():
    command = build_pytest_command(["tests/test_a.py::test_b"], ["-x"])
    assert command == [
        "/workspace/.venv/bin/python", "-m", "pytest",
        "-p", "bugbite_report", "-p", "no:cacheprovider", "--tb=short", "--color=no",
        "-x", "--", "tests/test_a.py::test_b",
    ]  # fmt: skip
    assert command[0] != "sh" and "-c" not in command


def test_collect_only_command_and_no_targets():
    command = build_pytest_command(collect_only=True)
    assert command[-2:] == ["--collect-only", "-q"]
    assert "--" not in command


def test_extra_args_cannot_contain_control_characters():
    with pytest.raises(ValueError):
        build_pytest_command([], ["-x\n--pdb"])


# -- sandbox file helpers (validation only; no container needed) -------------------


@pytest.mark.parametrize("bad", ["relative.txt", "/etc/passwd", "/workspace", "/workspace/../etc/x", "/workspaceevil/x", "/workspace/a\nb"])
def test_write_and_read_reject_bad_paths(bad):
    sb = Sandbox()
    with pytest.raises(ValueError):
        sb.write_file(bad, "x")
    with pytest.raises(ValueError):
        sb.read_file(bad)
