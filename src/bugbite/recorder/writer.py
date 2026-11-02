"""Writing a recording to disk: a folder with a manifest and an append-only event log (AD-117, AD-120)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bugbite.adapter.codec import scrub_value

FORMAT = "bugbite-recording"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
EVENTS = "events.jsonl"
DEFAULT_MAX_BYTES = 200 * 1024 * 1024


class RecordingError(Exception):
    """A recording cannot be created or is damaged. The message names the file and the problem."""


def _identity(text: str) -> str:
    return text


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_run_id(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)


class RunWriter:
    """Writes one recording. Thread-safe. After construction nothing here raises: problems are counted.

    It satisfies `bugbite.adapter.recording.RecordingSink`, so it can be handed to `create_adapter`.
    """

    def __init__(
        self,
        root: str | Path,
        manifest: dict[str, Any],
        *,
        record_requests: bool = False,
        scrub: Callable[[str], str] = _identity,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        max_bytes: int = DEFAULT_MAX_BYTES,
        run_id: str | None = None,
    ) -> None:
        self.record_requests = record_requests
        self._scrub = scrub
        self._wall, self._mono, self._max_bytes = wall_clock, monotonic, max_bytes
        self._lock = threading.Lock()
        self.errors = 0
        self.last_error: str | None = None  # the kind of the last problem, never its text
        self._seq = self._bytes = self._calls = self._assigned = 0
        self._counts = {"model_call": 0, "tool_call": 0}
        self._stopped: str | None = None
        self._finished = False
        started = self._wall()
        self.run_id = run_id or new_run_id(started)
        self.root = Path(root)
        self.path = self.root / self.run_id
        self._started_mono = self._mono()
        self._manifest: dict[str, Any] = scrub_value(
            {"format": FORMAT, "format_version": FORMAT_VERSION, "run_id": self.run_id, "created_at": _iso(started),
             "finished_at": None, "status": "recording", **manifest}, scrub)
        try:
            os.makedirs(self.root, exist_ok=True)
            os.mkdir(self.path, 0o700)
            os.chmod(self.path, 0o700)
            fd = os.open(self.path / EVENTS, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
            self._fh: Any = os.fdopen(fd, "a", encoding="utf-8", newline="\n")
            self._write_manifest()
        except FileExistsError:
            raise RecordingError(f"{self.path}: the recording folder already exists") from None
        except OSError as exc:
            raise RecordingError(f"{self.path}: cannot create the recording ({type(exc).__name__})") from None

    # -- the sink interface -------------------------------------------------------------------------------------------------------

    def next_call_number(self) -> int:
        with self._lock:
            self._calls += 1
            return self._calls

    def take_unassigned_calls(self) -> list[int]:
        """The provider call numbers handed out since the last time this was called (they belong to one loop step)."""
        with self._lock:
            numbers = list(range(self._assigned + 1, self._calls + 1))
            self._assigned = self._calls
            return numbers

    def note_error(self, exc: BaseException) -> None:
        with self._lock:
            self.errors += 1
            self.last_error = type(exc).__name__

    def write(self, event: dict[str, Any]) -> bool:
        """Append one event. Returns False (and counts a problem) if it could not be written."""
        with self._lock:
            if self._finished or self._stopped:
                return False
            try:
                record = scrub_value({"seq": self._seq + 1, "t": round(max(0.0, self._mono() - self._started_mono), 6), **event}, self._scrub)
                line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
                size = len(line.encode("utf-8"))
                if self._bytes + size > self._max_bytes:
                    self._stopped = f"the size limit of {self._max_bytes} bytes was reached"
                    self.errors += 1
                    self.last_error = "SizeLimit"
                    return False
                self._fh.write(line)
                self._fh.flush()
            except Exception as exc:  # disk full, permissions, a value that cannot be written: a record, not part of the work
                self.errors += 1
                self.last_error = type(exc).__name__
                return False
            self._seq += 1
            self._bytes += size
            kind = record.get("type")
            if kind in self._counts:
                self._counts[kind] += 1
            return True

    # -- the manifest --------------------------------------------------------------------------------------------------------------------

    def _write_manifest(self) -> None:
        data = json.dumps(self._manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        tmp = self.path / (MANIFEST + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path / MANIFEST)  # a reader sees the old manifest or the new one, never half of one

    def finish(self, outcome: dict[str, Any] | None = None, *, status: str | None = None, reason: str | None = None) -> str:
        """Close the recording and write the final manifest. Returns the status. Calling it again does nothing."""
        with self._lock:
            if self._finished:
                return self._manifest["status"]
            self._finished = True
            try:
                self._fh.close()
            except OSError as exc:
                self.errors += 1
                self.last_error = type(exc).__name__
            problems = self._stopped or (f"{self.errors} recording problem(s), last: {self.last_error}" if self.errors else None)
            final = status or ("incomplete" if problems else "complete")
            why = reason or (problems if final == "incomplete" else None)
            update: dict[str, Any] = {"finished_at": _iso(self._wall()), "status": final, "reason": why,
                                      "counts": {"events": self._seq, "model_calls": self._counts["model_call"], "tool_calls": self._counts["tool_call"]},
                                      "recording_errors": self.errors}
            if outcome is not None:
                update["outcome"] = outcome
            try:
                raw = (self.path / EVENTS).read_bytes()
                update["events_sha256"], update["events_bytes"] = hashlib.sha256(raw).hexdigest(), len(raw)
            except OSError as exc:
                self.errors += 1
                self.last_error = type(exc).__name__
                update.update(status="incomplete", reason="the events file could not be read back")
            self._manifest.update(scrub_value(update, self._scrub))
            try:
                self._write_manifest()
            except OSError as exc:
                self.errors += 1
                self.last_error = type(exc).__name__
            return self._manifest["status"]

    def abort(self, reason: str) -> str:
        return self.finish(status="incomplete", reason=reason)
