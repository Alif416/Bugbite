"""Loop detection inside the loop."""

import pytest
from loop_helpers import Clock, FakeTools, adapter, assert_conversation_valid, text_response, tool_call_response
from tool_helpers import LocalSandbox

from bugbite.adapter import Usage
from bugbite.adapter.testing import ScriptedAdapter
from bugbite.adapter.types import ToolCallBlock, ToolResultBlock
from bugbite.agent import FINISHED, LOOP_DETECTED, TIME_CAP, Limits, LoopPolicy, run_agent
from bugbite.agent.loop import NOTE_PREFIX
from bugbite.agent.tools import ToolOutput, build_agent_tools

TASK = "fix it"
NOT_FOUND = ToolOutput("old_text was not found in a.py. It must match exactly.", True)


def echo(i, text="a"):
    return tool_call_response(("echo", {"text": text}), first_id=i)


def edit_call(i, path="a.py", old=None):
    return tool_call_response(("edit_file", {"path": path, "old_text": old or f"guess {i}", "new_text": "fixed"}), first_id=i)


def go(script, tools=None, steps=30, **kw):
    ad = adapter(*script)
    tools = tools or FakeTools()
    return run_agent(ad, tools, TASK, limits=Limits(steps), **kw), ad, tools


def result_text(ad, call_index):
    """The tool-result text the model was shown just before model call number `call_index` (0-based)."""
    return ad.calls[call_index].messages[-1].blocks[-1].content


# -- rule 1 in the loop ----------------------------------------------------------------------------------------------------


def test_a_repeated_call_is_nudged_once_and_then_stopped():
    script = [echo(i) for i in range(1, 8)]
    result, ad, tools = go(script)
    assert result.status == LOOP_DETECTED and len(result.steps) == 5 and len(ad.calls) == 5 and len(tools.executed) == 5
    assert result.nudges == 1
    assert [s.nudge is not None for s in result.steps] == [False, False, True, False, False]
    assert result.limit_detail == "Stopped: the same echo call returned the same result 5 times with no change to the repository."
    shown = result_text(ad, 3)  # what the model read after its 3rd call
    assert shown.startswith("echo: a\n\n" + NOTE_PREFIX + "You have now made the same echo call 3 times")
    assert result_text(ad, 2) == "echo: a" and result_text(ad, 4) == "echo: a"  # no note before or after
    assert_conversation_valid(result)
    assert result.messages[-1].role == "user"  # the last step's results are in the conversation


def test_the_recorded_tool_run_keeps_the_original_output():
    result, ad, _ = go([echo(i) for i in range(1, 8)])
    third = result.steps[2]
    assert third.tool_runs[0].output.text == "echo: a" and third.nudge in result_text(ad, 3)
    assert NOTE_PREFIX not in third.tool_runs[0].output.text


def test_a_model_that_changes_course_after_the_nudge_carries_on():
    script = [echo(1), echo(2), echo(3), echo(4, text="something else"), text_response("Done.")]
    result, ad, _ = go(script)
    assert result.status == FINISHED and result.nudges == 1 and len(ad.calls) == 5


def test_a_nudge_costs_no_extra_model_call():
    script = [echo(1), echo(2), echo(3), text_response("done")]
    result, ad, _ = go(script)
    assert len(ad.calls) == 4 == len(result.steps) and result.nudges == 1


def test_no_nudge_or_stop_when_the_policy_is_none():
    script = [echo(i) for i in range(1, 11)] + [text_response("done")]
    result, ad, _ = go(script, loop_policy=None)
    assert result.status == FINISHED and result.nudges == 0 and all(s.nudge is None for s in result.steps)
    assert all(NOTE_PREFIX not in r.content for call in ad.calls for m in call.messages for r in m.blocks if isinstance(r, ToolResultBlock))


def test_a_custom_policy_is_used():
    result, _, _ = go([echo(i) for i in range(1, 5)], loop_policy=LoopPolicy(repeat_nudge=2, repeat_stop=3))
    assert result.status == LOOP_DETECTED and len(result.steps) == 3 and result.nudges == 1


@pytest.mark.parametrize("bad", ["yes", 5, {}])
def test_the_policy_must_be_a_loop_policy_or_none(bad):
    ad = adapter(text_response("x"))
    with pytest.raises(ValueError, match="loop_policy"):
        run_agent(ad, FakeTools(), TASK, limits=Limits(3), loop_policy=bad)
    assert ad.calls == []


def test_several_calls_in_one_reply_get_one_note_on_the_last_result():
    reply = tool_call_response(("echo", {"text": "a"}), ("echo", {"text": "b"}), ("echo", {"text": "c"}), first_id=3)
    result, ad, _ = go([echo(1), echo(2), reply, text_response("done")])
    blocks = ad.calls[3].messages[-1].blocks
    assert [b.content for b in blocks[:2]] == ["echo: a", "echo: b"]
    assert blocks[2].content.startswith("echo: c\n\n" + NOTE_PREFIX) and result.nudges == 1
    assert result.steps[2].nudge in blocks[2].content


def test_the_note_never_repeats_arguments_or_output():
    script = [echo(i, text="TOPSECRET-ARGUMENT") for i in range(1, 6)]
    result, ad, _ = go(script)
    assert "TOPSECRET" not in result.steps[2].nudge and "TOPSECRET" not in result.limit_detail


def test_invalid_actions_are_not_counted_as_repeated_calls():
    bad = lambda i: tool_call_response(ToolCallBlock(f"ta_{i}", "invalid_action", {}, "The reply was not a valid action: broken"), first_id=i)
    result, _, tools = go([bad(i) for i in range(1, 9)] + [text_response("gave up")])
    assert result.status == FINISHED and result.nudges == 0 and tools.executed == []


def test_an_unknown_tool_repeated_is_a_loop_and_its_name_is_made_safe():
    weird = lambda i: tool_call_response(ToolCallBlock(f"c{i}", "no\nsuch tool", {}), first_id=i)
    tools = FakeTools(outputs={"no\nsuch tool": ToolOutput("Unknown tool", True)})
    result, _, _ = go([weird(i) for i in range(1, 7)], tools=tools)
    assert result.status == LOOP_DETECTED and "\n" not in result.limit_detail and "\n" not in result.steps[2].nudge


# -- rule 2 in the loop ----------------------------------------------------------------------------------------------------


def test_failed_edits_to_one_file_are_nudged_then_stopped_even_with_different_text():
    tools = FakeTools(outputs={"edit_file": NOT_FOUND})
    result, ad, _ = go([edit_call(i) for i in range(1, 9)], tools=tools)
    assert result.status == LOOP_DETECTED and len(result.steps) == 6 and result.nudges == 1
    assert [s.nudge is not None for s in result.steps] == [False, False, False, True, False, False]
    assert result_text(ad, 4).endswith(result.steps[3].nudge) and "4 attempts to edit a.py have failed" in result.steps[3].nudge
    assert result.limit_detail == "Stopped: 6 edits to a.py failed with no successful edit in between."
    assert_conversation_valid(result)


def test_edits_to_different_files_are_not_a_loop():
    tools = FakeTools(outputs={"edit_file": NOT_FOUND})
    script = [edit_call(i, path=f"f{i}.py") for i in range(1, 9)] + [text_response("done")]
    result, _, _ = go(script, tools=tools)
    assert result.status == FINISHED and result.nudges == 0


def test_edit_run_tests_same_failure_edit_again_is_not_a_loop():
    class Tools(FakeTools):
        def execute(self, name, arguments, *, time_limit_s=None):
            self.executed.append((name, dict(arguments)))
            if name == "run_tests":
                return ToolOutput("Ran 1 tests: 1 failed.\nFAILED t::a: assert 0")
            return ToolOutput("Edited a.py: replaced 1 occurrence.")

    script, i = [], 1
    for n in range(8):
        script.append(tool_call_response(("edit_file", {"path": "a.py", "old_text": f"v{n}", "new_text": f"v{n + 1}"}), first_id=i))
        script.append(tool_call_response(("run_tests", {}), first_id=i + 1))
        i += 2
    result, _, _ = go(script + [text_response("could not fix it")], tools=Tools())
    assert result.status == FINISHED and result.nudges == 0 and len(result.steps) == 17


def test_a_successful_edit_in_the_same_reply_cancels_a_stop_from_earlier_in_that_reply():
    class Tools(FakeTools):
        def execute(self, name, arguments, *, time_limit_s=None):
            if name == "edit_file":
                return ToolOutput("Edited a.py: replaced 1 occurrence.")
            return super().execute(name, arguments, time_limit_s=time_limit_s)

    reply = tool_call_response(("echo", {"text": "a"}), ("edit_file", {"path": "a.py", "old_text": "x", "new_text": "y"}), first_id=5)
    result, _, _ = go([echo(1), echo(2), echo(3), echo(4), reply, text_response("done")], tools=Tools())
    assert result.status == FINISHED  # the 5th identical call came in the same reply as a real edit


# -- ordering with the other limits --------------------------------------------------------------------------------------------


def test_time_wins_over_a_loop_stop():
    clock = Clock()

    class SlowTools(FakeTools):
        def execute(self, name, arguments, *, time_limit_s=None):
            if len(self.executed) == 4:
                clock.advance(1000)  # the fifth call takes the rest of the time
            return super().execute(name, arguments, time_limit_s=time_limit_s)

    tools = SlowTools()
    ad = adapter(*[echo(i) for i in range(1, 8)])
    result = run_agent(ad, tools, TASK, limits=Limits(30, max_wall_clock_s=500), clock=clock)
    assert result.status == TIME_CAP and len(result.steps) == 5
    assert_conversation_valid(result)


def test_a_loop_stop_beats_the_step_limit_only_when_tools_ran():
    result, _, _ = go([echo(i) for i in range(1, 8)], steps=5)
    assert result.status == "max_steps"  # the fifth reply is the last step, so its tools never run
    result, _, _ = go([echo(i) for i in range(1, 8)], steps=6)
    assert result.status == LOOP_DETECTED


def test_the_observer_still_sees_every_event_around_a_stop():
    events = []
    result, _, _ = go([echo(i) for i in range(1, 8)], observer=events.append)
    names = [type(e).__name__ for e in events]
    assert names.count("ToolCallEvent") == 5 and names[-1] == "FinishEvent" and events[-1].result.status == LOOP_DETECTED


# -- with the real tools -------------------------------------------------------------------------------------------------------------


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    box = LocalSandbox(root)
    box.write("a.py", "def add(a, b):\n    return a - b\n")
    box.write("tests/test_a.py", "assert True\n")
    return box


def test_a_model_that_obeys_the_nudge_reads_the_file_and_fixes_it(sb):
    tools = build_agent_tools(sb, test_runner=lambda *a, **k: None)
    wrong = lambda i: tool_call_response(("edit_file", {"path": "a.py", "old_text": f"return a minus b {i}", "new_text": "return a + b"}), first_id=i)
    script = [wrong(1), wrong(2), wrong(3), wrong(4),                                    # the 4th failure triggers the nudge
              tool_call_response(("read_file", {"path": "a.py"}), first_id=5),
              tool_call_response(("edit_file", {"path": "a.py", "old_text": "return a - b", "new_text": "return a + b"}), first_id=6),
              text_response("Fixed the sign.")]
    ad = ScriptedAdapter(None, script)
    result = run_agent(ad, tools, TASK, limits=Limits(20))
    assert result.status == FINISHED and result.nudges == 1
    assert "have failed since your last successful edit" in result_text(ad, 4)
    assert (sb.root / "a.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_a_model_that_ignores_the_nudge_is_stopped_and_the_file_is_untouched(sb):
    tools = build_agent_tools(sb, test_runner=lambda *a, **k: None)
    wrong = lambda i: tool_call_response(("edit_file", {"path": "a.py", "old_text": f"never there {i}", "new_text": "x"}), first_id=i)
    result = run_agent(ScriptedAdapter(None, [wrong(i) for i in range(1, 10)]), tools, TASK, limits=Limits(20))
    assert result.status == LOOP_DETECTED and len(result.steps) == 6
    assert (sb.root / "a.py").read_text() == "def add(a, b):\n    return a - b\n"
    assert all("was not found" in r.output.text for s in result.steps for r in s.tool_runs)


def test_repeated_attempts_to_edit_a_protected_test_are_a_loop(sb):
    tools = build_agent_tools(sb, test_runner=lambda *a, **k: None)
    attempt = lambda i: tool_call_response(("edit_file", {"path": "tests/test_a.py", "old_text": "True", "new_text": f"False{i}"}), first_id=i)
    result = run_agent(ScriptedAdapter(None, [attempt(i) for i in range(1, 10)]), tools, TASK, limits=Limits(20))
    assert result.status == LOOP_DETECTED and "tests/test_a.py" in result.limit_detail
    assert "not allowed to change" in result.steps[0].tool_runs[0].output.text and "protected" in result.steps[3].nudge
    assert "assert True" in (sb.root / "tests/test_a.py").read_text()
