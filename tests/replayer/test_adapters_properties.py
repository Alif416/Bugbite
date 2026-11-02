"""What is special about replay through the real adapters: parity, secrets, differences, cache markers."""

import json

import pytest
from real_adapter_helpers import BOTH, SIDES, FakeTools, Limits, record_real, replay_real, start_recording
from rec_helpers import FIXED_ENV

from bugbite.adapter import CostLedger, GenerationRequest, Message, create_adapter
from bugbite.adapter.types import ToolDefinition
from bugbite.agent import DEFAULT_LOOP_POLICY
from bugbite.replayer.errors import REQUEST_MISMATCH

ECHO_CALL = ("echo", {"text": "hi"})


def conversation(s):
    return [s.tool_turn([ECHO_CALL], text="Looking."), s.tool_turn([("echo", {"text": "more"})]), s.answer("Fixed.")]


def test_the_same_conversation_through_both_adapters_gives_the_same_neutral_run(tmp_path):
    seen = {}
    for side in BOTH:
        tools = FakeTools()
        result, path, _ = record_real(tmp_path / side, side, conversation(SIDES[side]), tools=tools)
        replayed = replay_real(path)
        assert replayed.identical, (side, replayed.divergence, replayed.differences)
        seen[side] = (result.status, result.final_text, len(result.steps), tools.executed, [s.response.text for s in result.steps])
    assert seen["claude"] == seen["openai"]


@pytest.mark.parametrize("side", BOTH)
def test_the_api_key_is_used_but_never_recorded(tmp_path, side):
    s = SIDES[side]
    _, path, http = record_real(tmp_path, side, conversation(s), record_requests=True)
    assert s.key in "".join(str(v) for r in http.requests for v in r.headers.values())  # the adapter really sent it
    for file in path.iterdir():
        text = file.read_text()
        assert s.key not in text and "Authorization" not in text and "x-api-key" not in text.lower(), file.name


@pytest.mark.parametrize("side", BOTH)
def test_a_changed_system_prompt_is_found_at_the_first_request(tmp_path, side):
    _, path, _ = record_real(tmp_path, side, conversation(SIDES[side]), record_requests=True, system_prompt="Be careful.")
    replayed = replay_real(path, system_prompt="Be careful. Be quick.")
    assert not replayed.identical and replayed.divergence.kind == REQUEST_MISMATCH and replayed.divergence.call == 1
    assert replayed.divergence.path.startswith("system")


@pytest.mark.parametrize("side", BOTH)
def test_a_changed_tool_description_is_found(tmp_path, side):
    _, path, _ = record_real(tmp_path, side, conversation(SIDES[side]), record_requests=True)
    echo, boom = FakeTools().definitions()
    changed = (ToolDefinition(echo.name, echo.description + " Faster.", echo.parameters), boom)
    replayed = replay_real(path, tool_definitions=changed)
    assert replayed.divergence.kind == REQUEST_MISMATCH and "description" in replayed.divergence.path


@pytest.mark.parametrize("side", BOTH)
def test_a_replay_needs_no_key_and_no_network(tmp_path, side, monkeypatch):
    _, path, _ = record_real(tmp_path, side, conversation(SIDES[side]))
    import socket

    def no_socket(*a, **k):
        raise AssertionError("a replay opened a socket")

    monkeypatch.setattr(socket.socket, "connect", no_socket)
    for name in ("ANTHROPIC_API_KEY", "LLM_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert replay_real(path).identical


def test_the_cache_marker_reaches_claude_and_is_part_of_the_recorded_request(tmp_path):
    side = SIDES["claude"]
    cfg = side.config(prompt_caching="explicit")  # only the marker on the block, not the automatic one
    queue = [side.answer("a"), side.answer("b")]
    provider, http = side.build(lambda r: queue.pop(0), cfg)
    recording = start_recording(tmp_path / "rec", __import__("bugbite.recorder", fromlist=["RecordingInfo"]).RecordingInfo(
        cfg, "https://github.com/o/r/issues/1", "o/r", "public", "t", ref="a" * 40, limits=Limits(5), loop_policy=DEFAULT_LOOP_POLICY),
        scrub=lambda t: t, commit_info=lambda: ("c" * 40, False), environment=lambda: dict(FIXED_ENV))
    from bugbite.privacy import Sensitivity

    chain = create_adapter(cfg, sensitivity=Sensitivity.PUBLIC, recorder=recording.writer, provider_adapter=provider)
    chain.generate(GenerationRequest(messages=(Message.user("hello", cache=True),)))
    chain.generate(GenerationRequest(messages=(Message.user("hello", cache=False),)))
    recording.close()
    marked, plain = http.bodies
    assert "cache_control" in json.dumps(marked) and "cache_control" not in json.dumps(plain)
    calls = [json.loads(l) for l in (recording.path / "events.jsonl").read_text().splitlines()]
    calls = [c for c in calls if c["type"] == "model_call"]
    assert calls[0]["request"]["sha256"] != calls[1]["request"]["sha256"]  # the marker changes the fingerprint
