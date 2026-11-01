"""Builders shared by the trace store tests: scripted runs with a real ledger, metering and retry wrappers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from decimal import Decimal  # noqa: E402

from loop_helpers import ECHO, FakeTools  # noqa: E402

from bugbite.adapter import CostLedger, MeteredAdapter, TextActionAdapter, Usage  # noqa: E402
from bugbite.adapter.base import ModelAdapter  # noqa: E402
from bugbite.adapter.testing import ScriptedAdapter, text_response, tool_call_response  # noqa: E402
from bugbite.agent import Limits, run_agent  # noqa: E402
from bugbite.config import ModelConfig, Pricing  # noqa: E402
from bugbite.errors import AdapterError  # noqa: E402

class TestRetry(ModelAdapter):
    """A minimal retry layer for these tests (the real one lives on another branch): up to 4 tries on transient errors."""

    __test__ = False
    CODES = {"rate_limited", "server_error", "network_error", "timeout"}

    def __init__(self, inner):
        super().__init__(inner.config)
        self.inner = inner

    def generate(self, request):
        for attempt in range(1, 5):
            try:
                return self.inner.generate(request)
            except AdapterError as error:
                if error.code not in self.CODES or attempt == 4:
                    raise

    def estimate_tokens(self, request):
        return self.inner.estimate_tokens(request)


PRICING = Pricing.of(1000, 2000)  # dollars per million tokens: 1e-3 per input token, 2e-3 per output token


def model(native=True, name="paid"):
    return ModelConfig(name, "scripted", "http://x", "m", 100_000, native, PRICING, 0.0, True, max_output_tokens=100)


def scripted_run(script, recorder_for, *, native=True, retry=False, limits=None, tools=None, observer_extra=None):
    """Run the agent on a scripted model through the real metering (and optionally retry and text-action) wrappers.

    `recorder_for(ledger)` returns the observer. Returns (result, ledger, recorder, raw_adapter).
    """
    ledger = CostLedger()
    raw = ScriptedAdapter(model(native), list(script))
    adapter = MeteredAdapter(raw, ledger)
    if retry:
        adapter = TestRetry(adapter)
    if not native:
        adapter = TextActionAdapter(adapter)
    recorder = recorder_for(ledger)
    result = run_agent(adapter, tools or FakeTools(), "fix it", limits=limits or Limits(10), ledger=ledger, observer=recorder)
    return result, ledger, recorder, raw


__all__ = [
    "ECHO", "FakeTools", "Decimal", "Usage", "AdapterError", "text_response", "tool_call_response", "scripted_run", "model", "Limits",
]
