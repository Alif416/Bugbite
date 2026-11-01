"""Finding and checking the one action in a model's reply. Pure functions: no model, no network."""

import json

import pytest
from text_action_helpers import EDIT_FILE, LIST_DIRECTORY, MODE, READ_FILE, RUN_COMMAND, RUN_TESTS, SEARCH_CODE, TOOLS, action, final

from bugbite.adapter import ToolDefinition, parse_action
from bugbite.adapter.text_action import ActionError, FinalAction, ToolAction


def ok(text, tools=TOOLS, **kw):
    result = parse_action(text, tools, **kw)
    assert not isinstance(result, ActionError), result
    return result


def bad(text, tools=TOOLS, **kw):
    result = parse_action(text, tools, **kw)
    assert isinstance(result, ActionError), result
    return result.message


# -- the two shapes ----------------------------------------------------------------------------


def test_a_bare_tool_action():
    result = ok(action("read_file", path="a.py", start_line=3))
    assert result == ToolAction("read_file", {"path": "a.py", "start_line": 3}, "")


def test_a_bare_final_action():
    assert ok(final("All done.")) == FinalAction("All done.", "")


@pytest.mark.parametrize("text", ['{"tool": "run_tests"}', '{"tool": "run_tests", "arguments": null}', '{"tool": "run_tests", "arguments": {}}'])
def test_arguments_may_be_left_out_when_the_tool_needs_none(text):
    assert ok(text) == ToolAction("run_tests", {}, "")


def test_other_keys_in_the_action_are_ignored():
    assert ok('{"thought": "I should look", "tool": "read_file", "arguments": {"path": "a.py"}, "confidence": 0.9}').name == "read_file"


# -- prose, fences, and where the JSON sits ----------------------------------------------------------


@pytest.mark.parametrize(
    "text, prose",
    [
        ("Let me look at the file.\n" + action("read_file", path="a.py"), "Let me look at the file."),
        (action("read_file", path="a.py") + "\nThat should show the bug.", "That should show the bug."),
        ("First.\n" + action("read_file", path="a.py") + "\nSecond.", "First.\n\nSecond."),
        ("```json\n" + action("read_file", path="a.py") + "\n```", ""),
        ("```\n" + action("read_file", path="a.py") + "\n```", ""),
        ("```JSON\n" + action("read_file", path="a.py") + "\n```", ""),
        ("Reasoning here.\n```json\n" + action("read_file", path="a.py") + "\n```\nDone.", "Reasoning here.\n\nDone."),
        ("   \n\n" + action("read_file", path="a.py") + "   \n", ""),
    ],
)
def test_prose_and_code_fences_are_ignored_but_the_prose_is_kept(text, prose):
    result = ok(text)
    assert result.name == "read_file" and result.arguments == {"path": "a.py"} and result.prose == prose


def test_braces_inside_strings_do_not_confuse_the_parser():
    result = ok(action("edit_file", path="a.py", old="if x: {", new="if x: { # } {{"))
    assert result.arguments["old"] == "if x: {" and result.arguments["new"] == "if x: { # } {{"


def test_prose_containing_braces_before_the_action_is_fine():
    result = ok("Use a dict like {not json at all} here.\n" + action("run_command", command="ls"))
    assert result.name == "run_command"


def test_nested_objects_in_arguments_are_not_mistaken_for_separate_actions():
    result = ok(action("set_mode", mode="fast", level={"n": 3}), tools=(MODE,))
    assert result.arguments == {"mode": "fast", "level": {"n": 3}}


@pytest.mark.parametrize("value", ["caf\u00e9 \u2713 \U0001f41b", "line1\nline2\ttab", 'quote " and \\ backslash', "\u2028 separator", ""])
def test_unusual_text_survives_in_arguments(value):
    assert ok(action("edit_file", path="p", old=value, new="x")).arguments["old"] == value


def test_the_same_action_repeated_counts_once():
    text = action("read_file", path="a.py")
    assert ok(text + "\nAgain:\n" + text).name == "read_file"


def test_an_action_after_a_stray_unparseable_fragment_is_still_found():
    assert ok("see {broken: here\n" + action("run_command", command="pwd")).name == "run_command"


# -- no action / too many ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "I will fix this by reading the file first.", "Sure! Here is my plan:\n1. read\n2. edit"])
def test_prose_only_is_invalid(text):
    assert "No JSON action" in bad(text)


def test_two_different_actions_are_invalid():
    message = bad(action("read_file", path="a.py") + "\n" + action("read_file", path="b.py"))
    assert "2 different actions" in message and "exactly one" in message


def test_a_tool_action_and_a_final_action_together_are_two_actions():
    assert "2 different actions" in bad(action("read_file", path="a.py") + " " + final("done"))


def test_one_object_with_both_keys_is_invalid():
    assert 'not both' in bad('{"tool": "run_tests", "final": "done"}')


@pytest.mark.parametrize("text", ['{"action": "read_file"}', '{"name": "read_file", "arguments": {}}', '{"a": 1}', "[1, 2, 3]", '"just a string"', "{}"])
def test_json_that_is_not_an_action_is_invalid(text):
    assert "no action" in bad(text) or "No JSON action" in bad(text)


# -- broken JSON ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ['{"tool": "read_file", "arguments": {"path": "a.py"},}', "{'tool': 'read_file'}", '{tool: "read_file"}', '{"tool": "read_file", "arguments": {"path": "a.py"}', '{"tool": "read_file" "arguments": {}}'],
)
def test_broken_json_reports_the_parsers_reason(text):
    message = bad(text)
    assert "could not be parsed" in message and "line 1" in message


def test_a_reply_cut_off_by_the_output_limit_says_so():
    cut = '{"tool": "edit_file", "arguments": {"path": "a.py", "old": "x'
    assert "cut off by the output limit" in bad(cut, truncated=True)
    assert "cut off" not in bad(cut, truncated=False)


def test_a_truncated_prose_reply_also_mentions_the_limit():
    assert "cut off" in bad("I think the", truncated=True)


def test_extremely_deep_nesting_is_just_an_unusable_reply():
    assert isinstance(parse_action("{" * 50000 + "}" * 50000, TOOLS), ActionError)
    assert isinstance(parse_action('{"tool": ' + "[" * 20000, TOOLS), ActionError)


# -- field types and tool names --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tool_value", [5, None, True, ["read_file"], {"name": "read_file"}, ""])
def test_the_tool_must_be_a_name_in_text(tool_value):
    assert "name of a tool" in bad(json.dumps({"tool": tool_value}))


def test_final_must_be_text():
    assert '"final" must be text' in bad('{"final": 5}')
    assert '"final" must be text' in bad('{"final": null}')


@pytest.mark.parametrize("value", ['"x"', "[1]", "5", "true"])
def test_arguments_must_be_an_object(value):
    assert "must be a JSON object" in bad('{"tool": "read_file", "arguments": %s}' % value)


def test_an_unknown_tool_lists_the_valid_names():
    message = bad(action("delete_everything"))
    assert 'Unknown tool "delete_everything"' in message
    assert all(t.name in message for t in TOOLS)


def test_a_very_long_unknown_name_is_shortened_in_the_message():
    assert len(bad(action("x" * 5000))) < 400


def test_tool_names_are_case_sensitive():
    assert "Unknown tool" in bad(action("Read_File", path="a.py"))


# -- the tool's own schema ----------------------------------------------------------------------------------------------------


def test_a_missing_required_argument():
    message = bad(action("read_file"))
    assert 'Invalid arguments for "read_file"' in message and "'path' is a required property" in message


def test_a_wrong_type_names_the_path():
    message = bad(action("read_file", path=5))
    assert "arguments.path" in message and "5 is not of type 'string'" in message


def test_a_value_below_a_minimum():
    assert "arguments.start_line" in bad(action("read_file", path="a", start_line=0))


def test_a_value_outside_an_enum():
    assert "arguments.mode" in bad(action("set_mode", mode="reckless"), tools=(MODE,))


def test_a_nested_problem_names_the_nested_path():
    assert "arguments.level" in bad(action("set_mode", mode="fast", level={}), tools=(MODE,))
    assert "arguments.level.n" in bad(action("set_mode", mode="fast", level={"n": "x"}), tools=(MODE,))


def test_an_extra_property_when_not_allowed():
    assert "Additional properties" in bad(action("read_file", path="a.py", colour="red"))


def test_an_array_item_of_the_wrong_type():
    assert "arguments.targets.1" in bad(action("run_tests", targets=["a", 5]))


def test_extra_properties_are_fine_when_the_schema_allows_them():
    open_tool = ToolDefinition("open", "Open.", {"type": "object", "properties": {"a": {"type": "string"}}})
    assert ok(action("open", a="x", b=1), tools=(open_tool,)).arguments == {"a": "x", "b": 1}


def test_a_long_schema_error_message_is_shortened():
    assert len(bad(action("read_file", path="y" * 10000, start_line="z" * 10000))) < 700


def test_booleans_are_not_integers_for_schema_checks():
    assert "arguments.start_line" in bad(action("read_file", path="a", start_line=True))


# -- never raises ------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("junk", [None, 5, b"bytes", ["list"], {"d": 1}])
def test_non_text_input_is_an_error_not_an_exception(junk):
    assert isinstance(parse_action(junk, TOOLS), ActionError)


@pytest.mark.parametrize("text", ["\x00", "{\x00}", "\ud83d", "{" + "\u0000" * 100, "{\"tool\": \"read_file\", \"arguments\": {\"path\": \"\\ud800\"}}"])
def test_odd_characters_never_crash_the_parser(text):
    assert parse_action(text, TOOLS) is not None


def test_a_large_reply_with_one_action_in_the_middle():
    filler = "word " * 50_000
    assert ok(filler + action("run_command", command="ls") + filler).name == "run_command"


# -- round trip -------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("read_file", {"path": "src/\u00e9.py", "start_line": 2, "end_line": 9}),
        ("edit_file", {"path": "a.py", "old": 'say "hi"\n\ttab {braces}', "new": "\u2713 \U0001f41b \\ back"}),
        ("search_code", {"query": "def (\\w+)", "regex": True}),
        ("run_tests", {"targets": ["tests/a.py::test_x[1-2]", "tests/b.py"]}),
        ("run_command", {"command": "grep -rn '{' . | head"}),
        ("list_directory", {"path": "."}),
    ],
)
def test_rendering_an_action_and_parsing_it_back_gives_the_same_call(name, arguments):
    from bugbite.adapter.text_action import _render_action

    parsed = ok(_render_action(name, arguments))
    assert (parsed.name, parsed.arguments) == (name, arguments)
