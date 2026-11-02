"""The small pieces of the replayer, one by one."""

import copy
from decimal import Decimal
from pathlib import Path

import pytest
from rp_helpers import FakeTools, ToolOutput, load_recording, record, text_response, tool_call_response, USAGE

from bugbite.adapter import GenerationRequest, Message, TextBlock
from bugbite.adapter.codec import request_fingerprint, request_to_dict
from bugbite.adapter.types import ToolDefinition
from bugbite.config import load_models_config
from bugbite.errors import AdapterError
from bugbite.recorder.start import _plain
from bugbite.replayer import (
    EXTRA_MODEL_CALL, EXTRA_TOOL_CALL, PROVIDER_BUG, RECORDING_ENDED, REQUEST_MISMATCH, TOOL_MISMATCH, MemoryWriter, ReplayClock,
    ReplayDivergence, ReplayError, ReplayProvider, ReplayTools, first_difference, fingerprint_differences, model_from_manifest,
)
from bugbite.replayer.diff import at_path

ROOT = Path(__file__).resolve().parents[2]


# -- the clock ------------------------------------------------------------------------------------------------------------


def test_the_clock_starts_at_zero_and_only_moves_forward():
    clock = ReplayClock()
    assert clock.now() == 0 and clock() == 0
    clock.advance_to(2.5)
    assert clock() == 2.5
    clock.advance_to(1.0)  # an earlier recorded time never sets it back
    assert clock() == 2.5
    clock.advance_to(2.5)
    assert clock() == 2.5


def test_sleep_moves_the_clock_without_waiting():
    clock = ReplayClock()
    clock.sleep(30)
    clock.sleep(0)
    clock.advance_to(10)  # behind the sleep: ignored
    assert clock() == 30
    clock.advance_to(31.5)
    assert clock() == 31.5


@pytest.mark.parametrize("bad", [float("nan"), "5", None, True])
def test_the_clock_refuses_nonsense(bad):
    clock = ReplayClock()
    with pytest.raises(ValueError):
        clock.sleep(bad)
    with pytest.raises(ValueError):
        clock.advance_to(bad)
    assert clock() == 0


def test_the_clock_refuses_to_sleep_backwards():
    clock = ReplayClock()
    clock.advance_to(3)
    with pytest.raises(ValueError):
        clock.sleep(-1)
    assert clock() == 3


# -- rebuilding the model -----------------------------------------------------------------------------------------------------


def test_every_shipped_model_comes_back_exactly_from_its_manifest_copy():
    models = load_models_config(ROOT / "config" / "models.yaml")
    assert len(models) >= 3
    for name, model in models.items():
        assert model_from_manifest(_plain(model)) == model, name


def test_the_long_prompt_price_tier_survives_the_round_trip():
    models = load_models_config(ROOT / "config" / "models.yaml")
    with_tier = [m for m in models.values() if m.pricing.long_prompt is not None]
    assert with_tier, "a shipped model with a long-prompt tier is needed for this test"
    for model in with_tier:
        back = model_from_manifest(_plain(model))
        assert back.pricing.long_prompt == model.pricing.long_prompt and isinstance(back.pricing.long_prompt.input, Decimal)
        assert back.pricing.input == model.pricing.input and back.pricing.as_of == model.pricing.as_of


def test_a_hand_made_model_with_odd_prices_comes_back_exactly():
    from bugbite.config import ModelConfig, Pricing

    model = ModelConfig("m", "p", "http://x", "mm", 1000, False, Pricing.of("0.1", "0.30000000000000004", long_prompt=(5, 1, 2, 3, 4), as_of="2026-01-02", source="s"),
                        0.25, True, "KEY", 77, "off")
    assert model_from_manifest(_plain(model)) == model


@pytest.mark.parametrize("damage", [
    lambda m: m.pop("pricing"), lambda m: m.update(extra=1), lambda m: m["pricing"].update(input="cheap"),
    lambda m: m["pricing"].update(input=1.5), lambda m: m["pricing"].pop("source"), lambda m: m["pricing"].update(long_prompt={"over_tokens": 1}),
    lambda m: m.update(context_window="big"), lambda m: m.update(prompt_caching="sometimes"),
])
def test_a_malformed_model_in_the_manifest_is_refused(damage):
    models = load_models_config(ROOT / "config" / "models.yaml")
    data = copy.deepcopy(_plain(next(iter(models.values()))))
    damage(data)
    with pytest.raises(ReplayError):
        model_from_manifest(data)
    with pytest.raises(ReplayError):
        model_from_manifest("not a model")


# -- the diff helpers ---------------------------------------------------------------------------------------------------------


def test_fingerprint_differences_names_each_field():
    base = request_fingerprint(GenerationRequest(messages=(Message.user("hi"),), system=(TextBlock("s"),)))
    assert fingerprint_differences(base, dict(base)) == []
    for field, value in [("sha256", "0" * 64), ("bytes", 1), ("messages", 9), ("system_blocks", 9), ("tools", 9), ("max_output_tokens", 5),
                         ("temperature", 0.5), ("stop_sequences", ["x"])]:
        assert fingerprint_differences(base, {**base, field: value}) == [field]
    assert fingerprint_differences(base, {**base, "full": {"anything": 1}}) == []  # the full copy is not a fingerprint field
    assert fingerprint_differences(base, {**base, "bytes": 1, "tools": 2}) == ["bytes", "tools"]


def test_first_difference_gives_a_path_into_nested_requests():
    def request(text="a", tool_desc="d", system="s"):
        return request_to_dict(GenerationRequest(
            messages=(Message.user(text),), system=(TextBlock(system),), tools=(ToolDefinition("t", tool_desc, {"type": "object", "properties": {}}),)))

    assert first_difference(request(), request()) is None
    assert first_difference(request(text="b"), request()) == "messages[0].blocks[0].text"
    assert first_difference(request(system="x"), request()) == "system[0].text"
    assert first_difference(request(tool_desc="e"), request()) == "tools[0].description"


def test_first_difference_handles_lengths_keys_and_types():
    assert first_difference([1, 2], [1, 2, 3]) == "[2]"
    assert first_difference({"a": 1}, {"a": 1, "b": 2}) == "b"
    assert first_difference({"a": {"b": [1, {"c": 1}]}}, {"a": {"b": [1, {"c": 2}]}}) == "a.b[1].c"
    assert first_difference(1, True) == "(root)" and first_difference(1, 1.0) == "(root)"  # a different type is a difference
    assert first_difference("a", "b", "x.y") == "x.y"
    assert first_difference({"b": 1, "a": 1}, {"a": 2, "b": 2}) == "a"  # keys are visited in order, so the answer does not depend on dict order


def test_at_path_reads_back_what_first_difference_points_at():
    data = {"messages": [{"blocks": [{"content": "x"}]}], "tools": []}
    assert at_path(data, "messages[0].blocks[0].content") == "x"
    assert at_path(data, "messages[3].blocks") == "(missing)" and at_path(data, "nope") == "(missing)"


# -- the provider -------------------------------------------------------------------------------------------------------------


def calls_of(tmp_path, provider, script, **kw):
    _, path = record(tmp_path, provider, script, **kw)
    return load_recording(path)


def first_request():
    """The request the loop builds first in `record(...)` runs: the default system prompt, the test tools and the task text."""
    from bugbite.agent import SYSTEM_PROMPT

    return GenerationRequest(messages=(Message.user("fix it"),), system=(TextBlock(SYSTEM_PROMPT),), tools=FakeTools().definitions())


def make_provider(rec, **kw):
    clock = kw.pop("clock", ReplayClock())
    return ReplayProvider(model_from_manifest(rec.manifest["model"]), rec.model_calls(), clock, **kw), clock


def test_the_provider_serves_answers_in_order_and_moves_the_clock(tmp_path, provider):
    rec = calls_of(tmp_path, provider, [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)])
    served, clock = make_provider(rec)
    first = rec.model_calls()[0]
    request = first_request()  # the recorded run's first request is the system prompt plus the task
    assert request_fingerprint(request) == first.request
    response = served.generate(request)
    assert response == first.response and clock() == first.t and served.served == 1 and served.unused == 1


def test_a_changed_request_stops_the_provider_and_names_the_fields(tmp_path, provider):
    rec = calls_of(tmp_path, provider, [text_response("done", **USAGE)])
    served, clock = make_provider(rec)
    with pytest.raises(ReplayDivergence) as caught:
        served.generate(GenerationRequest(messages=(Message.user("another task"),)))
    d = caught.value
    assert d.kind == REQUEST_MISMATCH and d.call == 1 and "sha256" in d.fields and d.path is None and "call 1" in d.message
    assert served.served == 0 and clock() == 0  # nothing was served and the clock did not move
    assert isinstance(d, BaseException) and not isinstance(d, Exception)  # `except Exception` in the code under replay cannot swallow it


def test_the_provider_reports_a_recorded_error_as_the_same_adapter_error(tmp_path, provider):
    rec = calls_of(tmp_path, provider, [AdapterError("rate_limited", "slow down", retry_after_s=3, status_code=429)])
    served, _ = make_provider(rec)
    request = first_request()
    with pytest.raises(AdapterError) as caught:
        served.generate(request)
    e = caught.value
    assert (e.code, e.message, e.retry_after_s, e.status_code) == ("rate_limited", "slow down", 3, 429)
    assert served.served == 1


def test_the_provider_runs_out_of_answers(tmp_path, provider):
    rec = calls_of(tmp_path, provider, [AdapterError("server_error", "x", status_code=500)])
    request = first_request()
    served, _ = make_provider(rec)
    with pytest.raises(AdapterError):
        served.generate(request)
    with pytest.raises(ReplayDivergence) as caught:
        served.generate(request)
    assert caught.value.kind == EXTRA_MODEL_CALL and caught.value.call == 2
    partial, _ = make_provider(rec, complete=False)
    with pytest.raises(AdapterError):
        partial.generate(request)
    with pytest.raises(ReplayDivergence) as caught:
        partial.generate(request)
    assert caught.value.kind == RECORDING_ENDED


# -- the tools ----------------------------------------------------------------------------------------------------------------


def tool_event(name="echo", arguments=None, text="out", is_error=False, executed=True, t=1.0):
    return {"type": "tool_call", "t": t, "executed": executed, "duration_s": 0.1,
            "call": {"id": "c", "name": name, "arguments": {"text": "a"} if arguments is None else arguments}, "output": {"text": text, "is_error": is_error}}


def test_tools_serve_the_executed_calls_in_order_and_move_the_clock():
    clock = ReplayClock()
    tools = ReplayTools(FakeTools().definitions(), [tool_event(text="one", t=2.0), tool_event(executed=False, text="skipped", t=3.0), tool_event(text="two", is_error=True, t=4.0)], clock)
    assert tools.definitions() == FakeTools().definitions()
    assert tools.execute("echo", {"text": "a"}, time_limit_s=5) == ToolOutput("one") and clock() == 2.0
    assert tools.unused == 1
    assert tools.execute("echo", {"text": "a"}) == ToolOutput("two", True) and clock() == 4.0  # the not-executed entry was not counted
    assert tools.unused == 0


def test_argument_order_does_not_matter_but_values_do():
    tools = ReplayTools((), [tool_event(arguments={"a": 1, "b": [1, 2]}), tool_event(arguments={"a": 1})], ReplayClock())
    assert tools.execute("echo", {"b": [1, 2], "a": 1}) == ToolOutput("out")
    with pytest.raises(ReplayDivergence) as caught:
        tools.execute("echo", {"a": 2})
    assert caught.value.kind == TOOL_MISMATCH and caught.value.call == 2 and caught.value.fields == ("arguments",)
    assert tools.served == 1  # a mismatch serves nothing


def test_a_different_tool_name_is_a_mismatch_on_the_name():
    tools = ReplayTools((), [tool_event()], ReplayClock())
    with pytest.raises(ReplayDivergence) as caught:
        tools.execute("boom", {"text": "a"})
    assert caught.value.kind == TOOL_MISMATCH and caught.value.fields == ("name",)


def test_tools_run_out():
    tools = ReplayTools((), [], ReplayClock())
    with pytest.raises(ReplayDivergence) as caught:
        tools.execute("echo", {})
    assert caught.value.kind == EXTRA_TOOL_CALL and caught.value.call == 1
    with pytest.raises(ReplayDivergence) as caught:
        ReplayTools((), [], ReplayClock(), complete=False).execute("echo", {})
    assert caught.value.kind == RECORDING_ENDED


def test_arguments_that_json_cannot_hold_are_a_mismatch_not_a_crash():
    tools = ReplayTools((), [tool_event()], ReplayClock())
    with pytest.raises(ReplayDivergence) as caught:
        tools.execute("echo", {"text": float("nan")})
    assert caught.value.kind == TOOL_MISMATCH


# -- the in-memory writer -----------------------------------------------------------------------------------------------------


def test_the_memory_writer_numbers_events_stamps_them_and_makes_them_plain_data():
    clock = ReplayClock()
    writer = MemoryWriter(clock, record_requests=True)
    assert writer.record_requests is True
    assert (writer.next_call_number(), writer.next_call_number()) == (1, 2)
    assert writer.take_unassigned_calls() == [1, 2] and writer.take_unassigned_calls() == []
    clock.advance_to(1.23456789)
    assert writer.write({"type": "step", "step": 1, "tuple": (1, 2)}) is True
    assert writer.events == [{"seq": 1, "t": 1.234568, "type": "step", "step": 1, "tuple": [1, 2]}]  # JSON-plain, like a recording read back
    writer.note_error(KeyError("x"))
    writer.finish({"status": "finished"}, status="complete")
    assert writer.errors == 1 and writer.last_error == "KeyError" and writer.outcome == {"status": "finished"}


def test_excerpts_show_where_two_long_strings_differ():
    from bugbite.replayer.diff import excerpts

    long = "x" * 200
    before, now = excerpts(long + " end", long + " end. Be brief.")
    assert "Be brief" in now and "Be brief" not in before and before.startswith("'...") and len(now) < 100
    assert excerpts("short", "other") == ("'short'", "'other'")
    assert excerpts(1, [2]) == ("1", "[2]")
