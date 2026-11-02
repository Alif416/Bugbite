"""What replay does when the code or the recording is not what it was (README FR10.3: regression detection)."""

import copy

import pytest
from rp_helpers import (
    USAGE, AdapterError, FakeTools, Limits, Sensitivity, edited_copy, make_partial, record, replay_it, text_response, tool_call_response,
)

from bugbite.adapter.types import ToolDefinition
from bugbite.agent import SYSTEM_PROMPT, LoopPolicy
from bugbite.recorder import RecordingError
from bugbite.replayer import (
    EXTRA_MODEL_CALL, EXTRA_TOOL_CALL, PROVIDER_BUG, RECORDING_ENDED, REQUEST_MISMATCH, TOOL_MISMATCH, ReplayError, replay,
)


@pytest.fixture
def two_steps(tmp_path, provider):
    script = [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)]
    recorded, path = record(tmp_path, provider, script, record_requests=True)
    return path, tmp_path


def test_a_different_system_prompt_stops_at_the_first_call_with_a_path(two_steps):
    path, _ = two_steps
    result = replay_it(path, system_prompt=SYSTEM_PROMPT + " Be brief.")
    d = result.divergence
    assert not result.identical and result.agent is None and result.differences == ()
    assert d.kind == REQUEST_MISMATCH and d.call == 1 and "sha256" in d.fields and d.path == "system[0].text"
    assert "call 1" in d.message and "system[0].text" in d.message and "Be brief" in d.message
    assert any("system prompt is not the one the recording used" in n for n in result.notes)


def test_a_changed_tool_description_is_found(two_steps):
    path, _ = two_steps
    echo, boom = FakeTools().definitions()
    result = replay_it(path, tool_definitions=(ToolDefinition(echo.name, echo.description + " Faster now.", echo.parameters), boom))
    assert result.divergence.kind == REQUEST_MISMATCH and result.divergence.path == "tools[0].description" and "tools" not in result.divergence.fields[:0]


def test_a_changed_tool_schema_is_found(two_steps):
    path, _ = two_steps
    echo, boom = FakeTools().definitions()
    schema = copy.deepcopy(echo.parameters)
    schema["properties"]["text"] = {"type": "integer"}
    result = replay_it(path, tool_definitions=(ToolDefinition(echo.name, echo.description, schema), boom))
    assert result.divergence.path == "tools[0].parameters.properties.text.type"


def test_a_removed_tool_changes_the_tool_count(two_steps):
    path, _ = two_steps
    result = replay_it(path, tool_definitions=FakeTools().definitions()[:1])
    assert "tools" in result.divergence.fields and result.divergence.path == "tools[1]"


def test_without_full_requests_only_the_fingerprint_fields_are_named(tmp_path, provider):
    _, path = record(tmp_path, provider, [text_response("done", **USAGE)])
    result = replay_it(path, system_prompt="Another prompt.")
    d = result.divergence
    assert d.kind == REQUEST_MISMATCH and d.path is None and set(d.fields) >= {"sha256", "bytes"} and "system_blocks" not in d.fields


def test_a_changed_loop_policy_changes_a_later_request(tmp_path, provider):
    again = [tool_call_response(("echo", {"text": "again"}), first_id=i, **USAGE) for i in range(1, 5)]
    _, path = record(tmp_path, provider, again, record_requests=True, loop_policy=LoopPolicy(repeat_nudge=3, repeat_stop=4))
    result = replay_it(path, loop_policy=LoopPolicy(repeat_nudge=2, repeat_stop=4))
    d = result.divergence
    assert d.kind == REQUEST_MISMATCH and d.call == 3  # the nudge now appears one step earlier
    assert d.path == "messages[4].blocks[0].content" and "[Bugbite note]" in d.message


def test_a_changed_task_in_the_manifest_is_found(two_steps):
    path, tmp = two_steps
    other = edited_copy(path, tmp / "other", manifest_change=lambda m: m["task"].update(text="a different task"))
    result = replay_it(other)
    assert result.divergence.kind == REQUEST_MISMATCH and result.divergence.path == "messages[0].blocks[0].text"


def test_a_lower_limit_is_not_a_divergence_but_a_list_of_differences(two_steps):
    path, tmp = two_steps
    other = edited_copy(path, tmp / "other", manifest_change=lambda m: m["settings"]["limits"].update(max_steps=1))
    result = replay_it(other)
    assert result.divergence is None and not result.identical and result.agent.status == "max_steps"
    text = "\n".join(result.differences)
    assert "the replay produced a finish event here" in text and "recorded model call(s) were not used" in text


def test_a_run_that_ends_earlier_reports_what_was_left_over(tmp_path, provider):
    _, path = record(tmp_path, provider, [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)])
    result = replay_it(path, loop_policy=None)
    assert result.identical  # the same here; a real leftover needs a different outcome, below
    other = edited_copy(path, tmp_path / "other", manifest_change=lambda m: m["settings"]["limits"].update(max_wall_clock_s=0.000001))
    result = replay_it(other)
    assert result.divergence is None and result.agent.status == "time_cap" and any("not used" in d for d in result.differences)


def test_at_most_ten_differences_are_listed(tmp_path, provider):
    script = [tool_call_response(("echo", {"text": str(i)}), first_id=i, **USAGE) for i in range(1, 8)] + [text_response("done", **USAGE)]
    _, path = record(tmp_path, provider, script, limits=Limits(20))
    other = edited_copy(path, tmp_path / "other", manifest_change=lambda m: m["settings"]["limits"].update(max_steps=1))
    result = replay_it(other)
    assert len(result.differences) == 11 and result.differences[-1].startswith("... and ")


# -- damaged recordings: the recorded events themselves are what changed -------------------------------------------------------------


def test_a_changed_tool_call_in_the_recording_is_a_tool_mismatch(two_steps):
    path, tmp = two_steps

    def change(events):
        next(e for e in events if e["type"] == "tool_call")["call"]["arguments"] = {"text": "different"}

    result = replay_it(edited_copy(path, tmp / "other", change))
    d = result.divergence
    assert d.kind == TOOL_MISMATCH and d.call == 1 and d.fields == ("arguments",) and "different" in d.message and result.agent is None


def test_a_missing_tool_call_is_an_extra_tool_call(two_steps):
    path, tmp = two_steps
    result = replay_it(edited_copy(path, tmp / "other", lambda events: [e for e in events if e["type"] != "tool_call"]))
    assert result.divergence.kind == EXTRA_TOOL_CALL and result.divergence.call == 1


def test_a_missing_model_call_is_an_extra_model_call(two_steps):
    path, tmp = two_steps

    def change(events):
        last = max(i for i, e in enumerate(events) if e["type"] == "model_call")
        return events[:last] + events[last + 1:]

    result = replay_it(edited_copy(path, tmp / "other", change))
    assert result.divergence.kind == EXTRA_MODEL_CALL and result.divergence.call == 2


def test_a_recorded_provider_bug_is_reported_not_replayed(two_steps):
    path, tmp = two_steps

    def change(events):
        call = next(e for e in events if e["type"] == "model_call")
        del call["response"]
        call["exception"] = "KeyError"

    result = replay_it(edited_copy(path, tmp / "other", change))
    assert result.divergence.kind == PROVIDER_BUG and "KeyError" in result.divergence.message


def test_a_changed_recorded_output_changes_the_next_request(two_steps):
    path, tmp = two_steps

    def change(events):
        next(e for e in events if e["type"] == "tool_call")["output"]["text"] = "something else"

    result = replay_it(edited_copy(path, tmp / "other", change))
    assert result.divergence.kind == REQUEST_MISMATCH and result.divergence.call == 2 and result.divergence.path == "messages[2].blocks[0].content"


def test_a_changed_final_event_is_listed_as_a_difference(two_steps):
    path, tmp = two_steps

    def change(events):
        events[-1]["final_text"] = "a different ending"

    result = replay_it(edited_copy(path, tmp / "other", change))
    assert result.divergence is None and not result.identical
    assert result.differences == ("event 6 (finish): final_text differs: recorded 'a different ending', replayed 'done'",)


# -- recordings that cannot be replayed -------------------------------------------------------------------------------------------


def test_a_partial_recording_is_refused_unless_allowed(two_steps):
    path, tmp = two_steps
    partial = make_partial(path, tmp / "partial", 3)  # model_call, step, tool_call
    with pytest.raises(ReplayError, match="not complete"):
        replay_it(partial)
    result = replay_it(partial, allow_partial=True)
    assert result.divergence.kind == RECORDING_ENDED and result.divergence.call == 2 and not result.identical
    assert any("incomplete" in n for n in result.notes)


def test_a_damaged_recording_raises_the_readers_error(two_steps):
    path, tmp = two_steps
    other = edited_copy(path, tmp / "other")
    (other / "events.jsonl").write_text((other / "events.jsonl").read_text().replace("done", "dune"))
    with pytest.raises(RecordingError):
        replay_it(other)
    with pytest.raises(RecordingError):
        replay_it(tmp / "nothing-here")


def test_a_retry_policy_in_the_manifest_is_refused(tmp_path, provider):
    _, path = record(tmp_path, provider, [text_response("done", **USAGE)], info_kw={"retry_policy": {"max_attempts": 4}})
    with pytest.raises(ReplayError, match="retry"):
        replay_it(path)


@pytest.mark.parametrize("damage, match", [
    (lambda m: m["settings"].update(limits=None), "limits"),
    (lambda m: m["settings"].update(limits={"max_steps": 0}), "settings"),
    (lambda m: m["settings"].update(loop_policy={"repeat_nudge": 1}), "settings"),
    (lambda m: m["source"].update(sensitivity="secret"), "sensitivity"),
    (lambda m: m["task"].update(text=" "), "task"),
    (lambda m: m.pop("settings"), "settings"),
    (lambda m: m["model"].update(provider=""), "model"),
])
def test_an_unusable_manifest_is_refused(two_steps, damage, match):
    path, tmp = two_steps
    with pytest.raises(ReplayError, match=match):
        replay_it(edited_copy(path, tmp / "other", manifest_change=damage))


def test_version_differences_are_noted_before_anything_is_compared(two_steps):
    path, tmp = two_steps

    def change(m):
        m["prompt"].update(version="0", tools_version="0")

    result = replay_it(edited_copy(path, tmp / "other", manifest_change=change))
    assert result.identical and len(result.notes) == 2
    assert "prompt version '0'" in result.notes[0] and "tools version '0'" in result.notes[1]


def test_the_sensitivity_in_the_manifest_decides_what_the_guard_does(tmp_path, provider):
    _, path = record(tmp_path, provider, [], allow=False, sensitivity=Sensitivity.PRIVATE)
    public = edited_copy(path, tmp_path / "public", manifest_change=lambda m: m["source"].update(sensitivity="public"))
    result = replay_it(public)
    assert result.divergence.kind == EXTRA_MODEL_CALL  # the guard let the call through, and the recording has none


def test_replay_needs_no_tool_definitions_argument_to_use_the_real_ones(tmp_path, provider):
    _, path = record(tmp_path, provider, [text_response("done", **USAGE)])
    result = replay(path)  # the real tool set differs from the test tools, so the first request differs
    assert result.divergence.kind == REQUEST_MISMATCH and "tools" in result.divergence.fields
