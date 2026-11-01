"""An agent-loop observer that writes the run to the trace store as it happens (AD-114, AD-115, AD-116)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Callable

from bugbite.adapter.ledger import CallRecord, CostLedger
from bugbite.agent.types import AgentResult, FinishEvent, ModelCallEvent, ToolCallEvent

from .store import JobFinish, JobStart, ModelCallInput, ToolCallInput, TraceStore


def _identity(text: str) -> str:
    return text


def _scrub_json(value: Any, scrub: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {scrub(str(k)): _scrub_json(v, scrub) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_json(v, scrub) for v in value]
    return value


class TraceRecorder:
    """Use as `run_agent(..., observer=recorder)`.

    `ledger` must be the ledger of the job's metered adapter, and serve only this job: the recorder gives each
    ledger entry a step number by the order of events. A database problem is counted in `errors` and never
    raised; `scrub` is applied to every string before it is stored.
    """

    def __init__(self, store: TraceStore, job_id: uuid.UUID, ledger: CostLedger, *, scrub: Callable[[str], str] = _identity) -> None:
        self.store, self.job_id, self.ledger, self._scrub = store, job_id, ledger, scrub
        self.errors = 0
        self.last_error: str | None = None  # the kind of the last database error, never its text
        self._seen = len(ledger.calls)  # entries from before this job are not ours
        self._last_step = 0
        self._tool_steps: dict[int, int] = {}
        self._tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self._cost = Decimal(0)
        self._retries = 0

    # -- helpers ---------------------------------------------------------------------------------------------------------------

    def _s(self, text: str | None) -> str | None:
        return None if text is None else self._scrub(text)

    def _absorb(self, work: Callable[[], None]) -> None:
        try:
            work()
        except Exception as exc:  # a trace is a record, not part of the work (AD-115)
            self.errors += 1
            self.last_error = type(exc).__name__

    def _new_records(self) -> list[CallRecord]:
        records = list(self.ledger.calls[self._seen :])
        self._seen += len(records)
        return records

    def _to_input(self, record: CallRecord, response: Any = None) -> ModelCallInput:
        usage, cost = record.usage, record.cost
        reply = tools = None
        if response is not None and not record.failed:
            reply = self._s(response.text)
            tools = [{"id": c.id, "name": c.name, "arguments": _scrub_json(c.arguments, self._scrub)} for c in response.tool_calls] or None
        return ModelCallInput(
            model=record.model, request_id=record.request_id, stop_reason=record.stop_reason,
            input_tokens=usage.input_tokens if usage else 0, output_tokens=usage.output_tokens if usage else 0,
            cache_read_tokens=usage.cache_read_tokens if usage else 0, cache_write_tokens=usage.cache_write_tokens if usage else 0,
            usage_estimated=bool(cost.estimated) if cost else False, latency_s=record.latency_s,
            cost_usd=None if cost is None else cost.total_usd, error_code=record.error_code, response_text=reply, requested_tools=tools,
        )

    def _count(self, records: list[ModelCallInput]) -> None:
        for call in records:
            self._tokens["input"] += call.input_tokens
            self._tokens["output"] += call.output_tokens
            self._tokens["cache_read"] += call.cache_read_tokens
            self._tokens["cache_write"] += call.cache_write_tokens
            self._cost += call.cost_usd or Decimal(0)
        self._retries += sum(1 for i, call in enumerate(records) if call.error_code and i < len(records) - 1)

    def _store_calls(self, step: int, calls: list[ModelCallInput]) -> None:
        if not calls:
            return
        self._count(calls)  # counted even if the write fails, so the totals still match what was billed
        self._absorb(lambda: self.store.record_model_calls(self.job_id, step, calls))

    # -- the observer ----------------------------------------------------------------------------------------------------------

    def __call__(self, event: Any) -> None:
        try:
            if isinstance(event, ModelCallEvent):
                self._on_model_call(event)
            elif isinstance(event, ToolCallEvent):
                self._on_tool_call(event)
            elif isinstance(event, FinishEvent):
                self._on_finish(event.result)
        except Exception as exc:  # nothing here may reach the loop
            self.errors += 1
            self.last_error = type(exc).__name__

    def _on_model_call(self, event: ModelCallEvent) -> None:
        self._last_step = event.step
        records = self._new_records()
        calls = [self._to_input(r, event.response if i == len(records) - 1 else None) for i, r in enumerate(records)]
        if not records or records[-1].failed:  # no ledger entry for this reply (an unmetered adapter): store what the reply itself says
            usage = event.response.usage
            calls.append(ModelCallInput(
                model=event.response.model, request_id=event.response.request_id, stop_reason=event.response.stop_reason,
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cache_read_tokens=usage.cache_read_tokens,
                cache_write_tokens=usage.cache_write_tokens, usage_estimated=event.response.usage_estimated, latency_s=event.response.latency_s,
                response_text=self._s(event.response.text),
                requested_tools=[{"id": c.id, "name": c.name, "arguments": _scrub_json(c.arguments, self._scrub)} for c in event.response.tool_calls] or None,
            ))
        self._store_calls(event.step, calls)

    def _on_tool_call(self, event: ToolCallEvent) -> None:
        run = event.run
        self._last_step = max(self._last_step, event.step)
        self._tool_steps[event.step] = self._tool_steps.get(event.step, 0) + 1
        call = ToolCallInput(
            call_id=self._scrub(run.call.id), tool=self._scrub(run.call.name), arguments=_scrub_json(run.call.arguments, self._scrub),
            output_text=self._scrub(run.output.text), is_error=run.output.is_error, executed=run.executed, duration_s=run.duration_s,
        )
        self._absorb(lambda: self.store.record_tool_call(self.job_id, event.step, call))

    def _on_finish(self, result: AgentResult) -> None:
        leftovers = [self._to_input(r) for r in self._new_records()]  # failed attempts after the last reply
        self._store_calls(self._last_step + 1, leftovers)
        for step in result.steps:
            if step.nudge:
                nudge = self._scrub(step.nudge)
                self._absorb(lambda step=step, nudge=nudge: self.store.record_step(self.job_id, step.index, nudge))
        finish = JobFinish(
            status=result.status, final_text=self._s(result.final_text), error_code=result.error_code,
            error_message=self._s(result.error_message), limit_detail=self._s(result.limit_detail),
            steps_count=len(result.steps), nudges=result.nudges, retries=self._retries,
            observer_errors=result.observer_errors + self.errors, input_tokens=self._tokens["input"], output_tokens=self._tokens["output"],
            cache_read_tokens=self._tokens["cache_read"], cache_write_tokens=self._tokens["cache_write"], cost_usd=self._cost,
            elapsed_s=result.elapsed_s,
        )
        self._absorb(lambda: self.store.finish_job(self.job_id, finish))

    def abort(self, reason: str) -> None:
        """For the caller's exception handler: mark the job aborted if it is still running."""
        self._absorb(lambda: self.store.abort_job(self.job_id, self._scrub(reason)))


def start_trace(store: TraceStore, start: JobStart, ledger: CostLedger, *, scrub: Callable[[str], str] = _identity) -> TraceRecorder:
    """Create the job row (with every string scrubbed) and return the recorder for it."""
    clean = JobStart(
        issue_url=scrub(start.issue_url), repo=scrub(start.repo), model=scrub(start.model), sensitivity=start.sensitivity,
        ref=None if start.ref is None else scrub(start.ref), prompt_version=start.prompt_version, tools_version=start.tools_version,
        agent_commit=start.agent_commit, task_text=None if start.task_text is None else scrub(start.task_text),
        config=_scrub_json(start.config, scrub),
    )
    return TraceRecorder(store, store.start_job(clean), ledger, scrub=scrub)
