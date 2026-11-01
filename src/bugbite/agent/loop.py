"""The agent loop: ask the model, run the tools it asks for, show it the results, repeat (README FR5.3).

It stops by itself at the job's hard limits (FR5.4): steps, cost and wall-clock time (see `Limits`). Loop
detection (P18) and trimming a long conversation are not done yet. "Finished" means the model stopped, not
that the bug is fixed.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Callable

from bugbite.adapter.base import ModelAdapter
from bugbite.adapter.cost import money_text, worst_case_cost
from bugbite.adapter.ledger import CostLedger
from bugbite.adapter.metered import MeteredAdapter
from bugbite.adapter.text_action import INVALID_ACTION
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    STOP_MAX_TOKENS,
    STOP_OTHER,
    STOP_REFUSAL,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    Usage,
)
from bugbite.errors import AdapterError, PrivacyError

from .limits import Limits
from .loopguard import DEFAULT_LOOP_POLICY, NO_SIGNAL, NUDGE, RESET, STOP, LoopDetector, LoopPolicy, Signal, stronger
from .prompt import SYSTEM_PROMPT
from .tools import ToolOutput
from .types import (
    COST_CAP,
    EMPTY_REPLY,
    FINISHED,
    LOOP_DETECTED,
    MAX_STEPS,
    MODEL_ERROR,
    PRIVACY_BLOCKED,
    REFUSED,
    TIME_CAP,
    TRUNCATED,
    UNEXPECTED_STOP,
    AgentResult,
    FinishEvent,
    ModelCallEvent,
    Observer,
    Step,
    ToolCallEvent,
    ToolRun,
    add_usage,
)

log = logging.getLogger(__name__)
NOTE_PREFIX = "[Bugbite note] "
NOT_RUN_TIME = "Not run: the time limit for this job was reached."


def _run_call(tools: Any, call: Any, time_limit_s: float | None) -> ToolRun:
    started = time.monotonic()
    if call.error is not None or call.name == INVALID_ACTION:
        text = call.error or "That reply was not a valid action."
        output, executed = ToolOutput(text, True), False
    else:
        executed = True
        try:
            output = tools.execute(call.name, call.arguments, time_limit_s=time_limit_s)
            if not isinstance(output, ToolOutput):
                output = ToolOutput(f"{call.name} returned something unexpected.", True)
        except Exception as exc:  # the registry never raises; this protects the loop from a custom one
            output = ToolOutput(f"{call.name} failed unexpectedly ({type(exc).__name__}).", True)
    if not output.text:
        output = ToolOutput("(no output)", output.is_error)
    return ToolRun(call, output, time.monotonic() - started, executed)


def _ledger_is_in_chain(adapter: Any, ledger: CostLedger) -> bool:
    """True if some wrapper in the adapter chain records into this ledger."""
    seen: set[int] = set()
    while adapter is not None and id(adapter) not in seen:
        seen.add(id(adapter))
        if isinstance(adapter, MeteredAdapter) and adapter.ledger is ledger:
            return True
        adapter = getattr(adapter, "inner", None)
    return False


def run_agent(
    adapter: ModelAdapter,
    tools: Any,
    task: str,
    *,
    limits: Limits,
    ledger: CostLedger | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    observer: Observer | None = None,
    max_output_tokens: int | None = None,
    loop_policy: LoopPolicy | None = DEFAULT_LOOP_POLICY,
    clock: Callable[[], float] = time.monotonic,
) -> AgentResult:
    """Run the loop. `tools` needs `definitions()` and `execute(name, arguments, time_limit_s=...)`.

    A cost limit needs `ledger`, the ledger of a `MeteredAdapter` in the adapter chain (checked before
    anything is sent): without a way to measure cost the cap cannot be kept. Returns an `AgentResult` for
    every ending, including model failures and limits. Only mistakes in the arguments raise.
    `KeyboardInterrupt` is not caught. Errors raised by the observer while it handles the `FinishEvent` are
    logged but are not counted in the result.
    """
    if not isinstance(limits, Limits):
        raise ValueError("limits must be a Limits object")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("system_prompt must be a non-empty string")
    if loop_policy is not None and not isinstance(loop_policy, LoopPolicy):
        raise ValueError("loop_policy must be a LoopPolicy or None")
    cost_cap: Decimal | None = limits.max_cost_usd
    if cost_cap is not None:
        if ledger is None:
            raise ValueError("a cost limit needs the ledger of the metered adapter, so cost can be measured")
        if not _ledger_is_in_chain(adapter, ledger):
            raise ValueError("the ledger is not the one used by a MeteredAdapter in this adapter chain")
    baseline = ledger.total_usd if ledger is not None else None
    wall = limits.max_wall_clock_s
    started = clock()
    calls_per_step = max(1, int(getattr(adapter, "max_calls_per_step", 1)))

    def elapsed() -> float:
        return clock() - started

    def time_left() -> float | None:
        return None if wall is None else wall - elapsed()

    def spent() -> Decimal | None:
        return None if ledger is None else ledger.total_usd - baseline

    detector = LoopDetector(loop_policy) if loop_policy is not None else None
    nudges = 0
    observer_errors = 0

    def notify(event: Any) -> None:
        nonlocal observer_errors
        if observer is None:
            return
        try:
            observer(event)
        except Exception as exc:  # a recording fault must not throw away a paid job; the count shows the gap
            observer_errors += 1
            log.warning("agent observer failed (%s)", type(exc).__name__)

    system = (TextBlock(system_prompt),)
    definitions = tools.definitions()
    messages: list[Message] = [Message.user(task)]
    steps: list[Step] = []
    usage = Usage()

    def finish(status: str, final_text: str = "", error: Exception | None = None, detail: str | None = None) -> AgentResult:
        result = AgentResult(
            status=status,
            final_text=final_text,
            steps=tuple(steps),
            messages=tuple(messages),
            usage=usage,
            error_code=getattr(error, "code", None),
            error_message=getattr(error, "message", None),
            observer_errors=observer_errors,
            cost_usd=spent(),
            elapsed_s=elapsed(),
            limit_detail=detail,
            nudges=nudges,
        )
        notify(FinishEvent(result))
        return result

    def time_detail() -> str:
        return f"Stopped: the time limit of {wall:g} s was reached ({elapsed():.1f} s used)."

    def over_cap_detail() -> str:
        return f"the job has spent ${money_text(spent())}, over its cost limit of ${money_text(cost_cap)}"

    for index in range(1, limits.max_steps + 1):
        left = time_left()
        if left is not None and left <= 0:
            return finish(TIME_CAP, detail=time_detail())
        request = GenerationRequest(
            messages=tuple(messages), system=system, tools=definitions, max_output_tokens=max_output_tokens
        )
        if cost_cap is not None:
            worst = calls_per_step * worst_case_cost(
                adapter.config.pricing,
                adapter.estimate_tokens(request),
                adapter.resolve_max_output_tokens(request),
                limits.cost_margin,
            )
            if spent() + worst > cost_cap:
                return finish(
                    COST_CAP,
                    detail=(
                        f"Stopped before step {index}: the next step could cost up to ${money_text(worst)} and only "
                        f"${money_text(max(cost_cap - spent(), Decimal(0)))} of the ${money_text(cost_cap)} cost limit was left."
                    ),
                )
        try:
            response: GenerationResponse = adapter.generate(request)
        except PrivacyError as exc:
            return finish(PRIVACY_BLOCKED, error=exc)
        except AdapterError as exc:
            return finish(MODEL_ERROR, error=exc)
        usage = add_usage(usage, response.usage)
        if response.blocks:
            messages.append(Message(ROLE_ASSISTANT, response.blocks))
        notify(ModelCallEvent(index, response))
        calls = response.tool_calls
        over = cost_cap is not None and spent() > cost_cap

        if response.stop_reason == STOP_REFUSAL:
            steps.append(Step(index, response))
            return finish(REFUSED, response.text.strip())
        if response.stop_reason == STOP_MAX_TOKENS:  # a cut-off tool call may have half its arguments
            steps.append(Step(index, response))
            return finish(TRUNCATED, response.text.strip())
        if not calls:
            steps.append(Step(index, response))
            text = response.text.strip()
            note = f"The last call cost more than estimated: {over_cap_detail()}." if over else None
            if response.stop_reason == STOP_OTHER:
                return finish(UNEXPECTED_STOP, text, detail=note)
            return finish(FINISHED, text, detail=note) if text else finish(EMPTY_REPLY, detail=note)

        left = time_left()
        timed_out = left is not None and left <= 0
        if not timed_out and over:
            steps.append(Step(index, response))
            return finish(COST_CAP, detail=f"Stopped before running tools: {over_cap_detail()}; the estimate for the last call was too low.")
        if not timed_out and index == limits.max_steps:
            steps.append(Step(index, response))
            return finish(MAX_STEPS, detail=f"Stopped: the limit of {limits.max_steps} steps was reached.")

        runs: list[ToolRun] = []
        pending: list[Signal] = []
        for call in calls:
            left = time_left()
            if left is not None and left <= 0:
                run = ToolRun(call, ToolOutput(NOT_RUN_TIME, True), 0.0, executed=False)
            else:
                run = _run_call(tools, call, left)
            runs.append(run)
            notify(ToolCallEvent(index, run))
            if detector is not None:
                signal = detector.observe(run)
                if signal.kind == RESET:  # the repository changed: earlier signals in this step no longer apply
                    pending.clear()
                elif signal.kind != "ok":
                    pending.append(signal)
        stop = next((s for s in pending if s.kind == STOP), NO_SIGNAL)
        notes = [] if stop.kind == STOP else [s.note for s in pending if s.kind == NUDGE]
        blocks = [ToolResultBlock(r.call.id, r.output.text, r.output.is_error) for r in runs]
        nudge = None
        if notes:
            nudge = "\n".join(notes)
            last = blocks[-1]
            blocks[-1] = ToolResultBlock(last.tool_call_id, last.content + "\n\n" + NOTE_PREFIX + nudge, last.is_error)
            nudges += 1
        steps.append(Step(index, response, tuple(runs), nudge))
        messages.append(Message.tool_results(*blocks))
        if stop.kind == STOP:
            left = time_left()
            if left is not None and left <= 0:
                return finish(TIME_CAP, detail=time_detail())
            return finish(LOOP_DETECTED, detail=stop.detail)

    left = time_left()
    if left is not None and left <= 0:  # the last step ended with the clock out; time wins over steps
        return finish(TIME_CAP, detail=time_detail())
    return finish(MAX_STEPS, detail=f"Stopped: the limit of {limits.max_steps} steps was reached.")
