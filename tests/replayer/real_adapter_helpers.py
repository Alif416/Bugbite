"""Record runs made through the REAL Claude and OpenAI-compatible adapters (canned HTTP replies, no network) and replay them."""

import itertools
import sys
from pathlib import Path

for sub in ("adapter", "recorder", "agent"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / sub))

import claude_helpers as ch  # noqa: E402
import httpx  # noqa: E402
import httpx2  # noqa: E402
import openai_helpers as oh  # noqa: E402
from rec_helpers import FIXED_ENV, Limits, Sensitivity, fake_clocks  # noqa: E402
from loop_helpers import FakeTools  # noqa: E402

from bugbite.adapter import CostLedger, create_adapter  # noqa: E402
from bugbite.agent import DEFAULT_LOOP_POLICY, run_agent  # noqa: E402
from bugbite.recorder import RecordingInfo, start_recording  # noqa: E402
from bugbite.replayer import replay  # noqa: E402

_ids = itertools.count(1)


class ClaudeSide:
    """Builds Messages API replies and the real ClaudeAdapter on a mock transport."""

    name = "claude"
    key = ch.KEY

    def config(self, native=True, **kw):
        return ch.model(native_tool_calling=native, **kw)

    def build(self, replies, config):
        return ch.adapter_for(replies, config=config)

    def tool_turn(self, calls, text=None, usage=(20, 6), cache=(0, 0), **extra):
        content = ([ch.text(text)] if text else []) + [ch.tool_use(n, a, f"toolu_{next(_ids):04d}") for n, a in calls]
        use = {"input_tokens": usage[0], "output_tokens": usage[1], "cache_creation_input_tokens": cache[0], "cache_read_input_tokens": cache[1]}
        return ch.message(content, stop_reason="tool_use", usage=use, **extra)

    def answer(self, text="Done.", usage=(20, 6), cache=(0, 0), stop="end_turn"):
        use = {"input_tokens": usage[0], "output_tokens": usage[1], "cache_creation_input_tokens": cache[0], "cache_read_input_tokens": cache[1]}
        return ch.message([ch.text(text)], stop_reason=stop, usage=use)

    def truncated(self, text="Half an ans"):
        return self.answer(text, stop="max_tokens")

    def http_error(self, status):
        kind = {429: "rate_limit_error", 500: "api_error", 529: "overloaded_error"}.get(status, "invalid_request_error")
        return httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": f"claude says {status}"}})


class OpenAISide:
    """Builds chat completions replies and the real OpenAICompatibleAdapter on a mock transport."""

    name = "openai_compatible"
    key = oh.KEY

    def config(self, native=True, **kw):
        return oh.model(native=native, **kw)

    def build(self, replies, config):
        return oh.adapter_for(replies, config=config)

    def tool_turn(self, calls, text=None, usage=(20, 6), cache=(0, 0), **extra):
        import json

        entries = [oh.tool_call(n, json.dumps(a), f"call_{next(_ids):04d}") for n, a in calls]
        use = None if usage is None else {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
        return oh.completion(content=text, tool_calls=entries, finish="tool_calls", usage=use, **extra)

    def answer(self, text="Done.", usage=(20, 6), cache=(0, 0), stop="stop"):
        use = None if usage is None else {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
        return oh.completion(content=text, finish=stop, usage=use)

    def truncated(self, text="Half an ans"):
        return self.answer(text, stop="length")

    def http_error(self, status):
        return httpx.Response(status, json={"error": {"message": f"server says {status}", "type": "error"}})


SIDES = {"claude": ClaudeSide(), "openai": OpenAISide()}
BOTH = ["claude", "openai"]


def record_real(tmp_path, side, replies, *, native=True, tools=None, limits=None, task="fix it", system_prompt=None,
                sensitivity=Sensitivity.PUBLIC, record_requests=False, run_id=None, clock=None, config_kw=None):
    """Run the loop through the real adapter for `side`, answering from `replies` in order. Returns (result, recording folder, http recorder)."""
    side = SIDES[side] if isinstance(side, str) else side
    queue = list(replies)

    def reply(request):
        return queue.pop(0)

    cfg = side.config(native, **(config_kw or {}))
    provider, http = side.build(reply, cfg)
    wall, mono = fake_clocks()
    limits = limits or Limits(10)
    prompt = {} if system_prompt is None else {"system_prompt": system_prompt}
    recording = start_recording(
        tmp_path / "recordings",
        RecordingInfo(cfg, "https://github.com/o/r/issues/1", "o/r", sensitivity.value, task, ref="a" * 40,
                      limits=limits, loop_policy=DEFAULT_LOOP_POLICY, **prompt),
        scrub=lambda t: t, record_requests=record_requests, commit_info=lambda: ("c" * 40, False),
        environment=lambda: dict(FIXED_ENV), wall_clock=wall, monotonic=mono, run_id=run_id)
    ledger = CostLedger()
    chain = create_adapter(cfg, ledger=ledger, sensitivity=sensitivity, recorder=recording.writer, provider_adapter=provider)
    extra = prompt | {"loop_policy": DEFAULT_LOOP_POLICY} | ({} if clock is None else {"clock": clock})
    result = run_agent(chain, tools or FakeTools(), task, limits=limits, ledger=ledger, observer=recording.observer, **extra)
    recording.close()
    return result, recording.path, http


def replay_real(path, **kw):
    kw.setdefault("tool_definitions", FakeTools().definitions())
    return replay(path, **kw)
