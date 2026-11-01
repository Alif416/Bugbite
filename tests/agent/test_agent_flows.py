"""The loop with the real tools, the text-action wrapper, cost tracking and the privacy gate."""

import re
from pathlib import Path

import pytest
from loop_helpers import FakeTools
from tool_helpers import LocalSandbox

from bugbite.adapter import (
    CostLedger,
    GenerationRequest,
    Message,
    TextActionAdapter,
    create_adapter,
    register_adapter,
    unregister_adapter,
)
from bugbite.adapter.testing import ScriptedAdapter, text_response, tool_call_response
from bugbite.agent import FINISHED, MAX_STEPS, PRIVACY_BLOCKED, Limits, run_agent
from bugbite.agent.tools import build_agent_tools
from bugbite.config import ModelConfig, Pricing
from bugbite.privacy import Sensitivity
from bugbite.sandbox import SuiteRun
from bugbite.sandbox.testrun import CaseResult


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    box = LocalSandbox(root)
    box.allow_shell = True
    box.write("app.py", "def add(a, b):\n    return a - b\n")
    box.write("tests/test_app.py", "from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return box


def fake_runner(sandbox, targets, *, extra_args=(), timeout=None):
    """Runs the repo's tiny test by hand so the 'tests' really depend on the file the agent edits."""
    ok = "a + b" in (sandbox.root / "app.py").read_text()
    outcome = "passed" if ok else "failed"
    return SuiteRun("ok", "", 0 if ok else 1, {"tests/test_app.py::test_add": CaseResult(outcome, 0.0, "" if ok else "assert -1 == 3")},
                    1, (), (), 0.1, "", False)


def test_a_scripted_model_fixes_a_bug_with_the_real_tools(sb):
    tools = build_agent_tools(sb, test_runner=fake_runner)
    model = ScriptedAdapter(None, [
        tool_call_response(("list_directory", {}), ("search_code", {"pattern": "def add"})),
        tool_call_response(("read_file", {"path": "app.py"}), first_id=3),
        tool_call_response(("run_tests", {}), first_id=4),
        tool_call_response(("edit_file", {"path": "app.py", "old_text": "a - b", "new_text": "a + b"}), first_id=5),
        tool_call_response(("run_tests", {}), first_id=6),
        text_response("Fixed: add subtracted. Changed one line; run_tests passes."),
    ])
    result = run_agent(model, tools, "add(1, 2) returns -1", limits=Limits(max_steps=10))
    assert result.status == FINISHED and result.final_text.startswith("Fixed")
    assert (sb.root / "app.py").read_text() == "def add(a, b):\n    return a + b\n"
    outputs = [r.output.text for step in result.steps for r in step.tool_runs]
    assert "app.py:1:def add(a, b):" in outputs[1] and "FAILED tests/test_app.py::test_add" in outputs[3]
    assert outputs[5] == "Ran 1 tests: 1 passed." and not any(r.output.is_error for s in result.steps for r in s.tool_runs)


def test_the_model_cannot_rewrite_the_test_to_make_it_pass(sb):
    tools = build_agent_tools(sb, test_runner=fake_runner)
    model = ScriptedAdapter(None, [
        tool_call_response(("edit_file", {"path": "tests/test_app.py", "old_text": "== 3", "new_text": "== -1"})),
        text_response("I could not change the test."),
    ])
    result = run_agent(model, tools, "task", limits=Limits(max_steps=5))
    assert result.steps[0].tool_runs[0].output.is_error and "not allowed" in result.steps[0].tool_runs[0].output.text
    assert "== 3" in (sb.root / "tests/test_app.py").read_text()


def test_run_command_works_inside_the_loop(sb):
    tools = build_agent_tools(sb, test_runner=fake_runner)
    model = ScriptedAdapter(None, [tool_call_response(("run_command", {"command": "echo hi"})), text_response("done")])
    result = run_agent(model, tools, "task", limits=Limits(max_steps=3))
    assert result.steps[0].tool_runs[0].output.text == "exit code 0\nhi"


# -- a model without native tool calling -----------------------------------------------------------------------------


def non_native():
    return ModelConfig("plain", "scripted", "http://x", "m", 100_000, False, Pricing.free(), 0, True)


def test_a_text_only_model_completes_a_run_including_a_failed_step(sb):
    tools = build_agent_tools(sb, test_runner=fake_runner)
    raw = ScriptedAdapter(non_native(), [
        text_response('{"tool": "read_file", "arguments": {"path": "app.py"}}'),
        text_response("I will now think about it"),            # not an action ...
        text_response("still no action here"),                 # ... and the repair fails too: a failed step
        text_response('{"tool": "edit_file", "arguments": {"path": "app.py", "old_text": "a - b", "new_text": "a + b"}}'),
        text_response('{"final": "Fixed the sign."}'),
    ])
    adapter = TextActionAdapter(raw)
    result = run_agent(adapter, tools, "task", limits=Limits(max_steps=10))
    assert result.status == FINISHED and result.final_text == "Fixed the sign."
    assert (sb.root / "app.py").read_text().endswith("a + b\n")
    failed = result.steps[1].tool_runs[0]
    assert failed.call.name == "invalid_action" and failed.executed is False and failed.output.is_error
    assert adapter.stats.failed_steps == 1 and adapter.stats.steps >= 3
    assert raw.remaining == 0


# -- cost tracking and the privacy gate -----------------------------------------------------------------------------


@pytest.fixture
def provider():
    built = {}

    def factory(cfg, key):
        built["raw"] = ScriptedAdapter(cfg, [tool_call_response(("echo", {"text": "x"})), text_response("done")])
        return built["raw"]

    register_adapter("loop_fake", factory)
    yield built
    unregister_adapter("loop_fake")


def closed_model():
    return ModelConfig("closed", "loop_fake", "http://x", "m", 100_000, True, Pricing.free(), 0, False)


def test_a_public_job_runs_and_the_ledger_has_one_entry_per_model_call(provider):
    ledger = CostLedger()
    adapter = create_adapter(closed_model(), ledger=ledger, sensitivity=Sensitivity.PUBLIC)
    result = run_agent(adapter, FakeTools(), "task", limits=Limits(max_steps=5))
    assert result.status == FINISHED and len(ledger.calls) == len(result.steps) == 2


def test_a_private_job_with_a_closed_model_is_blocked_before_anything_is_sent(provider):
    ledger = CostLedger()
    adapter = create_adapter(closed_model(), ledger=ledger)  # the default sensitivity is private
    result = run_agent(adapter, FakeTools(), "task", limits=Limits(max_steps=5))
    assert result.status == PRIVACY_BLOCKED and result.error_code == "private_code_blocked"
    assert provider["raw"].calls == [] and ledger.calls == () and result.steps == ()


# -- rules about the code itself ------------------------------------------------------------------------------------------


def test_no_model_or_provider_name_is_hard_coded_in_the_agent():
    root = Path(__file__).resolve().parents[2] / "src" / "bugbite" / "agent"
    pattern = re.compile(r"claude|haiku|sonnet|opus|openai|groq|anthropic|gpt|ollama|gemini|llama", re.IGNORECASE)
    hits = [f"{p.name}:{n}: {line.strip()}" for p in root.rglob("*.py") for n, line in enumerate(p.read_text().splitlines(), 1) if pattern.search(line)]
    assert hits == []


def test_the_loop_never_touches_the_environment_or_logs_content():
    root = Path(__file__).resolve().parents[2] / "src" / "bugbite" / "agent"
    source = (root / "loop.py").read_text()
    assert "environ" not in source and "getenv" not in source
    assert all("%s" not in line or "type(exc).__name__" in line for line in source.splitlines() if "log." in line)


def test_max_steps_in_a_real_stuck_run(sb):
    tools = build_agent_tools(sb, test_runner=fake_runner)
    endless = [tool_call_response(("list_directory", {}), first_id=i) for i in range(1, 8)]
    result = run_agent(ScriptedAdapter(None, endless), tools, "task", limits=Limits(max_steps=4))
    assert result.status == MAX_STEPS and len(result.steps) == 4 and sum(1 for s in result.steps if s.tool_runs) == 3
