"""Spotting an agent that is going round in circles (README FR5.5).

Two exact rules, fed one executed tool run at a time:
- repeated call: the same tool with the same arguments gave the same result again and again;
- repeated failed edit: edit_file keeps failing on the same file, even with different text.
A successful edit changes the repository, so it starts all counts again. At the first threshold the model
gets a nudge; at the second the loop stops. Nothing here uses a model, a clock or randomness.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .tools.paths import PathRejected, clean_relative
from .types import ToolRun

OK, NUDGE, STOP, RESET = "ok", "nudge", "stop", "reset"
RULE_REPEAT = "repeated_call"
RULE_EDIT = "repeated_failed_edit"
_RANK = {OK: 0, RESET: 0, NUDGE: 1, STOP: 2}
_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.\-/ ]")


@dataclass(frozen=True)
class LoopPolicy:
    repeat_nudge: int = 3  # the same call with the same result, seen this many times
    repeat_stop: int = 5
    edit_fail_nudge: int = 4  # failed edits to one file since the last successful edit
    edit_fail_stop: int = 6

    def __post_init__(self) -> None:
        for name in ("repeat_nudge", "repeat_stop", "edit_fail_nudge", "edit_fail_stop"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                raise ValueError(f"{name} must be an integer of at least 2, got {value!r}")
        if self.repeat_stop <= self.repeat_nudge:
            raise ValueError("repeat_stop must be greater than repeat_nudge")
        if self.edit_fail_stop <= self.edit_fail_nudge:
            raise ValueError("edit_fail_stop must be greater than edit_fail_nudge")


DEFAULT_LOOP_POLICY = LoopPolicy()


@dataclass(frozen=True)
class Signal:
    """`kind` is ok, nudge, stop, or reset (a successful edit: earlier signals in the same step no longer apply)."""

    kind: str
    rule: str | None = None
    detail: str = ""  # a sentence for the result when the run stops
    note: str = ""  # the text for the model when it is nudged


NO_SIGNAL = Signal(OK)


def stronger(a: Signal, b: Signal) -> Signal:
    return b if _RANK[b.kind] > _RANK[a.kind] else a


def _safe(text: object, limit: int) -> str:
    """Model-supplied text made safe to show again: plain characters only, and short."""
    clean = _NAME_CHARS.sub("?", str(text))
    return clean if len(clean) <= limit else clean[:limit] + "..."


def _edit_path(arguments: dict) -> str:
    raw = arguments.get("path", "")
    if not isinstance(raw, str):
        return ""
    try:
        return clean_relative(raw)
    except PathRejected:
        return raw.strip()


class LoopDetector:
    def __init__(self, policy: LoopPolicy = DEFAULT_LOOP_POLICY) -> None:
        self.policy = policy
        self._calls: dict[tuple, int] = {}
        self._edits: dict[str, int] = {}

    def observe(self, run: ToolRun) -> Signal:
        if not run.executed:
            return NO_SIGNAL
        call, output = run.call, run.output
        if call.name == "edit_file" and not output.is_error:  # the repository changed: start again
            self._calls.clear()
            self._edits.clear()
            return Signal(RESET)
        key = (
            call.name,
            json.dumps(call.arguments, sort_keys=True, default=str),
            output.is_error,
            hashlib.sha256(output.text.encode("utf-8", "replace")).hexdigest(),
        )
        self._calls[key] = count = self._calls.get(key, 0) + 1
        found = NO_SIGNAL
        name = _safe(call.name, 64)
        if count >= self.policy.repeat_stop:
            found = Signal(
                STOP, RULE_REPEAT,
                detail=f"Stopped: the same {name} call returned the same result {count} times with no change to the repository.",
            )
        elif count == self.policy.repeat_nudge:
            found = Signal(
                NUDGE, RULE_REPEAT,
                note=(
                    f"You have now made the same {name} call {count} times and got the same result each time, and "
                    "nothing in the repository has changed. Do not repeat it. Try something different: look at other "
                    "files, search for something else, or make a different change. If you cannot make progress, "
                    "say so in your final answer."
                ),
            )
        if call.name == "edit_file" and output.is_error:
            path = _edit_path(call.arguments)
            self._edits[path] = failed = self._edits.get(path, 0) + 1
            shown = _safe(path, 100)
            if failed >= self.policy.edit_fail_stop:
                found = stronger(found, Signal(
                    STOP, RULE_EDIT,
                    detail=f"Stopped: {failed} edits to {shown} failed with no successful edit in between.",
                ))
            elif failed == self.policy.edit_fail_nudge:
                found = stronger(found, Signal(
                    NUDGE, RULE_EDIT,
                    note=(
                        f"{failed} attempts to edit {shown} have failed since your last successful edit. Use read_file "
                        "to copy the exact text from the file, change a smaller piece, or look at a different file. If "
                        "the file is protected, fix the source code instead. If you cannot make progress, say so in "
                        "your final answer."
                    ),
                ))
        return found
