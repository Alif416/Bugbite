"""Builds the two adapter golden recordings: a small deterministic run through the REAL Claude adapter and the REAL
OpenAI-compatible adapter (mock HTTP), kept in git under tests/fixtures/recordings/.

Run `uv run python tests/replayer/make_adapter_goldens.py` only when an adapter's neutral output or the recording format
changes on purpose; then commit the new folders. A test rebuilds them in a temporary folder and compares every byte.
"""

import itertools
import sys
import types
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import real_adapter_helpers as h  # noqa: E402

from bugbite.adapter import claude, openai_compatible  # noqa: E402

RUN_IDS = {"claude": "20270101T000000Z-claude01", "openai": "20270101T000000Z-openai01"}
PROMPT = "You are the adapter golden test agent. Fix the bug, then say so."  # fixed here, so editing the real prompt does not change the fixtures
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"


def build_adapter_golden(root: Path, side: str) -> Path:
    """Write the golden recording for `side` ("claude" or "openai") to `<root>/recordings/<run id>` and return that folder."""
    h._ids = itertools.count(1)  # tool-call ids are part of the recording, so they must not depend on what ran before
    s = h.SIDES[side]
    ticks = itertools.count()
    tools = h.FakeTools()
    replies = [s.tool_turn([("echo", {"text": "golden"})], text="Let me look.", usage=(1200, 40), cache=(300, 0) if side == "claude" else (0, 0)),
               s.answer("The bug is fixed.", usage=(1300, 12), cache=(0, 300) if side == "claude" else (0, 0))]
    steps = itertools.count()
    fixed_time = types.SimpleNamespace(monotonic=lambda: next(steps) * 0.125)  # the adapters measure latency; make it a constant
    with mock.patch.object(claude, "time", fixed_time), mock.patch.object(openai_compatible, "time", fixed_time):
        limits = h.Limits(6, max_cost_usd="5", max_wall_clock_s=60)
        _, path, _ = h.record_real(root, side, replies, tools=tools, task="Fix the golden bug.", limits=limits,
                                   run_id=RUN_IDS[side], clock=lambda: next(ticks) * 0.25, system_prompt=PROMPT)
    return path


if __name__ == "__main__":
    for name in h.BOTH:
        print("wrote", build_adapter_golden(FIXTURES.parent, name))
