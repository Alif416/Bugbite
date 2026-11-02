"""A scripted run through the real chain, recorded, then read back and compared with what really happened."""

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest
from rec_helpers import FIXED_ENV, AdapterError, FakeTools, Limits, load_recording, recorded_run, text_response, tool_call_response

from bugbite.adapter import Usage
from bugbite.adapter.codec import request_fingerprint, request_to_dict
from bugbite.agent import SYSTEM_PROMPT
from bugbite.agent.tools import TOOLS_VERSION, ToolOutput
from bugbite.privacy import Sensitivity
from bugbite.recorder import start as start_module

USAGE = dict(usage=Usage(10, 5))
SECRET = "SECRET-TOKEN-8f3a"


def load(recording):
    return load_recording(recording.path)


def test_a_finished_run_is_recorded_event_by_event(tmp_path, provider):
    tools = FakeTools(outputs={"echo": ToolOutput("echoed")})
    script = [tool_call_response(("echo", {"text": "hi"}), text="looking", **USAGE), text_response("Fixed.", **USAGE)]
    result, recording, ledger, raw = recorded_run(tmp_path, provider, script, tools=tools)
    rec = load(recording)
    assert rec.complete and rec.warnings == () and rec.manifest["status"] == "complete"
    assert [e["type"] for e in rec.events] == ["model_call", "step", "tool_call", "model_call", "step", "finish"]
    calls = rec.model_calls()
    assert [c.call for c in calls] == [1, 2] and len(calls) == len(raw.calls)
    for record, request in zip(calls, raw.calls):
        assert record.request == request_fingerprint(request) and "full" not in record.request  # a fingerprint of exactly what was sent
    assert calls[0].response.text == "looking" and calls[0].response.tool_calls[0].arguments == {"text": "hi"} and calls[1].response.text == "Fixed."
    assert calls[0].response.usage == Usage(10, 5) and calls[0].error is None
    assert [s["model_calls"] for s in rec.steps()] == [[1], [2]] and [s["step"] for s in rec.steps()] == [1, 2]
    [tool] = rec.tool_calls()
    assert (tool["step"], tool["position"], tool["call"], tool["output"], tool["executed"]) == (1, 1, {"id": "call_1", "name": "echo", "arguments": {"text": "hi"}}, {"text": "echoed", "is_error": False}, True)
    finish = rec.finish()
    assert finish["final_text"] == "Fixed." and finish["unassigned_model_calls"] == [] and finish["nudges"] == {}
    assert finish["outcome"] == {
        "status": "finished", "error_code": None, "error_message": None, "limit_detail": None, "steps": 2, "nudges": 0,
        "usage": {"input_tokens": 20, "output_tokens": 10, "cache_read_tokens": 0, "cache_write_tokens": 0},
        "cost_usd": "0.04", "elapsed_s": result.elapsed_s, "observer_errors": 0,
    }
    assert rec.manifest["outcome"] == finish["outcome"]
    assert [e["seq"] for e in rec.events] == list(range(1, 7)) and rec.manifest["counts"] == {"events": 6, "model_calls": 2, "tool_calls": 1}


def test_failed_attempts_are_recorded_and_belong_to_the_step_that_retried_them(tmp_path, provider):
    slow = AdapterError("rate_limited", "slow", retry_after_s=2, status_code=429)
    result, recording, ledger, raw = recorded_run(tmp_path, provider, [slow, tool_call_response(("echo", {}), **USAGE), text_response("done", **USAGE)], retry=True)
    rec = load(recording)
    calls = rec.model_calls()
    assert [(c.call, c.error is not None) for c in calls] == [(1, True), (2, False), (3, False)] and len(raw.calls) == 3
    assert (calls[0].error.code, calls[0].error.retry_after_s, calls[0].error.status_code) == ("rate_limited", 2, 429)
    assert [s["model_calls"] for s in rec.steps()] == [[1, 2], [3]]
    assert len(ledger.calls) == 3  # the cost ledger and the recording agree on how many provider calls there were


def test_a_failure_after_the_last_reply_is_listed_in_the_finish_event(tmp_path, provider):
    result, recording, ledger, raw = recorded_run(tmp_path, provider, [tool_call_response(("echo", {}), **USAGE), AdapterError("auth_failed", "bad key")])
    rec = load(recording)
    assert [s["model_calls"] for s in rec.steps()] == [[1]] and rec.finish()["unassigned_model_calls"] == [2]
    assert rec.model_calls()[1].error.code == "auth_failed" and rec.finish()["outcome"]["status"] == "model_error"
    assert rec.finish()["outcome"]["error_code"] == "auth_failed" and rec.finish()["outcome"]["error_message"] == "bad key"


def test_a_text_action_repair_is_two_provider_calls_in_one_step(tmp_path, provider):
    action = '{"tool": "echo", "arguments": {"text": "x"}}'
    script = [text_response("hmm", **USAGE), text_response(action, **USAGE), text_response('{"final": "done"}', **USAGE)]
    result, recording, ledger, raw = recorded_run(tmp_path, provider, script, native=False)
    rec = load(recording)
    assert [s["model_calls"] for s in rec.steps()] == [[1, 2], [3]] and len(rec.model_calls()) == 3
    assert rec.model_calls()[0].response.text == "hmm"  # what the provider really said, before the wrapper repaired it


def test_nudges_are_in_the_finish_event(tmp_path, provider):
    script = [tool_call_response(("echo", {"text": "a"}), first_id=i, **USAGE) for i in range(1, 4)] + [text_response("stop", **USAGE)]
    result, recording, ledger, raw = recorded_run(tmp_path, provider, script)
    nudges = load(recording).finish()["nudges"]
    assert list(nudges) == ["3"] and "same echo call 3 times" in nudges["3"] and result.nudges == 1


def test_full_requests_are_stored_only_when_asked_and_match_what_was_sent(tmp_path, provider):
    script = lambda: [tool_call_response(("echo", {}), **USAGE), text_response("done", **USAGE)]
    _, plain, _, _ = recorded_run(tmp_path, provider, script())
    assert all("full" not in c.request for c in load(plain).model_calls()) and plain.writer.record_requests is False
    (tmp_path / "second").mkdir()
    _, full, _, raw = recorded_run(tmp_path / "second", provider, script(), record_requests=True)
    rec = load(full)
    assert rec.manifest["settings"]["record_requests"] is True
    for record, request in zip(rec.model_calls(), raw.calls):
        assert record.request["full"] == json.loads(json.dumps(request_to_dict(request)))
    assert (full.path / "events.jsonl").stat().st_size > (plain.path / "events.jsonl").stat().st_size


def test_a_refused_call_is_not_recorded_as_a_provider_call(tmp_path, provider):
    import rec_helpers
    from dataclasses import replace

    original = rec_helpers.model
    rec_helpers.model = lambda native=True, allow=True: replace(original(native), allow_private_code=False)  # a model that may not see private code
    try:
        result, recording, ledger, raw = recorded_run(tmp_path, provider, [text_response("never")], sensitivity=Sensitivity.PRIVATE)
    finally:
        rec_helpers.model = original
    rec = load(recording)
    assert result.status == "privacy_blocked" and rec.model_calls() == [] and [e["type"] for e in rec.events] == ["finish"]
    assert rec.finish()["outcome"]["error_code"] == "private_code_blocked" and rec.manifest["source"]["sensitivity"] == "private"


def test_the_manifest_has_everything_needed_to_trace_a_run(tmp_path, provider):
    result, recording, ledger, raw = recorded_run(tmp_path, provider, [text_response("done", **USAGE)], task="Fix the bug\nplease", limits=Limits(7, max_cost_usd="0.10", max_wall_clock_s=90))
    m = load(recording).manifest
    assert m["format"] == "bugbite-recording" and m["format_version"] == 1 and m["run_id"] == recording.run_id and m["status"] == "complete"
    assert m["bugbite"] == {"commit": "c" * 40, "dirty": False, **FIXED_ENV}
    assert m["model"]["name"] == "paid" and m["model"]["provider"] == "rec_fake" and m["model"]["context_window"] == 100_000
    assert m["model"]["native_tool_calling"] is True and m["model"]["max_output_tokens"] == 100 and m["model"]["allow_private_code"] is True
    assert m["model"]["pricing"]["input"] == "1000" and m["model"]["pricing"]["output"] == "2000" and m["model"]["api_key_env"] is None
    assert m["prompt"] == {"version": "1", "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "tools_version": TOOLS_VERSION}
    assert m["task"] == {"text": "Fix the bug\nplease", "sha256": hashlib.sha256(b"Fix the bug\nplease").hexdigest()}
    assert m["source"] == {"issue_url": "https://github.com/o/r/issues/1", "repo": "o/r", "ref": "a" * 40, "sensitivity": "public"}
    settings = m["settings"]
    assert settings["limits"] == {"max_steps": 7, "max_cost_usd": "0.10", "max_wall_clock_s": 90.0, "cost_margin": "1.25"}
    assert settings["loop_policy"] == {"repeat_nudge": 3, "repeat_stop": 5, "edit_fail_nudge": 4, "edit_fail_stop": 6} and settings["retry_policy"] is None
    assert m["created_at"] < m["finished_at"] and m["recording_errors"] == 0 and m["reason"] is None


def test_the_secret_is_in_no_file(tmp_path, provider):
    tools = FakeTools(outputs={"echo": ToolOutput(f"out {SECRET}")})
    script = [tool_call_response(("echo", {"text": f"arg {SECRET}"}), text=f"reply {SECRET}", **USAGE), AdapterError("invalid_request", f"echoed {SECRET}")]
    result, recording, _, _ = recorded_run(tmp_path, provider, script, tools=tools, scrub=lambda t: t.replace(SECRET, "[key]"), task=f"task {SECRET}")
    assert SECRET in result.messages[1].blocks[0].text
    for name in ("events.jsonl", "manifest.json"):
        assert SECRET not in (recording.path / name).read_text()
    assert "[key]" in (recording.path / "events.jsonl").read_text() and load(recording).manifest["task"]["text"] == "task [key]"


def test_a_broken_recording_never_changes_the_run(tmp_path, provider):
    script = lambda: [tool_call_response(("echo", {}), **USAGE), tool_call_response(("echo", {}), first_id=2, **USAGE), text_response("done", **USAGE)]
    result, recording, _, _ = recorded_run(tmp_path, provider, script())
    (tmp_path / "tiny").mkdir()
    broken, rec2, _, _ = recorded_run(tmp_path / "tiny", provider, script(), max_bytes=700)  # the size cap stops the recording early
    for attr in ("status", "final_text", "usage", "error_code", "limit_detail", "nudges", "cost_usd"):
        assert getattr(broken, attr) == getattr(result, attr)
    assert len(broken.steps) == len(result.steps) and broken.observer_errors == 0
    loaded = load(rec2)
    assert loaded.complete is False and loaded.manifest["status"] == "incomplete" and "size limit" in loaded.manifest["reason"] and rec2.writer.errors > 0


def test_recordings_are_byte_for_byte_repeatable_with_fixed_clocks(tmp_path, provider):
    import time
    import unittest.mock as mock

    def once(root):
        root.mkdir()
        ticks = iter(range(10_000))
        with mock.patch.object(time, "monotonic", lambda: next(ticks) * 0.25):  # the loop times tool calls with the real clock
            return recorded_run(root, provider, [tool_call_response(("echo", {"text": "a"}), **USAGE), text_response("done", **USAGE)],
                                run_id="20270101T000000Z-fixed001", clock=lambda: next(ticks) * 0.25)[1]

    a, b = once(tmp_path / "one"), once(tmp_path / "two")
    for name in ("events.jsonl", "manifest.json"):
        assert (a.path / name).read_bytes() == (b.path / name).read_bytes(), name


# -- where the commit comes from ------------------------------------------------------------------------------------------------------------


def git(path, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=path, check=True, capture_output=True)


def package_in(monkeypatch, repo, relative="src/bugbite"):
    pkg = repo / relative
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    monkeypatch.setattr(start_module, "bugbite", SimpleNamespace(__file__=str(pkg / "__init__.py")))


def test_the_commit_and_dirty_flag_come_from_the_bugbite_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    package_in(monkeypatch, repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert start_module.bugbite_commit_info() == (head, False)
    (repo / "src/bugbite/new.py").write_text("x = 1\n")
    assert start_module.bugbite_commit_info() == (head, True)  # an uncommitted file makes it dirty


def test_there_is_no_commit_outside_a_git_checkout_or_in_someone_elses_project(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    package_in(monkeypatch, plain)
    assert start_module.bugbite_commit_info() == (None, None)  # not a git repository
    other = tmp_path / "other_project"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    (other / "README").write_text("x")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "x")
    package_in(monkeypatch, other, ".venv/lib/python3.11/site-packages/bugbite")  # installed inside another project's checkout
    assert start_module.bugbite_commit_info() == (None, None)  # that project's commit must not be passed off as Bugbite's


def test_the_real_checkout_gives_a_real_commit():
    commit, dirty = start_module.bugbite_commit_info()
    assert commit is None or (len(commit) == 40 and set(commit) <= set("0123456789abcdef"))
    assert dirty in (True, False, None)


def test_the_default_environment_facts():
    env = start_module.default_environment()
    assert set(env) == {"version", "python", "platform"} and env["python"].count(".") >= 1


def test_the_observer_survives_a_writer_that_raises(tmp_path):
    from bugbite.agent import run_agent
    from bugbite.recorder import RunRecorder

    class Exploding:
        errors = []

        def take_unassigned_calls(self):
            raise RuntimeError("boom")

        def write(self, event):
            raise RuntimeError("boom")

        def finish(self, outcome=None, **kw):
            raise RuntimeError("boom")

        def note_error(self, exc):
            self.errors.append(type(exc).__name__)

    from loop_helpers import FakeTools, adapter, text_response, tool_call_response

    writer = Exploding()
    ad = adapter(tool_call_response(("echo", {})), text_response("done"))
    result = run_agent(ad, FakeTools(), "task", limits=Limits(5), observer=RunRecorder(writer))
    assert result.status == "finished" and result.observer_errors == 0  # the recorder absorbed it; the loop never saw an exception
    assert writer.errors == ["RuntimeError"] * 4  # two steps, one tool call and the finish
