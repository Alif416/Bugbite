"""Helpers: record a scripted run, replay it, and damage copies of recordings in controlled ways."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "recorder"))

from rec_helpers import (  # noqa: E402,F401
    AdapterError, FakeTools, Limits, ProviderState, Sensitivity, load_recording, recorded_run, text_response, tool_call_response,
)

from bugbite.adapter import Usage  # noqa: E402,F401
from bugbite.agent.tools import ToolOutput  # noqa: E402,F401
from bugbite.recorder.writer import EVENTS, MANIFEST  # noqa: E402
from bugbite.replayer import replay  # noqa: E402

USAGE = dict(usage=Usage(10, 5))


def record(tmp_path, provider, script, **kw):
    """Record a scripted run. Returns (the run's AgentResult, the recording folder)."""
    result, recording, _, _ = recorded_run(tmp_path, provider, script, **kw)
    return result, recording.path


def replay_it(path, **kw):
    """`replay` with the tool definitions the test tools use."""
    kw.setdefault("tool_definitions", FakeTools().definitions())
    return replay(path, **kw)


def tree_hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).iterdir())}


def edited_copy(src, dst, change=None, *, manifest_change=None):
    """Copy a recording, let `change(events)` edit its event list (renumbered, counted and hashed again, so it still loads as complete),
    and let `manifest_change(manifest)` edit the manifest."""
    src = Path(src)
    dst = Path(dst) / src.name  # same folder name as the original, so the reader has nothing to warn about
    shutil.copytree(src, dst)
    manifest = json.loads((dst / MANIFEST).read_text())
    events = [json.loads(line) for line in (dst / EVENTS).read_text().splitlines()]
    if change is not None:
        events = change(events) or events
        for number, event in enumerate(events, 1):
            event["seq"] = number
        raw = ("".join(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for e in events)).encode()
        (dst / EVENTS).write_bytes(raw)
        manifest["events_sha256"], manifest["events_bytes"] = hashlib.sha256(raw).hexdigest(), len(raw)
        manifest["counts"] = {"events": len(events), "model_calls": sum(e["type"] == "model_call" for e in events),
                              "tool_calls": sum(e["type"] == "tool_call" for e in events)}
    if manifest_change is not None:
        manifest_change(manifest)
    (dst / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return dst


def make_partial(src, dst, keep):
    """A copy that looks like a run that crashed after `keep` events."""
    src = Path(src)
    dst = Path(dst) / src.name
    shutil.copytree(src, dst)
    lines = (dst / EVENTS).read_text().splitlines()[:keep]
    (dst / EVENTS).write_text("".join(line + "\n" for line in lines))
    manifest = json.loads((dst / MANIFEST).read_text())
    for key in ("events_sha256", "events_bytes", "counts", "outcome"):
        manifest.pop(key, None)
    manifest.update(status="incomplete", reason="test: cut short")
    (dst / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return dst
