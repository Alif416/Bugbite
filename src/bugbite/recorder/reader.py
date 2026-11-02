"""Reading and checking a recording (README FR10.2 needs this in P23)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bugbite.adapter.codec import CodecError, error_from_dict, response_from_dict
from bugbite.adapter.types import GenerationResponse
from bugbite.errors import AdapterError

from .writer import EVENTS, FORMAT, FORMAT_VERSION, MANIFEST, RecordingError

_BASE = {"seq", "type", "t"}
_EVENT_KEYS: dict[str, set[str]] = {
    "model_call": {"call", "request"},  # plus exactly one of response, error, exception
    "step": {"step", "model_calls"},
    "tool_call": {"step", "position", "call", "output", "executed", "duration_s"},
    "finish": {"outcome", "final_text", "unassigned_model_calls", "nudges"},
}
_OUTCOMES = {"response", "error", "exception"}
_REQUEST_KEYS = {"sha256", "bytes", "messages", "system_blocks", "tools", "max_output_tokens", "temperature", "stop_sequences"}


@dataclass(frozen=True)
class ModelCallRecord:
    call: int
    request: dict[str, Any]  # the fingerprint (and the full request when it was recorded)
    response: GenerationResponse | None
    error: AdapterError | None
    exception: str | None  # the type name of a bug in the provider adapter
    t: float


@dataclass(frozen=True)
class LoadedRecording:
    path: Path
    manifest: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    complete: bool
    warnings: tuple[str, ...]

    def model_calls(self) -> list[ModelCallRecord]:
        out = []
        for e in self.events:
            if e["type"] == "model_call":
                out.append(ModelCallRecord(
                    e["call"], e["request"], response_from_dict(e["response"]) if "response" in e else None,
                    error_from_dict(e["error"]) if "error" in e else None, e.get("exception"), e["t"]))
        return out

    def tool_calls(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "tool_call"]

    def steps(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "step"]

    def finish(self) -> dict[str, Any] | None:
        return next((e for e in self.events if e["type"] == "finish"), None)


def load_recording(path: str | Path) -> LoadedRecording:
    folder = Path(path)

    def bad(file: str, problem: str) -> RecordingError:
        return RecordingError(f"{folder / file}: {problem}")

    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise bad(MANIFEST, "missing") from None
    except (OSError, ValueError):
        raise bad(MANIFEST, "unreadable or not valid JSON") from None
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise bad(MANIFEST, f"not a {FORMAT} manifest")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise bad(MANIFEST, f"format version {manifest.get('format_version')!r} is not supported (this reader reads version {FORMAT_VERSION})")
    status = manifest.get("status")
    if status not in ("recording", "complete", "incomplete"):
        raise bad(MANIFEST, f"unknown status {status!r}")
    try:
        raw = (folder / EVENTS).read_bytes()
    except FileNotFoundError:
        raise bad(EVENTS, "missing") from None
    except OSError:
        raise bad(EVENTS, "unreadable") from None
    warnings: list[str] = []
    if manifest.get("run_id") != folder.name:
        warnings.append(f"the folder is named {folder.name!r} but the manifest says run_id {manifest.get('run_id')!r}")

    lines = raw.decode("utf-8", errors="replace").split("\n")
    trailing_complete = raw.endswith(b"\n") or raw == b""
    if lines and lines[-1] == "":
        lines.pop()
    events: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except ValueError:
            if index == len(lines) and not trailing_complete and status != "complete":
                warnings.append("the last line was cut off (the run probably crashed) and was ignored")
                break
            raise bad(EVENTS, f"line {index} is not valid JSON") from None
        _check_event(folder, index, event, events)
        events.append(event)

    if status == "complete":
        counts = manifest.get("counts") or {}
        if hashlib.sha256(raw).hexdigest() != manifest.get("events_sha256") or len(raw) != manifest.get("events_bytes"):
            raise bad(EVENTS, "does not match the hash and size in the manifest (the file was changed or damaged)")
        actual = {"events": len(events), "model_calls": sum(e["type"] == "model_call" for e in events),
                  "tool_calls": sum(e["type"] == "tool_call" for e in events)}
        if counts != actual:
            raise bad(MANIFEST, f"counts {counts} do not match the events {actual}")
    else:
        warnings.append(f"the recording is {status}" + (f": {manifest.get('reason')}" if manifest.get("reason") else ""))
    return LoadedRecording(folder, manifest, tuple(events), status == "complete", tuple(warnings))


def _check_event(folder: Path, line: int, event: Any, earlier: list[dict[str, Any]]) -> None:
    def bad(problem: str) -> RecordingError:
        return RecordingError(f"{folder / EVENTS}: line {line}: {problem}")

    if not isinstance(event, dict) or not _BASE <= set(event):
        raise bad("not an event object")
    if event["seq"] != len(earlier) + 1 or isinstance(event["seq"], bool):
        raise bad(f"sequence number {event['seq']!r} where {len(earlier) + 1} was expected (events are missing or reordered)")
    kind = event["type"]
    if kind not in _EVENT_KEYS:
        raise bad(f"unknown event type {kind!r}")
    keys = set(event) - _BASE
    wanted = _EVENT_KEYS[kind]
    if kind == "model_call":
        outcome = keys & _OUTCOMES
        if len(outcome) != 1 or keys - _OUTCOMES != wanted:
            raise bad("a model_call needs call, request and exactly one of response, error, exception")
        request = event["request"]
        if not isinstance(request, dict) or not _REQUEST_KEYS <= set(request) or set(request) - _REQUEST_KEYS - {"full"}:
            raise bad("the request fingerprint is malformed")
        try:
            if "response" in event:
                response_from_dict(event["response"])
            elif "error" in event:
                error_from_dict(event["error"])
        except CodecError as exc:
            raise bad(str(exc)) from None
    elif keys != wanted:
        raise bad(f"a {kind} event has the wrong fields (missing {sorted(wanted - keys)}, unexpected {sorted(keys - wanted)})")
