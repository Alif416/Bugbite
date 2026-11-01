"""What the agent loop returns and reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Union

from bugbite.adapter.types import GenerationResponse, Message, ToolCallBlock, Usage

from .tools import ToolOutput

# how a run ended
FINISHED = "finished"  # the model gave a final answer (not proof that the bug is fixed)
MAX_STEPS = "max_steps"
TRUNCATED = "truncated"
REFUSED = "refused"
EMPTY_REPLY = "empty_reply"
UNEXPECTED_STOP = "unexpected_stop"
MODEL_ERROR = "model_error"
PRIVACY_BLOCKED = "privacy_blocked"
COST_CAP = "cost_cap"  # the cost limit would be (or was) passed
TIME_CAP = "time_cap"  # the wall-clock limit was reached
ALL_STATUSES = frozenset(
    {FINISHED, MAX_STEPS, TRUNCATED, REFUSED, EMPTY_REPLY, UNEXPECTED_STOP, MODEL_ERROR, PRIVACY_BLOCKED, COST_CAP, TIME_CAP}
)


@dataclass(frozen=True)
class ToolRun:
    """One tool call and what the model was told about it. `executed` is False when it was answered without running."""

    call: ToolCallBlock
    output: ToolOutput
    duration_s: float
    executed: bool = True


@dataclass(frozen=True)
class Step:
    """One model call and what happened to the tool calls in its reply."""

    index: int  # 1-based
    response: GenerationResponse
    tool_runs: tuple[ToolRun, ...] = ()


@dataclass(frozen=True)
class AgentResult:
    status: str
    final_text: str
    steps: tuple[Step, ...]
    messages: tuple[Message, ...]
    usage: Usage
    error_code: str | None = None
    error_message: str | None = None
    observer_errors: int = 0
    cost_usd: Decimal | None = None  # what this job cost (None when no ledger was given)
    elapsed_s: float = 0.0
    limit_detail: str | None = None  # one sentence about the limit that stopped the run, or was passed

    def __post_init__(self) -> None:
        if self.status not in ALL_STATUSES:
            raise ValueError(f"unknown status: {self.status!r}")
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "messages", tuple(self.messages))

    @property
    def finished(self) -> bool:
        return self.status == FINISHED


@dataclass(frozen=True)
class ModelCallEvent:
    step: int
    response: GenerationResponse


@dataclass(frozen=True)
class ToolCallEvent:
    step: int
    run: ToolRun


@dataclass(frozen=True)
class FinishEvent:
    result: AgentResult


Event = Union[ModelCallEvent, ToolCallEvent, FinishEvent]
Observer = Callable[[Event], None]


def add_usage(a: Usage, b: Usage) -> Usage:
    return Usage(
        a.input_tokens + b.input_tokens,
        a.output_tokens + b.output_tokens,
        a.cache_read_tokens + b.cache_read_tokens,
        a.cache_write_tokens + b.cache_write_tokens,
    )
