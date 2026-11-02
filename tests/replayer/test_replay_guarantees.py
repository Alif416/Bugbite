"""Replay is deterministic, read-only and offline (README FR10.2, FR10.5), and the golden recording replays."""

import json
import os
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from loop_helpers import Clock
from rp_helpers import (
    USAGE, AdapterError, FakeTools, Limits, ToolOutput, record, replay_it, text_response, tool_call_response, tree_hashes,
)
from test_replay_end_to_end import SlowTools, again

from bugbite import replay as replay_cli
from bugbite.replayer import replay

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "bugbite"
GOLDEN = ROOT / "tests" / "fixtures" / "recordings" / "20270101T000000Z-golden01"


def scenarios(tmp_path, provider):
    """A handful of different recordings, made one after another with the same registered provider."""
    out = []
    tools = FakeTools(outputs={"echo": ToolOutput("echoed")})
    out.append(record(tmp_path / "a", provider, [tool_call_response(("echo", {"text": "hi"}), **USAGE), text_response("Fixed.", **USAGE)], tools=tools)[1])
    out.append(record(tmp_path / "b", provider, [AdapterError("server_error", "broke", status_code=500)])[1])
    out.append(record(tmp_path / "c", provider, again(5), tools=FakeTools(outputs={"echo": ToolOutput("same")}))[1])
    clock = Clock()
    out.append(record(tmp_path / "d", provider, [tool_call_response(("echo", {"text": "a"}), **USAGE)], tools=SlowTools(clock, 10),
                      limits=Limits(10, max_wall_clock_s=5), clock=clock, monotonic=clock)[1])
    return out


def test_replaying_twice_gives_equal_results_and_the_recording_is_untouched(tmp_path, provider):
    for path in scenarios(tmp_path, provider):
        before = tree_hashes(path)
        first, second = replay_it(path), replay_it(path)
        assert first.identical and second.identical, (path, first.differences, first.divergence)
        assert first.agent == second.agent and first.events == second.events and first.notes == second.notes
        assert tree_hashes(path) == before


def test_replay_works_on_a_read_only_recording(tmp_path, provider):
    [path, *_] = scenarios(tmp_path, provider)
    for f in path.iterdir():
        f.chmod(0o400)
    path.chmod(0o500)
    try:
        assert replay_it(path).identical
    finally:
        path.chmod(0o700)
        for f in path.iterdir():
            f.chmod(0o600)


def test_replay_needs_no_network_no_environment_and_no_key(tmp_path, provider, monkeypatch):
    paths = scenarios(tmp_path, provider)

    def no_network(*a, **k):
        raise AssertionError("the replay tried to use the network")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    for name in list(os.environ):
        monkeypatch.delenv(name)
    assert all(replay_it(p).identical for p in paths)


FORBIDDEN = re.compile(r"\bos\.environ\b|\bgetenv\b|\bsocket\b|\bhttpx\b|\brequests\b|\bdocker\b|\bsubprocess\b|\burllib\b|\banthropic\b|\bsandbox\b", re.I)
WRITES = re.compile(r"\.write_(text|bytes)\(|open\([^)]*['\"][wax+]|os\.(remove|unlink|rename|replace|mkdir|makedirs|chmod)|shutil\.")


def code_only(text):
    """Source without comments and docstrings, which may talk about these things."""
    kept, in_doc = [], False
    for line in text.splitlines():
        if line.count('"""') % 2 == 1:
            in_doc = not in_doc
            continue
        if not in_doc and not line.strip().startswith(('"""', "#")):
            kept.append(line.split("  #")[0])
    return "\n".join(kept)


def replayer_files():
    files = sorted((SRC / "replayer").glob("*.py")) + [SRC / "replay.py"]
    assert len(files) >= 9
    return files


def test_the_checks_below_would_catch_what_they_look_for():
    for bad in ("import socket", "os.environ['KEY']", "os.getenv('KEY')", "import httpx", "import docker", "import subprocess", "from anthropic import X", "sandbox.run()"):
        assert FORBIDDEN.search(code_only(bad)), bad
    for bad in ("p.write_text('x')", "open(p, 'w')", "open(p, mode='ab')", "os.remove(p)", "shutil.copy(a, b)", "os.chmod(p, 0)"):
        assert WRITES.search(code_only(bad)), bad
    assert not FORBIDDEN.search(code_only('"""the sandbox, os.environ and socket"""\nx = 1  # docker\n'))


def test_the_replayer_source_never_touches_the_environment_the_network_or_docker():
    for file in replayer_files():
        assert not FORBIDDEN.search(code_only(file.read_text())), f"{file.name} mentions something it must not use"


def test_the_replayer_opens_files_only_for_reading():
    for file in replayer_files():
        assert not WRITES.search(code_only(file.read_text())), file.name


# -- the golden recording ---------------------------------------------------------------------------------------------------------


def test_the_golden_recording_replays_identically():
    from make_golden import GOLDEN_PROMPT  # noqa: PLC0415

    result = replay(GOLDEN, system_prompt=GOLDEN_PROMPT, tool_definitions=FakeTools().definitions())
    assert result.identical and result.divergence is None and result.agent.status == "finished"
    assert result.agent.final_text == "The bug is fixed." and str(result.agent.cost_usd) == "0.068"
    assert [e["type"] for e in result.events] == ["model_call", "step", "tool_call", "model_call", "step", "finish"]
    assert result.notes == ()


def test_the_golden_recording_stops_with_the_real_prompt_because_it_was_made_with_another():
    result = replay(GOLDEN, tool_definitions=FakeTools().definitions())
    assert result.divergence is not None and result.divergence.call == 1 and "sha256" in result.divergence.fields
    assert any("system prompt" in n for n in result.notes)


# -- the command line -------------------------------------------------------------------------------------------------------------


@pytest.fixture
def golden_args():
    return [str(GOLDEN)]


def run_cli(capsys, *args):
    code = replay_cli.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_exit_codes_and_output(capsys, tmp_path, provider):
    # the real prompt and tools differ from the golden's, so replaying the golden with the defaults diverges: exit 1
    code, out, err = run_cli(capsys, str(GOLDEN))
    assert code == 1 and out.startswith("DIVERGED at request_mismatch (call 1)") and "note: the system prompt" in out and err == ""
    # a recording made with the real prompt and the test tools is not possible (the tools differ), so use the default tool set
    from bugbite.agent.tools import build_agent_tools

    _, path = record(tmp_path, provider, [text_response("done", **USAGE)], tools=type("T", (), {
        "definitions": lambda self: build_agent_tools(None).definitions(), "execute": lambda self, *a, **k: ToolOutput("x")})())
    code, out, err = run_cli(capsys, str(path))
    assert code == 0 and out.startswith("IDENTICAL") and "3 events" in out and "run ended as finished" in out and err == ""
    code, out, err = run_cli(capsys, str(tmp_path / "missing"))
    assert code == 2 and out == "" and err.startswith("cannot replay:") and "missing" in err


def test_cli_refuses_a_partial_recording_unless_allowed(capsys, tmp_path, provider):
    from bugbite.agent.tools import build_agent_tools
    from rp_helpers import make_partial

    class RealToolNames:
        def definitions(self):
            return build_agent_tools(None).definitions()

        def execute(self, *a, **k):
            return ToolOutput("x")

    _, path = record(tmp_path, provider, [tool_call_response(("read_file", {"path": "a.py"}), **USAGE), text_response("done", **USAGE)], tools=RealToolNames())
    partial = make_partial(path, tmp_path / "p", 3)
    code, out, err = run_cli(capsys, str(partial))
    assert code == 2 and "not complete" in err
    code, out, err = run_cli(capsys, str(partial), "--allow-partial")
    assert code == 1 and "recording_ended" in out


def test_cli_json_output(capsys):
    code, out, err = run_cli(capsys, str(GOLDEN), "--json")
    data = json.loads(out)
    assert code == 1 and data["identical"] is False and data["divergence"]["kind"] == "request_mismatch" and data["divergence"]["call"] == 1
    assert set(data) == {"identical", "status", "divergence", "differences", "notes", "events"}


def test_cli_runs_as_a_module(tmp_path):
    done = subprocess.run([sys.executable, "-m", "bugbite.replay", str(tmp_path / "nothing")], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 2 and "cannot replay" in done.stderr
    done = subprocess.run([sys.executable, "-m", "bugbite.replay", "--help"], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0 and "--allow-partial" in done.stdout


def test_cli_needs_a_folder(capsys):
    with pytest.raises(SystemExit) as exit_info:
        replay_cli.main([])
    assert exit_info.value.code == 2
