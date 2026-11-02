"""Starting a recording: collect the facts that make it traceable (README FR10.4)."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import bugbite
from bugbite.agent.limits import Limits
from bugbite.agent.loopguard import DEFAULT_LOOP_POLICY, LoopPolicy
from bugbite.agent.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from bugbite.agent.tools.base import TOOLS_VERSION
from bugbite.config import ModelConfig

from .observer import RunRecorder
from .writer import DEFAULT_MAX_BYTES, RunWriter


def _identity(text: str) -> str:
    return text


def _plain(value: Any) -> Any:
    """Dataclasses, decimals and sets as plain JSON data."""
    return json.loads(json.dumps(dataclasses.asdict(value) if dataclasses.is_dataclass(value) and not isinstance(value, type) else value,
                                 default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o)))


def bugbite_commit_info() -> tuple[str | None, bool | None]:
    """(commit hash, working tree has uncommitted changes) of the Bugbite code, or (None, None) when it is not a git checkout."""
    package = Path(bugbite.__file__).resolve().parent

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=package, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() not in package.parents:  # a git checkout that is not Bugbite's own (for example a venv inside another project)
        return None, None
    if not (Path(top) / "src" / "bugbite").is_dir():
        return None, None
    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return commit, (None if status is None else bool(status))


def default_environment() -> dict[str, Any]:
    try:
        from importlib.metadata import version

        installed: str | None = version("bugbite")
    except Exception:
        installed = None
    return {"version": installed, "python": sys.version.split()[0], "platform": platform.platform()}


@dataclass(frozen=True)
class RecordingInfo:
    model: ModelConfig
    issue_url: str
    repo: str
    sensitivity: str
    task_text: str
    ref: str | None = None
    system_prompt: str = SYSTEM_PROMPT
    limits: Limits | None = None
    loop_policy: LoopPolicy | None = DEFAULT_LOOP_POLICY
    retry_policy: Any = None  # any dataclass or dict describing the retry settings
    extra: dict[str, Any] = field(default_factory=dict)  # for example the pre-step report


class Recording:
    """A started recording: `writer` for `create_adapter(recorder=...)`, `observer` for `run_agent(observer=...)`."""

    def __init__(self, writer: RunWriter) -> None:
        self.writer = writer
        self.observer = RunRecorder(writer)

    @property
    def path(self) -> Path:
        return self.writer.path

    @property
    def run_id(self) -> str:
        return self.writer.run_id

    def close(self) -> str:
        """Finish the recording if the run has not already finished it. Returns the final status."""
        return self.writer.finish(status="incomplete", reason="closed before the run finished")

    def abort(self, reason: str) -> str:
        return self.writer.abort(reason)


def start_recording(
    root: str | Path,
    info: RecordingInfo,
    *,
    scrub: Callable[[str], str] = _identity,
    record_requests: bool = False,
    commit_info: Callable[[], tuple[str | None, bool | None]] = bugbite_commit_info,
    environment: Callable[[], dict[str, Any]] = default_environment,
    wall_clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    max_bytes: int = DEFAULT_MAX_BYTES,
    run_id: str | None = None,
) -> Recording:
    """Create the recording folder and its manifest. Raises `RecordingError` if the folder cannot be created
    (before anything has run, so the caller can choose to go on without recording)."""
    commit, dirty = commit_info()
    manifest = {
        "bugbite": {"commit": commit, "dirty": dirty, **environment()},
        "model": _plain(info.model),
        "prompt": {"version": PROMPT_VERSION, "system_prompt_sha256": hashlib.sha256(info.system_prompt.encode("utf-8")).hexdigest(),
                   "tools_version": TOOLS_VERSION},
        "task": {"text": info.task_text, "sha256": hashlib.sha256(info.task_text.encode("utf-8")).hexdigest()},
        "source": {"issue_url": info.issue_url, "repo": info.repo, "ref": info.ref, "sensitivity": info.sensitivity},
        "settings": {
            "limits": None if info.limits is None else _plain(info.limits),
            "loop_policy": None if info.loop_policy is None else _plain(info.loop_policy),
            "retry_policy": None if info.retry_policy is None else _plain(info.retry_policy),
            "record_requests": record_requests,
        },
        "extra": _plain(info.extra),
    }
    writer = RunWriter(root, manifest, record_requests=record_requests, scrub=scrub, wall_clock=wall_clock, monotonic=monotonic,
                       max_bytes=max_bytes, run_id=run_id)
    return Recording(writer)
