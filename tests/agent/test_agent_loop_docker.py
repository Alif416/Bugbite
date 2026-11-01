"""The loop driving the real tools in a real sandbox (the model is scripted; only Docker is needed)."""

import pytest

from bugbite.adapter.testing import ScriptedAdapter, text_response, tool_call_response
from bugbite.agent import FINISHED, Limits, run_agent
from bugbite.agent.tools import build_agent_tools
from bugbite.config import SandboxConfig
from bugbite.sandbox import Sandbox, list_sandbox_containers

pytestmark = pytest.mark.docker

_SEED = """
import os, subprocess
root = "/workspace/origin"
os.makedirs(root + "/tests")
open(root + "/app.py", "w").write("def add(a, b):\\n    return a - b\\n")
open(root + "/tests/test_app.py", "w").write("from app import add\\n\\ndef test_add():\\n    assert add(1, 2) == 3\\n")
def git(*a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=root, check=True, capture_output=True)
git("init", "-b", "main"); git("add", "-A"); git("commit", "-m", "init")
"""


def test_a_scripted_model_edits_a_file_and_checks_it_in_a_real_sandbox():
    before = set(list_sandbox_containers())
    config = SandboxConfig(max_lifetime_s=600, setup_timeout_s=120, workspace_mb=256, command_timeout_s=30)
    with Sandbox(config, network=True, job_id="tests-loop") as sb:
        assert sb.run(["python", "-c", _SEED]).exit_code == 0
        sb.disconnect_network()
        assert sb.run("git clone -q /workspace/origin /workspace/repo").exit_code == 0
        tools = build_agent_tools(sb)
        model = ScriptedAdapter(None, [
            tool_call_response(("list_directory", {}), ("read_file", {"path": "app.py"})),
            tool_call_response(("run_command", {"command": "python -c 'from app import add; print(add(1, 2))'"}), first_id=3),
            tool_call_response(("edit_file", {"path": "app.py", "old_text": "a - b", "new_text": "a + b"}), first_id=4),
            tool_call_response(("run_command", {"command": "python -c 'from app import add; print(add(1, 2))'"}), first_id=5),
            text_response("Fixed: add used minus. Checked add(1, 2) prints 3."),
        ])
        result = run_agent(model, tools, "add(1, 2) returns -1", limits=Limits(max_steps=8))
        assert result.status == FINISHED, (result.status, result.error_message)
        outputs = [r.output.text for s in result.steps for r in s.tool_runs]
        assert outputs[0].splitlines()[:2] == ["tests/", "app.py"] and "     2|     return a - b" in outputs[1]
        assert outputs[2] == "exit code 0\n-1" and outputs[4] == "exit code 0\n3"
        diff = sb.run("git diff", workdir="/workspace/repo").stdout
        assert "-    return a - b" in diff and "+    return a + b" in diff and diff.count("\n@@") == 1
        assert sb.run("git status --porcelain", workdir="/workspace/repo").stdout.strip() == "M app.py"
    assert set(list_sandbox_containers()) <= before


def test_a_real_sleeping_command_is_stopped_by_the_wall_clock_limit():
    import time

    before = set(list_sandbox_containers())
    config = SandboxConfig(max_lifetime_s=600, setup_timeout_s=120, workspace_mb=256, command_timeout_s=60)

    def slow_step(response):
        def step(request):
            time.sleep(0.3)  # a model call takes a little time
            return response
        return step

    with Sandbox(config, network=True, job_id="tests-loop-time") as sb:
        assert sb.run(["python", "-c", _SEED]).exit_code == 0
        sb.disconnect_network()
        assert sb.run("git clone -q /workspace/origin /workspace/repo").exit_code == 0
        tools = build_agent_tools(sb)
        sleepers = [tool_call_response(("run_command", {"command": "sleep 60"}), first_id=i) for i in range(1, 41)]
        model = ScriptedAdapter(None, [slow_step(r) for r in sleepers])
        started = time.monotonic()
        result = run_agent(model, tools, "task", limits=Limits(40, max_wall_clock_s=6))
        took = time.monotonic() - started
        assert result.status == "time_cap", (result.status, result.limit_detail)
        first = result.steps[0].tool_runs[0].output.text
        assert first.startswith("timed out after ") and "sleep" not in first  # stopped at the time left, not after 60 s
        assert took < 12, took  # the cap was 6 s; the sleeper did not run for its full minute
        assert "time limit of 6 s was reached" in result.limit_detail
    assert set(list_sandbox_containers()) <= before
