"""The stand-in for the tools: returns the recorded outputs, in order, for the calls that really ran."""

from __future__ import annotations

from typing import Any, Sequence

from bugbite.adapter.codec import canonical_json
from bugbite.agent.tools import ToolOutput

from .clock import ReplayClock
from .diff import short
from .errors import EXTRA_TOOL_CALL, RECORDING_ENDED, TOOL_MISMATCH, ReplayDivergence


class ReplayTools:
    """Has the two methods the loop uses. `recorded` is the list of recorded `tool_call` events; only the ones that ran are served.

    Calls the loop answers by itself (a reply that was not a valid action, a call skipped for lack of time) never reach `execute`,
    so they are not in the list; the loop produces them again and they are compared with the recording afterwards.
    """

    def __init__(self, definitions: Sequence[Any], recorded: Sequence[dict[str, Any]], clock: ReplayClock, *, complete: bool = True) -> None:
        self._definitions = tuple(definitions)
        self._recorded = [e for e in recorded if e["executed"]]
        self._clock = clock
        self._complete = complete
        self.served = 0

    @property
    def unused(self) -> int:
        return len(self._recorded) - self.served

    def definitions(self) -> tuple[Any, ...]:
        return self._definitions

    def execute(self, name: str, arguments: Any, *, time_limit_s: float | None = None) -> ToolOutput:
        number = self.served + 1
        if self.served >= len(self._recorded):
            if not self._complete:
                raise ReplayDivergence(RECORDING_ENDED, number, f"The recording ends after {len(self._recorded)} tool run(s) (it is incomplete); the code ran tool call {number}.")
            raise ReplayDivergence(EXTRA_TOOL_CALL, number, f"The code ran tool call {number} ({name}), but the recording has only {len(self._recorded)}.")
        event = self._recorded[self.served]
        recorded = event["call"]
        try:
            same = recorded["name"] == name and canonical_json(recorded["arguments"]) == canonical_json(arguments)
        except (TypeError, ValueError):
            same = False
        if not same:
            raise ReplayDivergence(
                TOOL_MISMATCH, number,
                f"Tool call {number}: the code called {name} with {short(arguments)}, but the recording has {recorded['name']} with {short(recorded['arguments'])}.",
                fields=("name",) if recorded["name"] != name else ("arguments",))
        self.served += 1
        self._clock.advance_to(event["t"])
        return ToolOutput(event["output"]["text"], event["output"]["is_error"])
