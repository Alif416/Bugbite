"""Builds the golden recording: a small, fully deterministic version-1 recording kept in git.

Run `uv run python tests/recorder/make_golden.py` only when the format version is bumped on purpose; then commit
the new folder under tests/fixtures/recordings/. A test regenerates it in a temporary folder and compares every byte.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rec_helpers import (  # noqa: E402
    FakeTools, ProviderState, Limits, recorded_run, register, text_response, tool_call_response, unregister,
)

from bugbite.adapter import Usage  # noqa: E402
from bugbite.agent.tools import ToolOutput  # noqa: E402

RUN_ID = "20270101T000000Z-golden01"
GOLDEN_PROMPT = "You are the golden test agent. Fix the bug, then say so."  # fixed here, so editing the real prompt does not change the fixture
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"


def build_golden(root: Path) -> Path:
    """Write the golden recording to `<root>/recordings/<run id>` and return that folder."""
    state = ProviderState()
    register(state)
    try:
        ticks = iter(range(100_000))
        tools = FakeTools(outputs={"echo": ToolOutput("echoed: golden")})
        script = [
            tool_call_response(("echo", {"text": "golden"}), text="Let me look.", usage=Usage(12, 7, 3, 1)),
            text_response("The bug is fixed.", usage=Usage(20, 9)),
        ]
        _, recording, _, _ = recorded_run(
            root, state, script, tools=tools, task="Fix the golden bug.", limits=Limits(6, max_cost_usd="5", max_wall_clock_s=60),
            run_id=RUN_ID, clock=lambda: next(ticks) * 0.25, system_prompt=GOLDEN_PROMPT)
        return recording.path
    finally:
        unregister()


if __name__ == "__main__":
    out = build_golden(FIXTURES.parent)
    print("wrote", out)
