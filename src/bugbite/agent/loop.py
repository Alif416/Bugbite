"""The agent loop: ask the model, run the tools it asks for, show it the results, repeat (README FR5.3).

This is the minimal version. It has no cost or time limits (P17), no loop detection (P18) and does not
trim a long conversation. `max_steps` is the only limit and is required. "Finished" means the model stopped,
not that the bug is fixed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from bugbite.adapter.base import ModelAdapter
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

from .prompt import SYSTEM_PROMPT
from .tools import ToolOutput
from .types import (
    EMPTY_REPLY,
    FINISHED,
    MAX_STEPS,
    MODEL_ERROR,
    PRIVACY_BLOCKED,
    REFUSED,
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


def _run_call(tools: Any, call: Any) -> ToolRun:
    started = time.monotonic()
    if call.error is not None or call.name == INVALID_ACTION:
        text = call.error or "That reply was not a valid action."
        output, executed = ToolOutput(text, True), False
    else:
        executed = True
        try:
            output = tools.execute(call.name, call.arguments)
            if not isinstance(output, ToolOutput):
                output = ToolOutput(f"{call.name} returned something unexpected.", True)
        except Exception as exc:  # the registry never raises; this protects the loop from a custom one
            output = ToolOutput(f"{call.name} failed unexpectedly ({type(exc).__name__}).", True)
    if not output.text:
        output = ToolOutput("(no output)", output.is_error)
    return ToolRun(call, output, time.monotonic() - started, executed)


def run_agent(
    adapter: ModelAdapter,
    tools: Any,
    task: str,
    *,
    max_steps: int,
    system_prompt: str = SYSTEM_PROMPT,
    observer: Observer | None = None,
    max_output_tokens: int | None = None,
) -> AgentResult:
    """Run the loop. `tools` needs `definitions()` and `execute(name, arguments)` (a `ToolRegistry`).

    Returns an `AgentResult` for every ending, including model failures. Only mistakes in the arguments
    raise. `KeyboardInterrupt` is not caught. Errors raised by the observer while it handles the
    `FinishEvent` are logged but are not counted in the result.
    """
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError(f"max_steps must be an integer of at least 1, got {max_steps!r}")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("system_prompt must be a non-empty string")

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

    def finish(status: str, final_text: str = "", error: Exception | None = None) -> AgentResult:
        result = AgentResult(
            status=status,
            final_text=final_text,
            steps=tuple(steps),
            messages=tuple(messages),
            usage=usage,
            error_code=getattr(error, "code", None),
            error_message=getattr(error, "message", None),
            observer_errors=observer_errors,
        )
        notify(FinishEvent(result))
        return result

    for index in range(1, max_steps + 1):
        request = GenerationRequest(
            messages=tuple(messages), system=system, tools=definitions, max_output_tokens=max_output_tokens
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

        if response.stop_reason == STOP_REFUSAL:
            steps.append(Step(index, response))
            return finish(REFUSED, response.text.strip())
        if response.stop_reason == STOP_MAX_TOKENS:  # a cut-off tool call may have half its arguments
            steps.append(Step(index, response))
            return finish(TRUNCATED, response.text.strip())
        if not calls:
            steps.append(Step(index, response))
            text = response.text.strip()
            if response.stop_reason == STOP_OTHER:
                return finish(UNEXPECTED_STOP, text)
            return finish(FINISHED, text) if text else finish(EMPTY_REPLY)
        if index == max_steps:
            steps.append(Step(index, response))
            return finish(MAX_STEPS)

        runs: list[ToolRun] = []
        for call in calls:
            run = _run_call(tools, call)
            runs.append(run)
            notify(ToolCallEvent(index, run))
        steps.append(Step(index, response, tuple(runs)))
        messages.append(
            Message.tool_results(*(ToolResultBlock(r.call.id, r.output.text, r.output.is_error) for r in runs))
        )

    return finish(MAX_STEPS)  # not reached: the last step always returns above
