"""The committed recordings made through the real adapters: they replay identically and rebuild byte for byte."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from make_adapter_goldens import PROMPT, RUN_IDS, build_adapter_golden
from real_adapter_helpers import BOTH, replay_real

from bugbite.recorder import EVENTS, MANIFEST, load_recording

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recordings"


@pytest.mark.parametrize("side", BOTH)
def test_the_committed_recording_replays_identically(side):
    path = FIXTURES / RUN_IDS[side]
    rec = load_recording(path)
    assert rec.complete and rec.warnings == () and rec.manifest["counts"] == {"events": 6, "model_calls": 2, "tool_calls": 1}
    replayed = replay_real(path, system_prompt=PROMPT)
    assert replayed.identical and replayed.divergence is None and not replayed.differences
    assert replayed.agent.final_text == "The bug is fixed." and replayed.agent.status == "finished"


def test_the_two_goldens_were_made_by_different_providers_but_agree_on_the_neutral_run():
    a, b = (load_recording(FIXTURES / RUN_IDS[s]) for s in BOTH)
    assert a.manifest["model"]["provider"] == "claude" and b.manifest["model"]["provider"] == "openai_compatible"
    assert [c.response.tool_calls[0].name if c.response.tool_calls else None for c in a.model_calls()] == ["echo", None]
    assert [c.response.tool_calls[0].name if c.response.tool_calls else None for c in b.model_calls()] == ["echo", None]
    assert a.finish()["final_text"] == b.finish()["final_text"]


@pytest.mark.parametrize("side", BOTH)
def test_regenerating_it_gives_the_same_bytes(tmp_path, side):
    """If this fails an adapter's neutral output or the recording format changed. If on purpose: run make_adapter_goldens.py and commit."""
    folder = build_adapter_golden(tmp_path, side)
    for name in (EVENTS, MANIFEST):
        assert (folder / name).read_bytes() == (FIXTURES / RUN_IDS[side] / name).read_bytes(), name


@pytest.mark.parametrize("side", BOTH)
def test_no_secret_is_in_the_fixture(side):
    import real_adapter_helpers as h

    for file in (FIXTURES / RUN_IDS[side]).iterdir():
        assert h.SIDES[side].key not in file.read_text()


def test_the_fixtures_are_not_hidden_by_gitignore():
    if shutil.which("git") is None:
        return
    files = [str(FIXTURES / RUN_IDS[s] / n) for s in BOTH for n in (EVENTS, MANIFEST)]
    done = subprocess.run(["git", "check-ignore", "-q", *files], cwd=FIXTURES, capture_output=True)
    if done.returncode == 128:
        return
    assert done.returncode == 1, "a .gitignore rule hides the adapter golden recordings"
