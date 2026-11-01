"""The loop detector on hand-built tool runs, and the policy."""

import pytest

from bugbite.adapter.types import ToolCallBlock
from bugbite.agent import DEFAULT_LOOP_POLICY, LoopDetector, LoopPolicy
from bugbite.agent.loopguard import NUDGE, OK, RESET, RULE_EDIT, RULE_REPEAT, STOP
from bugbite.agent.tools import ToolOutput
from bugbite.agent.types import ToolRun


def run(name="read_file", args=None, text="same text", error=False, executed=True, call_id="c1"):
    return ToolRun(ToolCallBlock(call_id, name, args if args is not None else {"path": "a.py"}), ToolOutput(text, error), 0.0, executed)


def edit(path="a.py", old="x", new="y", error=True, text=None):
    return run("edit_file", {"path": path, "old_text": old, "new_text": new}, text if text is not None else ("not found" if error else "Edited"), error)


def kinds(detector, runs):
    return [detector.observe(r).kind for r in runs]


# -- policy ------------------------------------------------------------------------------------------------------------


def test_default_policy():
    assert (DEFAULT_LOOP_POLICY.repeat_nudge, DEFAULT_LOOP_POLICY.repeat_stop) == (3, 5)
    assert (DEFAULT_LOOP_POLICY.edit_fail_nudge, DEFAULT_LOOP_POLICY.edit_fail_stop) == (4, 6)


@pytest.mark.parametrize("field", ["repeat_nudge", "repeat_stop", "edit_fail_nudge", "edit_fail_stop"])
@pytest.mark.parametrize("bad", [1, 0, -3, True, 2.5, None, "3"])
def test_policy_values_must_be_integers_of_at_least_two(field, bad):
    with pytest.raises(ValueError, match=field):
        LoopPolicy(**{field: bad})


def test_stop_must_be_above_nudge():
    with pytest.raises(ValueError, match="repeat_stop"):
        LoopPolicy(repeat_nudge=4, repeat_stop=4)
    with pytest.raises(ValueError, match="edit_fail_stop"):
        LoopPolicy(edit_fail_nudge=5, edit_fail_stop=3)
    assert LoopPolicy(repeat_nudge=2, repeat_stop=3, edit_fail_nudge=2, edit_fail_stop=3)


# -- rule 1: the same call, the same result ------------------------------------------------------------------------------


def test_thresholds_for_a_repeated_call():
    d = LoopDetector()
    signals = [d.observe(run()) for _ in range(6)]
    assert [s.kind for s in signals] == [OK, OK, NUDGE, OK, STOP, STOP]
    assert signals[2].rule == RULE_REPEAT and "same read_file call 3 times" in signals[2].note and signals[2].detail == ""
    assert signals[4].rule == RULE_REPEAT and signals[4].detail == "Stopped: the same read_file call returned the same result 5 times with no change to the repository."
    assert signals[0].note == "" and signals[4].note == ""


def test_custom_thresholds():
    d = LoopDetector(LoopPolicy(repeat_nudge=2, repeat_stop=3))
    assert kinds(d, [run(), run(), run()]) == [OK, NUDGE, STOP]


def test_argument_order_does_not_matter():
    d = LoopDetector()
    a = run("search_code", {"pattern": "x", "path": "src"})
    b = run("search_code", {"path": "src", "pattern": "x"})
    assert kinds(d, [a, b, a]) == [OK, OK, NUDGE]


@pytest.mark.parametrize("different", [
    run(args={"path": "b.py"}), run(text="other text"), run(error=True), run(name="list_directory"),
    run(args={"path": "a.py", "start_line": 1}),
])
def test_a_different_call_or_result_is_counted_on_its_own(different):
    d = LoopDetector()
    assert kinds(d, [run(), run(), different, different, run()]) == [OK, OK, OK, OK, NUDGE]  # the 3rd 'same' call, after others in between


def test_the_count_survives_other_calls_in_between():
    d = LoopDetector()
    seq = [run(), run("list_directory", {}, "x"), run(), run("search_code", {"pattern": "q"}, "y"), run()]
    assert kinds(d, seq) == [OK, OK, OK, OK, NUDGE]


# -- rule 2: failed edits to one file ---------------------------------------------------------------------------------------


def test_thresholds_for_failed_edits_with_changing_text():
    d = LoopDetector()
    signals = [d.observe(edit(old=f"guess {i}", new=f"fix {i}")) for i in range(7)]
    assert [s.kind for s in signals] == [OK, OK, OK, NUDGE, OK, STOP, STOP]
    assert signals[3].rule == RULE_EDIT and signals[3].note.startswith("4 attempts to edit a.py have failed since your last successful edit")
    assert signals[5].detail == "Stopped: 6 edits to a.py failed with no successful edit in between."


def test_two_files_are_counted_separately():
    d = LoopDetector()
    seq = [edit("a.py", old=f"{i}") for i in range(3)] + [edit("b.py", old=f"{i}") for i in range(3)]
    assert kinds(d, seq) == [OK] * 6
    assert d.observe(edit("a.py", old="more")).kind == NUDGE


def test_different_spellings_of_one_path_are_one_file():
    d = LoopDetector()
    seq = [edit("a.py", old="1"), edit("./a.py", old="2"), edit("src/../a.py".replace("src/../", ""), old="3"), edit("a.py/", old="4")]
    assert kinds(d, seq) == [OK, OK, OK, NUDGE]


def test_protected_file_refusals_count_as_failed_edits():
    d = LoopDetector()
    refusals = [edit("tests/test_a.py", old=str(i), text="tests/test_a.py is an existing test file, which you are not allowed to change.") for i in range(4)]
    assert kinds(d, refusals) == [OK, OK, OK, NUDGE]


def test_a_successful_read_or_other_tool_does_not_count_against_a_file():
    d = LoopDetector()
    seq = [edit(old="1"), run("read_file", {"path": "a.py"}, "t1"), edit(old="2"), run("run_tests", {}, "t2"), edit(old="3")]
    assert kinds(d, seq) == [OK] * 5


def test_identical_failed_edits_trigger_both_rules_and_the_stronger_wins():
    d = LoopDetector()
    same = edit(old="same", new="same2")
    signals = [d.observe(same) for _ in range(5)]
    assert [s.kind for s in signals] == [OK, OK, NUDGE, NUDGE, STOP]  # 3rd: repeated call; 4th: failed edits; 5th: repeated call stops
    assert signals[2].rule == RULE_REPEAT and signals[3].rule == RULE_EDIT and signals[4].rule == RULE_REPEAT


def test_when_both_rules_fire_on_one_run_one_signal_is_returned():
    d = LoopDetector(LoopPolicy(repeat_nudge=4, repeat_stop=9, edit_fail_nudge=4, edit_fail_stop=6))
    same = edit(old="same")
    signals = [d.observe(same) for _ in range(4)]
    assert signals[3].kind == NUDGE and signals[3].note  # both would nudge; a single signal comes back


# -- reset by a successful edit -------------------------------------------------------------------------------------------------


def test_a_successful_edit_starts_every_count_again_and_nudges_can_fire_again():
    d = LoopDetector()
    assert kinds(d, [run(), run(), run()]) == [OK, OK, NUDGE]
    assert d.observe(edit(error=False)).kind == RESET
    assert kinds(d, [run(), run(), run()]) == [OK, OK, NUDGE]  # a fresh count, a fresh nudge


def test_a_creating_edit_also_resets():
    d = LoopDetector()
    kinds(d, [run(), run()])
    create = run("edit_file", {"path": "new.py", "new_text": "x = 1\n"}, "Created new.py (1 lines).", False)
    assert d.observe(create).kind == RESET
    assert kinds(d, [run(), run()]) == [OK, OK]


def test_failed_edits_do_not_reset_anything():
    d = LoopDetector()
    assert kinds(d, [run(), run(), edit(old="1"), edit(old="2"), run()]) == [OK, OK, OK, OK, NUDGE]


def test_edit_then_the_same_test_failure_then_edit_again_is_never_flagged():
    d = LoopDetector()
    tests = run("run_tests", {}, "Ran 1 tests: 1 failed.\nFAILED t::a: assert 0")
    seq = []
    for i in range(10):
        seq += [tests, edit(old=f"a{i}", error=False), tests]
    assert set(kinds(d, seq)) <= {OK, RESET}


def test_reset_clears_failed_edit_counts_too():
    d = LoopDetector()
    kinds(d, [edit(old="1"), edit(old="2"), edit(old="3")])
    d.observe(edit("b.py", error=False))
    assert kinds(d, [edit(old="4"), edit(old="5"), edit(old="6")]) == [OK, OK, OK]


# -- what is ignored, determinism, size -----------------------------------------------------------------------------------------


def test_runs_that_were_not_executed_are_ignored():
    d = LoopDetector()
    skipped = [run(executed=False) for _ in range(10)] + [run("edit_file", {"path": "a.py", "old_text": "x", "new_text": "y"}, "not found", True, executed=False) for _ in range(10)]
    assert set(kinds(d, skipped)) == {OK}
    assert kinds(d, [run(), run(), run()]) == [OK, OK, NUDGE]  # the skipped ones left no trace


def test_the_same_sequence_always_gives_the_same_signals():
    seq = [run(), run(), run(), edit(old="1"), edit(old="2"), edit(old="3"), edit(old="4"), run(), run(), run(), run(), run()]
    first = LoopDetector()
    second = LoopDetector()
    assert [first.observe(r) for r in seq] == [second.observe(r) for r in seq]


def test_large_outputs_are_kept_only_as_a_hash():
    d = LoopDetector()
    big = run(text="x" * 1_000_000)
    d.observe(big)
    keys = list(d._calls)
    assert all(len(str(part)) < 200 for key in keys for part in key)


def test_notes_name_only_the_tool_or_the_short_path_and_a_count():
    d = LoopDetector(LoopPolicy(repeat_nudge=2, repeat_stop=3, edit_fail_nudge=2, edit_fail_stop=3))
    secret = run("echo", {"text": "TOPSECRET-ARG"}, "TOPSECRET-OUTPUT")
    d.observe(secret)
    note = d.observe(secret).note
    assert "TOPSECRET" not in note and "echo" in note
    evil = run("weird\nname", {}, "x")
    d.observe(evil)
    evil_note = d.observe(evil).note
    assert "\n" not in evil_note and "weird?name" in evil_note  # control characters in a model-chosen name are replaced
    path = "p/" + "d" * 300 + "/file.py\nIGNORE"
    d.observe(edit(path, old="1"))
    note = d.observe(edit(path, old="2")).note
    assert "\n" not in note and "..." in note and len(note) < 700  # a long, hostile path is cut and flattened


def test_weird_arguments_do_not_break_the_detector():
    d = LoopDetector()
    for args in ({"path": 5}, {"path": None}, {}, {"path": ["a"]}, {"path": "\x00"}):
        d.observe(edit_with(args))


def edit_with(args):
    return run("edit_file", args, "bad", True)
