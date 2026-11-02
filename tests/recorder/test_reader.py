import json
import shutil

import pytest
from rec_helpers import load_recording, recorded_run, text_response, tool_call_response

from bugbite.adapter import Usage
from bugbite.recorder import EVENTS, MANIFEST, RecordingError

USAGE = dict(usage=Usage(10, 5))


@pytest.fixture
def good(tmp_path, provider):
    script = [tool_call_response(("echo", {"text": "hi"}), **USAGE), text_response("done", **USAGE)]
    result, recording, _, _ = recorded_run(tmp_path, provider, script)
    copy = tmp_path / "copies" / recording.path.name  # keep the folder name, which the manifest records
    shutil.copytree(recording.path, copy)
    return copy


def edit_manifest(folder, **changes):
    path = folder / MANIFEST
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def edit_events(folder, fn):
    path = folder / EVENTS
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n" for e in fn(lines)))


def test_a_good_recording_loads(good):
    rec = load_recording(good)
    assert rec.complete and rec.warnings == () and len(rec.events) == 6 and rec.path == good


@pytest.mark.parametrize("name, damage, where, fragment", [
    ("no manifest", lambda f: (f / MANIFEST).unlink(), MANIFEST, "missing"),
    ("no events", lambda f: (f / EVENTS).unlink(), EVENTS, "missing"),
    ("manifest not JSON", lambda f: (f / MANIFEST).write_text("{nope"), MANIFEST, "not valid JSON"),
    ("manifest not an object", lambda f: (f / MANIFEST).write_text("[]"), MANIFEST, "bugbite-recording"),
    ("another format", lambda f: edit_manifest(f, format="other"), MANIFEST, "bugbite-recording"),
    ("a newer version", lambda f: edit_manifest(f, format_version=2), MANIFEST, "version 2"),
    ("no version", lambda f: edit_manifest(f, format_version=None), MANIFEST, "not supported"),
    ("an unknown status", lambda f: edit_manifest(f, status="done"), MANIFEST, "unknown status"),
    ("a hash mismatch", lambda f: edit_manifest(f, events_sha256="0" * 64), EVENTS, "hash and size"),
    ("a size mismatch", lambda f: edit_manifest(f, events_bytes=1), EVENTS, "hash and size"),
    ("a counts mismatch", lambda f: edit_manifest(f, counts={"events": 6, "model_calls": 9, "tool_calls": 1}), MANIFEST, "counts"),
    ("a changed byte", lambda f: (f / EVENTS).write_bytes((f / EVENTS).read_bytes().replace(b"done", b"dome", 1)), EVENTS, "hash and size"),
])
def test_damage_to_a_complete_recording_is_an_error_naming_the_file(good, name, damage, where, fragment):
    damage(good)
    with pytest.raises(RecordingError) as info:
        load_recording(good)
    assert where in str(info.value) and fragment in str(info.value) and str(good) in str(info.value), name


@pytest.mark.parametrize("name, change, fragment", [
    ("a gap in the numbers", lambda lines: [e for e in lines if e["seq"] != 3], "sequence number 4 where 3 was expected"),
    ("events out of order", lambda lines: [lines[1], lines[0]] + lines[2:], "sequence number 2 where 1 was expected"),
    ("a repeated number", lambda lines: lines[:1] + lines[:1] + lines[1:], "sequence number 1 where 2"),
    ("an unknown event type", lambda lines: [dict(lines[0], type="mystery")] + lines[1:], "unknown event type 'mystery'"),
    ("a missing field", lambda lines: [{k: v for k, v in e.items() if k != "step"} if e["type"] == "step" else e for e in lines], "wrong fields"),
    ("an extra field", lambda lines: [dict(e, extra=1) if e["type"] == "step" else e for e in lines], "wrong fields"),
    ("a model_call with no outcome", lambda lines: [{k: v for k, v in lines[0].items() if k != "response"}] + lines[1:], "exactly one of"),
    ("a model_call with two outcomes", lambda lines: [dict(lines[0], exception="X")] + lines[1:], "exactly one of"),
    ("a broken response", lambda lines: [dict(lines[0], response={"blocks": []})] + lines[1:], "response"),
    ("a malformed fingerprint", lambda lines: [dict(lines[0], request={"sha256": "x"})] + lines[1:], "fingerprint"),
    ("not an event", lambda lines: ["text"] + lines[1:], "not an event object"),
])
def test_damage_inside_the_events_is_found_even_when_the_hash_is_not_checked(good, name, change, fragment):
    edit_manifest(good, status="incomplete", reason="test")  # so only the structure of the events is under test
    edit_events(good, change)
    with pytest.raises(RecordingError, match="events.jsonl: line") as info:
        load_recording(good)
    assert fragment in str(info.value), name


def test_a_line_that_is_not_json_in_the_middle_is_an_error_but_a_torn_last_line_is_not(good):
    edit_manifest(good, status="incomplete", reason="test")
    raw = (good / EVENTS).read_text().splitlines()
    (good / EVENTS).write_text("\n".join(raw[:2] + ["{not json"] + raw[2:]) + "\n")
    with pytest.raises(RecordingError, match="line 3 is not valid JSON"):
        load_recording(good)
    (good / EVENTS).write_text("\n".join(raw[:2]) + '\n{"seq": 3, "ty')
    rec = load_recording(good)
    assert len(rec.events) == 2 and any("cut off" in w for w in rec.warnings)


def test_a_torn_line_in_a_recording_that_claims_to_be_complete_is_an_error(good):
    (good / EVENTS).write_text((good / EVENTS).read_text() + '{"seq": 7, "ty')
    with pytest.raises(RecordingError):
        load_recording(good)


def test_a_renamed_folder_is_noticed(good, tmp_path):
    renamed = tmp_path / "renamed"
    shutil.move(good, renamed)
    rec = load_recording(renamed)
    assert rec.complete and any("renamed" in w and "run_id" in w for w in rec.warnings)


def test_partial_recordings_load_with_a_warning(tmp_path, provider):
    result, recording, _, _ = recorded_run(tmp_path, provider, [text_response("done", **USAGE)])
    edit_manifest(recording.path, status="recording", finished_at=None)  # as a crashed run would have left it
    rec = load_recording(recording.path)
    assert rec.complete is False and any("recording is recording" in w for w in rec.warnings) and rec.finish() is not None
