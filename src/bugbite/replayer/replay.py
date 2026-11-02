"""Replaying a recording: run the current agent code against the recorded answers and compare (README FR10.2, FR10.3, FR10.5)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from bugbite.adapter import CostLedger, create_adapter
from bugbite.agent import AgentResult, Limits, LoopPolicy, run_agent
from bugbite.agent.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from bugbite.agent.tools import TOOLS_VERSION, build_agent_tools
from bugbite.privacy import Sensitivity
from bugbite.recorder import LoadedRecording, RunRecorder, load_recording

from .clock import ReplayClock
from .diff import at_path, excerpts, first_difference
from .errors import ReplayDivergence, ReplayError
from .memory import MemoryWriter
from .model import model_from_manifest
from .provider import ReplayProvider
from .tools import ReplayTools

RECORDED: Any = object()  # "use the loop policy the recording says"
MAX_LISTED_DIFFERENCES = 10
_USED = re.compile(r"\(\d+(?:\.\d+)? s used\)")


@dataclass(frozen=True)
class ReplayResult:
    """`identical` is true only if the replay neither diverged nor differed from the recording in anything that matters."""

    identical: bool
    divergence: ReplayDivergence | None
    differences: tuple[str, ...]
    notes: tuple[str, ...]
    agent: AgentResult | None
    events: tuple[dict[str, Any], ...]


def _normal(event: dict[str, Any]) -> dict[str, Any]:
    """An event without the parts that legitimately differ: timestamps, durations, elapsed time and the full request copy."""
    out = {k: v for k, v in event.items() if k not in ("seq", "t", "duration_s")}
    if isinstance(out.get("request"), dict):
        out["request"] = {k: v for k, v in out["request"].items() if k != "full"}
    if isinstance(out.get("outcome"), dict):
        outcome = {k: v for k, v in out["outcome"].items() if k != "elapsed_s"}
        if isinstance(outcome.get("limit_detail"), str):
            outcome["limit_detail"] = _USED.sub("(... s used)", outcome["limit_detail"])
        out["outcome"] = outcome
    return out


def compare_events(recorded: Sequence[dict[str, Any]], replayed: Sequence[dict[str, Any]]) -> list[str]:
    """Every difference between two event lists, ignoring timestamps, tool durations and elapsed time. Empty if they agree."""
    found: list[str] = []
    for index in range(max(len(recorded), len(replayed))):
        if index >= len(recorded):
            found.append(f"event {index + 1}: the replay produced a {replayed[index]['type']} event that the recording does not have")
        elif index >= len(replayed):
            found.append(f"event {index + 1}: the recording has a {recorded[index]['type']} event that the replay did not produce")
        else:
            a, b = _normal(recorded[index]), _normal(replayed[index])
            path = first_difference(a, b)
            if path is not None:
                where = f"event {index + 1} ({recorded[index]['type']})"
                if a.get("type") != b.get("type"):
                    found.append(f"{where}: the replay produced a {replayed[index]['type']} event here")
                else:
                    before, now = excerpts(at_path(a, path), at_path(b, path))
                    found.append(f"{where}: {path} differs: recorded {before}, replayed {now}")
    return found


def _field(manifest: dict[str, Any], *path: str) -> Any:
    value: Any = manifest
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise ReplayError(f"the manifest has no {'.'.join(path)}")
        value = value[key]
    return value


def _settings(manifest: dict[str, Any]) -> tuple[Limits, LoopPolicy | None]:
    if _field(manifest, "settings", "retry_policy") is not None:
        raise ReplayError("this recording used a retry policy, and replaying retries is not supported yet (the retry layer is not part of the replay chain)")
    raw_limits = _field(manifest, "settings", "limits")
    if raw_limits is None:
        raise ReplayError("the manifest does not say what limits the run had")
    raw_policy = _field(manifest, "settings", "loop_policy")
    try:
        return Limits(**raw_limits), (None if raw_policy is None else LoopPolicy(**raw_policy))
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"the manifest's settings are not usable: {exc}") from None


def replay(
    path: str | Path,
    *,
    allow_partial: bool = False,
    system_prompt: str | None = None,
    tool_definitions: Sequence[Any] | None = None,
    loop_policy: Any = RECORDED,
) -> ReplayResult:
    """Replay the recording in folder `path` with no network, sandbox, key or environment access.

    Taken from the recording: the model (with prices), the data sensitivity, the task, the limits, the loop policy, the answers of
    the model and of the tools. Taken from the current code: the system prompt, the tool definitions and the loop itself.
    `system_prompt`, `tool_definitions` and `loop_policy` override those for tests and "what if" runs.

    Raises `bugbite.recorder.RecordingError` for a damaged recording and `ReplayError` for one that cannot be replayed. A difference
    is not an error: it comes back in the result (`divergence` when the replay had to stop, `differences` otherwise).
    """
    recording: LoadedRecording = load_recording(path)
    if not recording.complete and not allow_partial:
        raise ReplayError(f"the recording is not complete ({'; '.join(recording.warnings) or recording.manifest.get('status')}); pass allow_partial=True to replay what there is")
    manifest = recording.manifest
    model = model_from_manifest(_field(manifest, "model"))
    try:
        sensitivity = Sensitivity(_field(manifest, "source", "sensitivity"))
    except ValueError:
        raise ReplayError(f"the manifest's sensitivity {manifest['source']['sensitivity']!r} is not known") from None
    task = _field(manifest, "task", "text")
    if not isinstance(task, str) or not task.strip():
        raise ReplayError("the manifest has no task text")
    limits, recorded_policy = _settings(manifest)
    policy = recorded_policy if loop_policy is RECORDED else loop_policy
    prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt
    definitions = build_agent_tools(None).definitions() if tool_definitions is None else tuple(tool_definitions)

    notes: list[str] = list(recording.warnings)
    recorded_prompt = _field(manifest, "prompt")
    if recorded_prompt.get("version") != PROMPT_VERSION:
        notes.append(f"the recording used prompt version {recorded_prompt.get('version')!r}; the code is at {PROMPT_VERSION!r}")
    if recorded_prompt.get("system_prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest():
        notes.append("the system prompt is not the one the recording used")
    if recorded_prompt.get("tools_version") != TOOLS_VERSION:
        notes.append(f"the recording used tools version {recorded_prompt.get('tools_version')!r}; the code is at {TOOLS_VERSION!r}")

    clock = ReplayClock()
    writer = MemoryWriter(clock, record_requests=bool(_field(manifest, "settings", "record_requests")))
    calls = recording.model_calls()
    provider = ReplayProvider(model, calls, clock, complete=recording.complete)
    tools = ReplayTools(definitions, recording.tool_calls(), clock, complete=recording.complete)
    ledger = CostLedger()
    adapter = create_adapter(model, ledger=ledger, sensitivity=sensitivity, recorder=writer, provider_adapter=provider)
    max_output_tokens = calls[0].request["max_output_tokens"] if calls else None  # a run setting, kept on every request
    agent: AgentResult | None = None
    divergence: ReplayDivergence | None = None
    try:
        agent = run_agent(adapter, tools, task, limits=limits, ledger=ledger, system_prompt=prompt, observer=RunRecorder(writer),
                          max_output_tokens=max_output_tokens, loop_policy=policy, clock=clock)
    except ReplayDivergence as stop:
        divergence = stop
    finally:
        adapter.close()

    differences: list[str] = []
    if divergence is None:
        differences = compare_events(recording.events, writer.events)
        if provider.unused:
            differences.append(f"{provider.unused} recorded model call(s) were not used")
        if tools.unused:
            differences.append(f"{tools.unused} recorded tool run(s) were not used")
        if len(differences) > MAX_LISTED_DIFFERENCES:
            extra = len(differences) - MAX_LISTED_DIFFERENCES
            differences = differences[:MAX_LISTED_DIFFERENCES] + [f"... and {extra} more"]
    if writer.errors:
        notes.append(f"the in-memory recorder had {writer.errors} problem(s), last: {writer.last_error}")
    return ReplayResult(divergence is None and not differences, divergence, tuple(differences), tuple(notes), agent, tuple(writer.events))
