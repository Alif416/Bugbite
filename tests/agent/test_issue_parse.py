import time

import pytest

from bugbite.agent import issue_parse as ip
from bugbite.agent.issue_parse import Frame, TestMention, TrackedIndex, find_path_mentions, find_test_mentions, map_to_repo, parse_tracebacks

STANDARD = '''Traceback (most recent call last):
  File "/home/u/app/src/pkg/mod.py", line 42, in parse
    return int(x)
  File "src/pkg/util.py", line 7, in helper
    raise ValueError("bad")
ValueError: bad input
'''


# -- tracebacks ------------------------------------------------------------------------------------------------------------------


def test_a_standard_traceback():
    [tb] = parse_tracebacks("I get this:\n\n" + STANDARD + "\nPlease help.")
    assert tb.frames == (Frame("/home/u/app/src/pkg/mod.py", 42, "parse"), Frame("src/pkg/util.py", 7, "helper"))
    assert tb.exception == "ValueError: bad input"


def test_inside_a_code_fence_and_inside_a_quote():
    assert parse_tracebacks("```\n" + STANDARD + "```")[0].exception == "ValueError: bad input"
    quoted = "\n".join("> " + line for line in STANDARD.splitlines())
    [tb] = parse_tracebacks(quoted)
    assert len(tb.frames) == 2 and tb.exception == "ValueError: bad input"


def test_chained_tracebacks_give_one_each():
    chained = STANDARD + '\nDuring handling of the above exception, another exception occurred:\n\n' + STANDARD.replace("ValueError: bad input", "RuntimeError: wrapped")
    tbs = parse_tracebacks(chained)
    assert [t.exception for t in tbs] == ["ValueError: bad input", "RuntimeError: wrapped"]


def test_python_311_caret_lines_and_repeated_line_markers_are_skipped():
    text = '''Traceback (most recent call last):
  File "a.py", line 3, in f
    x = y + z
        ~~^~~
  File "a.py", line 3, in f
    x = y + z
        ~~^~~
  [Previous line repeated 2 more times]
TypeError: unsupported operand
'''
    [tb] = parse_tracebacks(text)
    assert [f.line for f in tb.frames] == [3, 3] and tb.exception == "TypeError: unsupported operand"


def test_frames_without_source_lines_and_without_function_names():
    text = 'Traceback (most recent call last):\n  File "<stdin>", line 1, in <module>\nNameError: name \'x\' is not defined\n'
    [tb] = parse_tracebacks(text)
    assert tb.frames == (Frame("<stdin>", 1, "<module>"),) and tb.exception == "NameError: name 'x' is not defined"
    [tb] = parse_tracebacks('Traceback (most recent call last):\n  File "a.py", line 9\n    x = (\nSyntaxError: invalid syntax\n')
    assert tb.frames == (Frame("a.py", 9, None),) and tb.exception == "SyntaxError: invalid syntax"


def test_windows_paths():
    [tb] = parse_tracebacks('Traceback (most recent call last):\n  File "C:\\Users\\me\\proj\\pkg\\mod.py", line 3, in f\n    pass\nKeyError: 1\n')
    assert tb.frames[0].path == "C:\\Users\\me\\proj\\pkg\\mod.py"


def test_a_truncated_traceback_keeps_the_frames_it_has():
    [tb] = parse_tracebacks('Traceback (most recent call last):\n  File "a.py", line 3, in f\n    pass\n')
    assert tb.frames == (Frame("a.py", 3, "f"),) and tb.exception is None


def test_a_long_exception_line_is_cut():
    [tb] = parse_tracebacks('Traceback (most recent call last):\n  File "a.py", line 3, in f\n    pass\nValueError: ' + "x" * 1000)
    assert len(tb.exception) == ip.MAX_EXCEPTION_CHARS


@pytest.mark.parametrize("text", [
    "", "no traceback here", "Traceback (most recent call last):", "Traceback (most recent call last):\n\nnothing",
    'File "a.py", line 3, in f', "The traceback was too long to paste", 'Traceback: File "a.py", line 3',
])
def test_text_that_only_looks_like_a_traceback_gives_nothing(text):
    assert parse_tracebacks(text) == []


def test_pytest_style_frames():
    text = "src/pkg/mod.py:42: in parse\n    return int(x)\nsrc/pkg/util.py:7: ValueError\n"
    [tb] = parse_tracebacks(text)
    assert tb.frames == (Frame("src/pkg/mod.py", 42, "parse"), Frame("src/pkg/util.py", 7, None)) and tb.exception == "ValueError"


def test_caps_on_tracebacks_and_frames():
    many = "\n".join(STANDARD for _ in range(9))
    assert len(parse_tracebacks(many)) == ip.MAX_TRACEBACKS
    frames = "".join(f'  File "f{i}.py", line {i + 1}, in g\n    pass\n' for i in range(100))
    [tb] = parse_tracebacks("Traceback (most recent call last):\n" + frames + "Error: x")
    assert len(tb.frames) == ip.MAX_FRAMES and tb.frames[-1].path == "f99.py"  # the innermost frames are kept


def test_huge_and_hostile_input_is_fast():
    nasty = ("Traceback (most recent call last):\n" + '  File "' + "a" * 5000 + '", line 1\n') * 2000 + ("x" * 100000) + "\n" + ("> " * 50000)
    started = time.monotonic()
    parse_tracebacks(nasty)
    find_path_mentions(nasty)
    find_test_mentions(nasty)
    assert time.monotonic() - started < 2


# -- paths and tests ------------------------------------------------------------------------------------------------------------------


def test_path_mentions():
    text = "See src/pkg/mod.py:42, `util.py`, tests\\test_a.py and https://github.com/o/r/blob/main/src/x.py. Not a.pyc, b.pyx, c.py.bak or notes.txt."
    assert find_path_mentions(text) == ["src/pkg/mod.py", "util.py", "tests/test_a.py"]


def test_path_mentions_are_ordered_unique_and_capped():
    assert find_path_mentions("a.py b.py a.py") == ["a.py", "b.py"]
    assert len(find_path_mentions(" ".join(f"f{i}.py" for i in range(100)))) == ip.MAX_PATHS


def test_test_mentions():
    text = "FAILED tests/test_a.py::TestX::test_y[a-b] - boom\nalso tests/test_b.py::test_z and test_bare_one, `test_bare_two()`."
    assert find_test_mentions(text) == [
        TestMention(node_id="tests/test_a.py::TestX::test_y[a-b]"), TestMention(node_id="tests/test_b.py::test_z"),
        TestMention(name="test_bare_one"), TestMention(name="test_bare_two"),
    ]


@pytest.mark.parametrize("text", [
    "-ptests/test_a.py::test_x", "--pdb tests/test_a.py", "/abs/tests/test_a.py::test_x", "tests/test_a.py::", "tests/test_a.py::123",
    "see test_a.py", "tests/test_a.py::test_x;rm", "$(tests/test_a.py)::test_x",
])
def test_unsafe_or_incomplete_ids_are_not_found(text):
    ids = [m.node_id for m in find_test_mentions(text) if m.node_id]
    for node_id in ids:
        assert ip.SAFE_NODE_ID.fullmatch(node_id) and not node_id.startswith("-") and ";" not in node_id and "$" not in node_id
    assert not any(i.startswith("-") for i in ids)


def test_ids_with_spaces_or_odd_characters_in_the_brackets_lose_the_brackets():
    [m] = [m for m in find_test_mentions("tests/test_a.py::test_x[a b]") if m.node_id]
    assert m.node_id == "tests/test_a.py::test_x"


def test_bare_names_are_capped_and_exclude_file_names_and_ids():
    names = " ".join(f"test_n{i}" for i in range(20))
    assert len([m for m in find_test_mentions(names) if m.name]) == ip.MAX_NAMES
    found = find_test_mentions("test_file.py and tests/test_file.py::test_in_id")
    assert [m.name for m in found if m.name] == [] and [m.node_id for m in found if m.node_id] == ["tests/test_file.py::test_in_id"]


# -- mapping ---------------------------------------------------------------------------------------------------------------------------


TRACKED = TrackedIndex.build(["src/pkg/mod.py", "src/pkg/util.py", "src/other/util.py", "tests/test_a.py", "setup.py", "a/b/c.py", "x/b/c.py"])


@pytest.mark.parametrize("path, expected", [
    ("src/pkg/mod.py", "src/pkg/mod.py"), ("/home/u/app/src/pkg/mod.py", "src/pkg/mod.py"), ("C:\\Users\\me\\proj\\src\\pkg\\mod.py", "src/pkg/mod.py"),
    ("./src/pkg/mod.py", "src/pkg/mod.py"), ("pkg/mod.py", "src/pkg/mod.py"), ("mod.py", "src/pkg/mod.py"), ("/srv/app/setup.py", "setup.py"),
    ("/x/y/pkg/util.py", "src/pkg/util.py"),
])
def test_paths_map_to_tracked_files(path, expected):
    assert map_to_repo(path, TRACKED) == expected


@pytest.mark.parametrize("path", [
    "util.py", "c.py", "b/c.py", "missing.py", "src/pkg/nope.py", "", "/", "../src/pkg/mod.py", "a/../src/pkg/mod.py", ".git/config",
    "src/.git/mod.py", "/usr/lib/python3.11/json/decoder.py", "/venv/lib/python3.9/site-packages/pkg/mod.py", "/x/dist-packages/pkg/mod.py",
    "<stdin>", "src/pkg/mod.py\x00", "a" * 500 + ".py", None, 5,
])
def test_unknown_ambiguous_foreign_and_unsafe_paths_do_not_map(path):
    assert map_to_repo(path, TRACKED) is None


def test_the_longest_tail_decides_between_files_with_the_same_name():
    assert map_to_repo("/home/u/src/other/util.py", TRACKED) == "src/other/util.py"
    assert map_to_repo("/home/u/src/pkg/util.py", TRACKED) == "src/pkg/util.py"
