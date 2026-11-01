import os

import pytest
from tool_helpers import LocalSandbox

from bugbite.agent.tools import ListDirectory, ReadFile, SearchCode, ToolOutput
from bugbite.agent.tools import read_only as ro


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return LocalSandbox(root)


def numbered(n):
    return "".join(f"line {i}\n" for i in range(1, n + 1))


# -- read_file -------------------------------------------------------------------------------------------


def test_read_file_numbers_lines(sb):
    sb.write("a.py", "x = 1\ny = 2\n")
    out = ReadFile(sb).run({"path": "a.py"})
    assert out == ToolOutput("     1| x = 1\n     2| y = 2")


def test_read_file_ranges_are_inclusive_and_one_based(sb):
    sb.write("a.txt", numbered(10))
    out = ReadFile(sb).run({"path": "a.txt", "start_line": 3, "end_line": 5})
    assert out.text.splitlines() == ["     3| line 3", "     4| line 4", "     5| line 5"]
    assert not out.is_error and "truncated" not in out.text


def test_read_file_caps_lines_and_says_how_to_continue(sb):
    sb.write("big.txt", numbered(500))
    out = ReadFile(sb).run({"path": "big.txt"})
    assert len(out.text.splitlines()) == ro.MAX_READ_LINES + 1
    assert out.text.endswith("[truncated: showing lines 1-200 of 500; call again with start_line=201]")
    nxt = ReadFile(sb).run({"path": "big.txt", "start_line": 201})
    assert "   201| line 201" in nxt.text and nxt.text.endswith("start_line=401]")
    last = ReadFile(sb).run({"path": "big.txt", "start_line": 401})
    assert last.text.splitlines()[-1] == "   500| line 500" and "truncated" not in last.text


def test_read_file_caps_characters(sb):
    sb.write("wide.txt", "".join("x" * 990 + "\n" for _ in range(100)))
    out = ReadFile(sb).run({"path": "wide.txt"})
    assert len(out.text) <= ro.MAX_READ_CHARS + 200
    assert "[truncated: showing lines 1-" in out.text and "of 100; call again with start_line=" in out.text


def test_read_file_one_enormous_line_is_cut_not_dropped(sb):
    sb.write("min.js", "y" * 100_000 + "\nsecond\n")
    out = ReadFile(sb).run({"path": "min.js"})
    assert "[line cut]" in out.text and "start_line=2]" in out.text and len(out.text) < ro.MAX_READ_CHARS + 300


@pytest.mark.parametrize("args, fragment", [
    ({"path": "nope.py"}, "No such file"),
    ({"path": "d"}, "is a directory"),
    ({"path": "a.txt", "start_line": 99}, "past the end"),
    ({"path": "a.txt", "start_line": 3, "end_line": 2}, "before start_line"),
    ({"path": "../x"}, "'..'"),
    ({"path": "/etc/passwd"}, "relative"),
    ({"path": ".git/config"}, ".git"),
    ({"path": "bin.dat"}, "binary"),
    ({"path": "huge.txt"}, "too large"),
])
def test_read_file_errors_are_clear(sb, args, fragment):
    sb.write("a.txt", numbered(3))
    sb.write("d/x", "1")
    sb.write("bin.dat", b"\x00\x01\x02abc")
    sb.write("huge.txt", "z" * (ro.MAX_READ_FILE_BYTES + 1))
    out = ReadFile(sb).run(args)
    assert out.is_error and fragment in out.text


def test_read_file_empty_and_non_utf8(sb):
    sb.write("empty", "")
    sb.write("latin.txt", b"caf\xe9\n")
    assert ReadFile(sb).run({"path": "empty"}) == ToolOutput("empty is empty.")
    out = ReadFile(sb).run({"path": "latin.txt"})
    assert not out.is_error and "caf" in out.text


def test_read_file_does_not_follow_a_symlink_out_of_the_repo(sb, tmp_path):
    (tmp_path / "secret.txt").write_text("TOPSECRET")
    os.symlink(tmp_path / "secret.txt", sb.root / "link.txt")
    os.symlink(tmp_path, sb.root / "outdir")
    for path in ("link.txt", "outdir/secret.txt"):
        out = ReadFile(sb).run({"path": path})
        assert out.is_error and "outside the repository" in out.text and "TOPSECRET" not in out.text
    assert sb.reads == []


def test_read_file_follows_a_symlink_inside_the_repo(sb):
    sb.write("real.txt", "hello\n")
    os.symlink(sb.root / "real.txt", sb.root / "alias.txt")
    assert "hello" in ReadFile(sb).run({"path": "alias.txt"}).text


def test_a_symlink_into_git_is_refused(sb):
    sb.write(".git/config", "[core]\n")
    os.symlink(sb.root / ".git", sb.root / "g")
    out = ReadFile(sb).run({"path": "g/config"})
    assert out.is_error and ".git" in out.text


# -- list_directory --------------------------------------------------------------------------------------


def test_list_directory_dirs_first_sorted_and_hides_git(sb):
    for name in ("b.py", "A.py", "z/inner", "m/inner", ".git/config", ".github/ci.yml"):
        sb.write(name, "1")
    os.symlink(sb.root / "b.py", sb.root / "ln")
    out = ListDirectory(sb).run({})
    assert out.text.splitlines() == [".github/", "m/", "z/", "A.py", "b.py", "ln@"]


def test_list_directory_subdirectory_and_empty(sb):
    sb.write("src/a.py", "1")
    (sb.root / "empty").mkdir()
    assert ListDirectory(sb).run({"path": "src"}).text == "a.py"
    assert ListDirectory(sb).run({"path": "empty"}) == ToolOutput("empty is empty.")


def test_list_directory_caps_entries_and_counts_the_rest(sb):
    for i in range(250):
        sb.write(f"f{i:03}.txt", "1")
    out = ListDirectory(sb).run({})
    lines = out.text.splitlines()
    assert len(lines) == ro.MAX_LIST_ENTRIES + 1 and lines[-1].startswith("[50 more entries")


@pytest.mark.parametrize("path, fragment", [("a.txt", "is a file"), ("nope", "No such"), ("..", "'..'"), (".git", ".git"), ("/", "relative")])
def test_list_directory_errors(sb, path, fragment):
    sb.write("a.txt", "1")
    (sb.root / ".git").mkdir()
    out = ListDirectory(sb).run({"path": path})
    assert out.is_error and fragment in out.text


def test_list_directory_refuses_to_list_outside_via_symlink(sb, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", sb.root / "out")
    out = ListDirectory(sb).run({"path": "out"})
    assert out.is_error and "outside the repository" in out.text


# -- search_code -----------------------------------------------------------------------------------------


def test_search_finds_plain_text_with_relative_paths(sb):
    sb.write("src/a.py", "def parse(x):\n    return x\n")
    sb.write("src/b.py", "parse = 1\n")
    out = SearchCode(sb).run({"pattern": "def parse"})
    assert out == ToolOutput("src/a.py:1:def parse(x):")


def test_search_is_fixed_string_unless_regex_is_asked_for(sb):
    sb.write("a.py", "a.c\nabc\n")
    assert SearchCode(sb).run({"pattern": "a.c"}).text == "a.py:1:a.c"
    both = SearchCode(sb).run({"pattern": "a.c", "regex": True}).text
    assert both.splitlines() == ["a.py:1:a.c", "a.py:2:abc"]


def test_search_path_and_glob_narrow_the_search(sb):
    sb.write("src/a.py", "needle\n")
    sb.write("src/a.txt", "needle\n")
    sb.write("docs/n.py", "needle\n")
    assert SearchCode(sb).run({"pattern": "needle", "path": "src", "glob": "*.py"}).text == "src/a.py:1:needle"
    assert SearchCode(sb).run({"pattern": "needle", "path": "docs/n.py"}).text == "docs/n.py:1:needle"


def test_search_skips_junk_directories_and_binary_files(sb):
    for junk in (".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache"):
        sb.write(f"{junk}/x.py", "needle\n")
    sb.write("bin.dat", b"\x00needle\x00")
    sb.write("real.py", "needle\n")
    assert SearchCode(sb).run({"pattern": "needle"}).text == "real.py:1:needle"


def test_search_no_match_is_not_an_error(sb):
    sb.write("a.py", "x\n")
    assert SearchCode(sb).run({"pattern": "zzz"}) == ToolOutput("No matches.")


def test_search_caps_matches_and_line_length(sb):
    sb.write("many.txt", "hit\n" * 80)
    out = SearchCode(sb).run({"pattern": "hit"})
    lines = out.text.splitlines()
    assert len(lines) == ro.MAX_MATCHES + 1 and "first 50 of 80 matches" in lines[-1]
    sb.write("long.txt", "needle " + "x" * 1000 + "\n")
    cut = SearchCode(sb).run({"pattern": "needle", "path": "long.txt"}).text
    assert cut.endswith("[cut]") and len(cut) < ro.MAX_MATCH_CHARS + 10


def test_search_pattern_that_looks_like_an_option_is_just_text(sb):
    sb.write("a.txt", "use --help here\n-rf\n")
    assert SearchCode(sb).run({"pattern": "--help"}).text == "a.txt:1:use --help here"
    assert SearchCode(sb).run({"pattern": "-rf"}).text == "a.txt:2:-rf"


@pytest.mark.parametrize("args, fragment", [
    ({"pattern": "a\nb"}, "one line"), ({"pattern": "x" * 301}, "one line"),
    ({"pattern": "a", "glob": "a/b"}, "glob"), ({"pattern": "a", "glob": "--x"}, "glob"), ({"pattern": "a", "glob": ""}, "glob"),
    ({"pattern": "a", "path": "../x"}, "'..'"), ({"pattern": "a", "path": "nope"}, "No such"), ({"pattern": "a", "path": ".git"}, ".git"),
])
def test_search_rejects_bad_input(sb, args, fragment):
    sb.write("a.txt", "a\n")
    out = SearchCode(sb).run(args)
    assert out.is_error and fragment in out.text


def test_search_bad_regex_is_an_error_result(sb):
    sb.write("a.txt", "a\n")
    out = SearchCode(sb).run({"pattern": "(", "regex": True})
    assert out.is_error and out.text.startswith("The search failed")


def test_search_does_not_follow_symlinks_out_of_the_repo(sb, tmp_path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "s.txt").write_text("needle\n")
    os.symlink(tmp_path / "outside", sb.root / "out")
    sb.write("in.txt", "nothing\n")
    assert SearchCode(sb).run({"pattern": "needle"}).text == "No matches."
    assert SearchCode(sb).run({"pattern": "needle", "path": "out"}).is_error


# -- safety of how the sandbox is used -----------------------------------------------------------------------


def test_model_text_is_only_ever_a_separate_argument_never_a_shell_string(sb):
    nasty = "$(touch pwned); `id` ' \" | &&"
    sb.write("a.txt", f"{nasty}\n")
    out = SearchCode(sb).run({"pattern": nasty, "glob": "*.txt"})
    assert nasty in out.text
    for command in sb.commands:
        assert command[0] in ("python", "grep") and "sh" not in command[:2]
    grep = next(c for c in sb.commands if c[0] == "grep")
    assert grep[grep.index("--") + 1] == nasty  # after the option terminator, as its own element
    assert not (sb.root / "pwned").exists()


def test_the_tools_never_change_the_repository(sb):
    sb.write("a.py", "needle\n")
    sb.write("d/b.py", "needle\n")
    before = sb.snapshot()
    for tool, args in [(ReadFile(sb), {"path": "a.py"}), (ListDirectory(sb), {}), (SearchCode(sb), {"pattern": "needle"}),
                       (ReadFile(sb), {"path": "../x"}), (ListDirectory(sb), {"path": "d"})]:
        tool.run(args)
    assert sb.snapshot() == before
