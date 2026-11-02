"""Record a run through the real adapters (mock HTTP), replay it, and expect an identical run."""

import pytest
from real_adapter_helpers import BOTH, SIDES, FakeTools, Limits, record_real, replay_real

from bugbite.agent import FINISHED  # noqa: E402

ECHO_CALL = ("echo", {"text": "hi"})
FINAL = '{"final": "All done."}'


def check(tmp_path, side, replies, **kw):
    s = SIDES[side]
    result, path, http = record_real(tmp_path, side, [r(s) if callable(r) else r for r in replies], **kw)
    replayed = replay_real(path)
    assert replayed.divergence is None, replayed.divergence
    assert not replayed.differences and replayed.identical
    assert (replayed.agent.status, replayed.agent.final_text, replayed.agent.cost_usd, replayed.agent.usage, replayed.agent.nudges) == (result.status, result.final_text, result.cost_usd, result.usage, result.nudges)
    return result, path, http, replayed


@pytest.mark.parametrize("side", BOTH)
def test_tool_call_then_answer(tmp_path, side):
    result, _, http, _ = check(tmp_path, side, [lambda s: s.tool_turn([ECHO_CALL], text="Looking."), lambda s: s.answer("Fixed.")])
    assert result.status == FINISHED and len(http.requests) == 2


@pytest.mark.parametrize("side", BOTH)
def test_text_only_answer(tmp_path, side):
    check(tmp_path, side, [lambda s: s.answer("Nothing to change.")])


@pytest.mark.parametrize("side", BOTH)
@pytest.mark.parametrize("status", [429, 500])
def test_provider_errors(tmp_path, side, status):
    result, _, _, _ = check(tmp_path, side, [lambda s: s.tool_turn([ECHO_CALL]), lambda s: s.http_error(status)])
    assert result.status != FINISHED


@pytest.mark.parametrize("side", BOTH)
def test_two_tool_calls_in_one_reply(tmp_path, side):
    tools = FakeTools()
    check(tmp_path, side, [lambda s: s.tool_turn([ECHO_CALL, ("echo", {"text": "again"})]), lambda s: s.answer()], tools=tools)
    assert [a["text"] for _, a in tools.executed] == ["hi", "again"]  # in the order the provider gave them


@pytest.mark.parametrize("side", BOTH)
def test_truncated_answer(tmp_path, side):
    check(tmp_path, side, [lambda s: s.truncated(), lambda s: s.answer()])


def test_openai_reply_without_a_usage_block(tmp_path):
    check(tmp_path, "openai", [lambda s: s.tool_turn([ECHO_CALL], usage=None), lambda s: s.answer(usage=None)])


@pytest.mark.parametrize("side", BOTH)
def test_a_model_without_native_tool_calling_uses_the_text_action_fallback(tmp_path, side):
    reply = '{"tool": "echo", "arguments": {"text": "hi"}}'
    result, path, http, replayed = check(tmp_path, side, [lambda s: s.answer(reply), lambda s: s.answer(FINAL)], native=False)
    assert result.status == FINISHED and len(http.requests) == 2


@pytest.mark.parametrize("side", BOTH)
def test_a_repair_call_replays_too(tmp_path, side):
    bad = "I will now call the tool echo with hi"
    good = '{"tool": "echo", "arguments": {"text": "hi"}}'
    check(tmp_path, side, [lambda s: s.answer(bad), lambda s: s.answer(good), lambda s: s.answer(FINAL)], native=False)


def test_claude_cache_tokens_cost_the_same_on_replay(tmp_path):
    result, path, _, replayed = check(
        tmp_path, "claude", [lambda s: s.tool_turn([ECHO_CALL], usage=(1000, 50), cache=(400, 0)), lambda s: s.answer(usage=(100, 20), cache=(0, 400))],
        limits=Limits(10, max_cost_usd="5"))
    assert result.cost_usd > 0 and replayed.agent.cost_usd == result.cost_usd


@pytest.mark.parametrize("side", BOTH)
def test_a_step_limit_ending_replays(tmp_path, side):
    check(tmp_path, side, [lambda s: s.tool_turn([("echo", {"text": str(i)})]) for i in range(3)], limits=Limits(3))
