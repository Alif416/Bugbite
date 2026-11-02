"""The loop observer that records steps, tool calls and the outcome (AD-117)."""

from __future__ import annotations

from typing import Any

from bugbite.adapter.cost import money_text
from bugbite.agent.types import AgentResult, FinishEvent, ModelCallEvent, ToolCallEvent

from .writer import RunWriter


def outcome_of(result: AgentResult) -> dict[str, Any]:
    usage = result.usage
    return {
        "status": result.status, "error_code": result.error_code, "error_message": result.error_message,
        "limit_detail": result.limit_detail, "steps": len(result.steps), "nudges": result.nudges,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "cache_read_tokens": usage.cache_read_tokens, "cache_write_tokens": usage.cache_write_tokens},
        "cost_usd": None if result.cost_usd is None else money_text(result.cost_usd),
        "elapsed_s": result.elapsed_s, "observer_errors": result.observer_errors,
    }


class RunRecorder:
    """Use as `run_agent(..., observer=recorder)`. Nothing here raises: problems are counted on the writer."""

    def __init__(self, writer: RunWriter) -> None:
        self.writer = writer
        self._positions: dict[int, int] = {}

    def __call__(self, event: Any) -> None:
        try:
            if isinstance(event, ModelCallEvent):
                self.writer.write({"type": "step", "step": event.step, "model_calls": self.writer.take_unassigned_calls()})
            elif isinstance(event, ToolCallEvent):
                run = event.run
                position = self._positions[event.step] = self._positions.get(event.step, 0) + 1
                self.writer.write({
                    "type": "tool_call", "step": event.step, "position": position,
                    "call": {"id": run.call.id, "name": run.call.name, "arguments": run.call.arguments},
                    "output": {"text": run.output.text, "is_error": run.output.is_error},
                    "executed": run.executed, "duration_s": run.duration_s,
                })
            elif isinstance(event, FinishEvent):
                result = event.result
                outcome = outcome_of(result)
                self.writer.write({
                    "type": "finish", "outcome": outcome, "final_text": result.final_text,
                    "unassigned_model_calls": self.writer.take_unassigned_calls(),
                    "nudges": {str(s.index): s.nudge for s in result.steps if s.nudge},
                })
                self.writer.finish(outcome)
        except Exception as exc:
            self.writer.note_error(exc)
