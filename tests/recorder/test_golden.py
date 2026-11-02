"""The committed version-1 recording: reading it, and regenerating it byte for byte, pins the format down."""

import hashlib
from pathlib import Path

from make_golden import RUN_ID, build_golden

from bugbite.adapter import GenerationResponse, TextBlock, ToolCallBlock, Usage
from bugbite.recorder import EVENTS, MANIFEST, load_recording

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "recordings" / RUN_ID


def test_the_committed_recording_loads_and_its_hash_matches():
    rec = load_recording(GOLDEN)
    assert rec.complete and rec.warnings == () and rec.manifest["run_id"] == RUN_ID
    raw = (GOLDEN / EVENTS).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == rec.manifest["events_sha256"] and len(raw) == rec.manifest["events_bytes"]
    assert rec.manifest["counts"] == {"events": 6, "model_calls": 2, "tool_calls": 1}


def test_its_contents_are_exactly_what_was_recorded():
    rec = load_recording(GOLDEN)
    calls = rec.model_calls()
    assert [c.call for c in calls] == [1, 2]
    assert calls[0].response == GenerationResponse(
        (TextBlock("Let me look."), ToolCallBlock("call_1", "echo", {"text": "golden"})), "tool_use", Usage(12, 7, 3, 1), "scripted-model", "tool_use")
    assert calls[1].response == GenerationResponse((TextBlock("The bug is fixed."),), "end_turn", Usage(20, 9), "scripted-model", "end_turn")
    assert [s["model_calls"] for s in rec.steps()] == [[1], [2]]
    [tool] = rec.tool_calls()
    assert (tool["call"], tool["output"], tool["duration_s"]) == ({"id": "call_1", "name": "echo", "arguments": {"text": "golden"}}, {"text": "echoed: golden", "is_error": False}, 0.25)
    finish = rec.finish()
    assert finish["final_text"] == "The bug is fixed." and finish["outcome"]["status"] == "finished" and finish["outcome"]["cost_usd"] == "0.068"
    m = rec.manifest
    assert (m["format"], m["format_version"], m["bugbite"]["commit"], m["task"]["text"]) == ("bugbite-recording", 1, "c" * 40, "Fix the golden bug.")
    assert m["source"]["sensitivity"] == "public" and m["settings"]["limits"]["max_steps"] == 6 and m["prompt"]["version"] == "1"


def test_regenerating_it_gives_the_same_bytes(tmp_path):
    """If this fails the recording format changed. If that was on purpose: bump FORMAT_VERSION, run make_golden.py, commit."""
    folder = build_golden(tmp_path)
    for name in (EVENTS, MANIFEST):
        assert (folder / name).read_bytes() == (GOLDEN / name).read_bytes(), name


def test_every_request_fingerprint_in_it_is_well_formed():
    for record in load_recording(GOLDEN).model_calls():
        fp = record.request
        assert len(fp["sha256"]) == 64 and fp["bytes"] > 0 and fp["messages"] >= 1 and fp["tools"] == 2 and fp["system_blocks"] == 1


def test_the_fixture_is_not_hidden_by_gitignore():
    """A .gitignore rule for recordings/ once hid this folder, so a fresh clone had no golden recording."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        return
    done = subprocess.run(["git", "check-ignore", "-q", str(GOLDEN / EVENTS), str(GOLDEN / MANIFEST)], cwd=GOLDEN, capture_output=True)
    if done.returncode == 128:  # not inside a git checkout (for example an exported source tree)
        return
    assert done.returncode == 1, "the golden recording is ignored by git"
