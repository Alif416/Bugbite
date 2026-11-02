import json
import os
import stat
import threading

import pytest
from rec_helpers import fake_clocks

from bugbite.recorder import EVENTS, FORMAT, FORMAT_VERSION, MANIFEST, RecordingError, RunWriter, load_recording

SECRET = "SECRET-TOKEN-8f3a"


def make(tmp_path, **kw):
    wall, mono = fake_clocks()
    base = {"bugbite": {"commit": "c" * 40}, "note": "m"}
    return RunWriter(tmp_path / "rec", kw.pop("manifest", base), wall_clock=kw.pop("wall_clock", wall), monotonic=kw.pop("monotonic", mono), **kw)


def lines(writer):
    return [json.loads(line) for line in (writer.path / EVENTS).read_text().splitlines()]


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_the_layout_names_and_permissions(tmp_path):
    w = make(tmp_path, run_id="20270101T000000Z-abc12345")
    assert w.path == tmp_path / "rec" / "20270101T000000Z-abc12345" and sorted(p.name for p in w.path.iterdir()) == [EVENTS, MANIFEST]
    assert mode(w.path) == 0o700 and mode(w.path / EVENTS) == 0o600 and mode(w.path / MANIFEST) == 0o600
    m = json.loads((w.path / MANIFEST).read_text())
    assert (m["format"], m["format_version"], m["status"], m["run_id"], m["finished_at"]) == (FORMAT, FORMAT_VERSION, "recording", w.run_id, None)
    assert m["created_at"].endswith("Z") and m["bugbite"]["commit"] == "c" * 40
    w.finish()
    assert mode(w.path / MANIFEST) == 0o600 and mode(w.path / EVENTS) == 0o600


def test_run_ids_sort_by_time_and_do_not_collide(tmp_path):
    ids = {make(tmp_path).run_id for _ in range(20)}
    assert len(ids) == 20 and all(len(i) == len("20270101T000000Z-abc12345") and i[8] == "T" for i in ids)


def test_an_existing_folder_is_refused_and_never_overwritten(tmp_path):
    first = make(tmp_path, run_id="same")
    first.write({"type": "step", "step": 1, "model_calls": []})
    with pytest.raises(RecordingError, match="already exists"):
        make(tmp_path, run_id="same")
    assert len(lines(first)) == 1  # the first recording is intact


def test_an_uncreatable_folder_is_a_recording_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(RecordingError, match="cannot create"):
        RunWriter(blocker / "sub", {})


def test_events_get_contiguous_sequence_numbers_and_times(tmp_path):
    w = make(tmp_path)
    for i in range(5):
        assert w.write({"type": "step", "step": i + 1, "model_calls": [i]}) is True
    events = lines(w)
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5] and [e["t"] for e in events] == [0.5, 1.0, 1.5, 2.0, 2.5]
    assert all(line.endswith("}") for line in (w.path / EVENTS).read_text().splitlines())


def test_eight_threads_writing_keep_every_line_whole_and_the_numbers_contiguous(tmp_path):
    w = make(tmp_path)

    def work(n):
        for i in range(100):
            w.write({"type": "step", "step": n * 1000 + i, "model_calls": [], "pad": "x" * 200})

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    events = lines(w)
    assert len(events) == 800 and [e["seq"] for e in events] == list(range(1, 801)) and w.errors == 0
    assert len({e["step"] for e in events}) == 800


def test_the_manifest_is_replaced_atomically(tmp_path, monkeypatch):
    w = make(tmp_path)
    seen = {}
    real = os.replace

    def spy(src, dst):
        seen["src"], seen["dst"] = os.path.basename(src), os.path.basename(dst)
        seen["old_manifest_valid"] = json.loads((w.path / MANIFEST).read_text())["status"] == "recording"  # not yet half-replaced
        seen["tmp_valid"] = json.loads(open(src).read())["status"] == "complete"  # the new one is complete before it is swapped in
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    w.finish({"status": "finished"})
    assert seen == {"src": "manifest.json.tmp", "dst": "manifest.json", "old_manifest_valid": True, "tmp_valid": True}
    assert not (w.path / "manifest.json.tmp").exists()


def test_finish_records_counts_hash_and_outcome(tmp_path):
    import hashlib

    w = make(tmp_path)
    w.write({"type": "model_call", "call": 1, "request": {}, "exception": "X"})
    w.write({"type": "tool_call", "step": 1})
    w.write({"type": "tool_call", "step": 1})
    w.write({"type": "step", "step": 1, "model_calls": [1]})
    assert w.finish({"status": "finished"}) == "complete"
    m = json.loads((w.path / MANIFEST).read_text())
    raw = (w.path / EVENTS).read_bytes()
    assert m["status"] == "complete" and m["outcome"] == {"status": "finished"} and m["reason"] is None and m["finished_at"].endswith("Z")
    assert m["counts"] == {"events": 4, "model_calls": 1, "tool_calls": 2} and m["events_sha256"] == hashlib.sha256(raw).hexdigest() and m["events_bytes"] == len(raw)
    assert w.finish() == "complete" and w.write({"type": "step"}) is False  # finishing twice does nothing; nothing is written afterwards


def test_abort_marks_the_recording_incomplete_with_the_reason(tmp_path):
    w = make(tmp_path)
    w.write({"type": "step", "step": 1, "model_calls": []})
    assert w.abort("the process was told to stop") == "incomplete"
    m = json.loads((w.path / MANIFEST).read_text())
    assert m["status"] == "incomplete" and m["reason"] == "the process was told to stop" and m["counts"]["events"] == 1


def test_a_secret_is_scrubbed_from_events_and_manifest(tmp_path):
    w = make(tmp_path, scrub=lambda t: t.replace(SECRET, "[key]"), manifest={"task": {"text": f"task {SECRET}"}, f"k{SECRET}": [SECRET]})
    w.write({"type": "tool_call", "call": {"arguments": {f"a{SECRET}": f"v {SECRET}"}}, "output": f"out {SECRET}"})
    w.finish({"error_message": f"provider said {SECRET}"})
    blob = (w.path / EVENTS).read_text() + (w.path / MANIFEST).read_text()
    assert SECRET not in blob and "[key]" in blob


def test_an_unwritable_disk_is_counted_never_raised_and_the_recording_says_incomplete(tmp_path):
    w = make(tmp_path)

    class Full:
        def write(self, text):
            raise OSError("disk full")

        def flush(self):
            pass

        def close(self):
            pass

    real = w._fh
    w._fh = Full()
    assert w.write({"type": "step", "step": 1, "model_calls": []}) is False
    assert w.errors == 1 and w.last_error == "OSError" and "disk full" not in repr(w.last_error)
    w._fh = real  # the disk comes back
    assert w.write({"type": "step", "step": 2, "model_calls": []}) is True
    assert [e["seq"] for e in lines(w)] == [1]  # the failed write did not use up a number: no gap
    assert w.finish({}) == "incomplete" and json.loads((w.path / MANIFEST).read_text())["reason"].startswith("1 recording problem(s)")
    assert load_recording(w.path).complete is False


def test_values_that_cannot_be_written_are_counted_not_raised(tmp_path):
    w = make(tmp_path)
    assert w.write({"type": "step", "x": float("nan")}) is False and w.write({"type": "step", "x": object()}) is False
    assert w.errors == 2 and w.write({"type": "step", "step": 1, "model_calls": []}) is True


def test_the_size_cap_stops_recording_cleanly(tmp_path):
    w = make(tmp_path, max_bytes=1500)
    results = [w.write({"type": "step", "step": i, "model_calls": [], "pad": "y" * 100}) for i in range(40)]
    assert results.count(True) < 15 and results[-1] is False and w.errors > 0
    assert (w.path / EVENTS).stat().st_size <= 1500
    assert w.finish({}) == "incomplete" and "size limit" in json.loads((w.path / MANIFEST).read_text())["reason"]


def test_a_crashed_run_leaves_a_readable_partial_recording(tmp_path):
    w = make(tmp_path)
    w.write({"type": "step", "step": 1, "model_calls": []})
    loaded = load_recording(w.path)  # never finished: the process "died"
    assert loaded.complete is False and loaded.manifest["status"] == "recording" and len(loaded.events) == 1
    assert any("recording" in warning for warning in loaded.warnings)
    with open(w.path / EVENTS, "a") as handle:
        handle.write('{"seq": 2, "type": "ste')  # the process died in the middle of a line
    torn = load_recording(w.path)
    assert len(torn.events) == 1 and any("cut off" in warning for warning in torn.warnings)
