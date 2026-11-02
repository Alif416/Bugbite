"""Shared builders: a scripted run through the real adapter chain with a recording."""

import itertools
import sys
from pathlib import Path

for sub in ("agent", "trace_store", "adapter"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / sub))

from decimal import Decimal  # noqa: E402

from loop_helpers import FakeTools, text_response, tool_call_response  # noqa: E402
from ts_helpers import PRICING, TestRetry  # noqa: E402

from bugbite.adapter import CostLedger, create_adapter, register_adapter, unregister_adapter  # noqa: E402
from bugbite.adapter.testing import ScriptedAdapter  # noqa: E402
from bugbite.agent import DEFAULT_LOOP_POLICY, Limits, run_agent  # noqa: E402
from bugbite.config import ModelConfig  # noqa: E402
from bugbite.errors import AdapterError  # noqa: E402
from bugbite.privacy import Sensitivity  # noqa: E402
from bugbite.recorder import RecordingInfo, load_recording, start_recording  # noqa: E402

PROVIDER = "rec_fake"
FIXED_ENV = {"version": "0.0.0-test", "python": "3.11.0", "platform": "test-platform"}


def model(native=True, allow=True):
    return ModelConfig("paid", PROVIDER, "http://x", "m", 100_000, native, PRICING, 0.0, allow, max_output_tokens=100)


class ProviderState:
    def __init__(self):
        self.script, self.raw = [], None


def register(state):
    def factory(cfg, key):
        state.raw = ScriptedAdapter(cfg, list(state.script))
        return state.raw

    register_adapter(PROVIDER, factory)


def unregister():
    unregister_adapter(PROVIDER)


def fake_clocks(step=0.5):
    """(wall clock, monotonic clock): deterministic, so recordings can be compared byte for byte."""
    wall = itertools.count(1_800_000_000)
    mono = itertools.count()
    return (lambda: float(next(wall))), (lambda: next(mono) * step)


def recorded_run(tmp_path, state, script, *, native=True, retry=False, record_requests=False, tools=None, limits=None,
                 scrub=None, task="fix it", info_kw=None, run_id=None, sensitivity=Sensitivity.PUBLIC, max_bytes=None, clock=None,
                 monotonic=None, system_prompt=None, allow=True, loop_policy=DEFAULT_LOOP_POLICY, max_output_tokens=None):
    state.script = list(script)
    wall, mono = fake_clocks()
    mono = monotonic or mono
    prompt = {} if system_prompt is None else {"system_prompt": system_prompt}
    kw = {} if max_bytes is None else {"max_bytes": max_bytes}
    recording = start_recording(
        tmp_path / "recordings", RecordingInfo(model(native, allow), "https://github.com/o/r/issues/1", "o/r", sensitivity.value, task, ref="a" * 40,
                                               limits=limits or Limits(10), loop_policy=loop_policy, **prompt, **(info_kw or {})),
        scrub=scrub or (lambda t: t), record_requests=record_requests, commit_info=lambda: ("c" * 40, False),
        environment=lambda: dict(FIXED_ENV), wall_clock=wall, monotonic=mono, run_id=run_id, **kw)
    ledger = CostLedger()
    adapter = create_adapter(model(native, allow), ledger=ledger, sensitivity=sensitivity, recorder=recording.writer)
    if retry:
        adapter = TestRetry(adapter)
    extra = prompt | {"loop_policy": loop_policy} | ({} if max_output_tokens is None else {"max_output_tokens": max_output_tokens}) | ({} if clock is None else {"clock": clock})
    result = run_agent(adapter, tools or FakeTools(), task, limits=limits or Limits(10), ledger=ledger, observer=recording.observer, **extra)
    recording.close()
    return result, recording, ledger, state.raw


__all__ = ["recorded_run", "register", "unregister", "ProviderState", "model", "fake_clocks", "FakeTools", "text_response",
           "tool_call_response", "AdapterError", "Decimal", "load_recording", "Limits", "FIXED_ENV", "PROVIDER"]
