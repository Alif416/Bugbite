import os

import pytest
from tool_helpers import LocalSandbox

from bugbite.agent.tools import EditFile, ReadFile, ToolOutput
from bugbite.agent.tools import edit_run as er


@pytest.fixture
def sb(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return LocalSandbox(root)


def edit(sb, **args):
    return EditFile(sb).run(args)


def read(sb, rel):
    return (sb.root / rel).read_bytes().decode()


# -- replace -----------------------------------------------------------------------------------------------


def test_a_single_match_is_replaced_and_the_region_is_shown(sb):
    sb.write("src/app.py", "def add(a, b):\n    return a - b\n\nprint(1)\n")
    out = edit(sb, path="src/app.py", old_text="return a - b", new_text="return a + b")
    assert not out.is_error
    assert out.text == "Edited src/app.py: replaced 1 occurrence.\n     2|     return a + b"
    assert read(sb, "src/app.py") == "def add(a, b):\n    return a + b\n\nprint(1)\n"


def test_multi_line_replacement_shows_all_new_lines(sb):
    sb.write("a.py", "x\ny\nz\n")
    out = edit(sb, path="a.py", old_text="y", new_text="y1\ny2\ny3")
    assert out.text.endswith("     2| y1\n     3| y2\n     4| y3") and read(sb, "a.py") == "x\ny1\ny2\ny3\nz\n"


def test_region_is_capped(sb):
    sb.write("a.py", "start\n")
    out = edit(sb, path="a.py", old_text="start", new_text="\n".join(f"l{i}" for i in range(50)))
    assert len(out.text.splitlines()) == er.SHOW_LINES + 2 and "more changed lines not shown" in out.text


def test_deletion_works(sb):
    sb.write("a.py", "keep\ndrop me\nkeep2\n")
    out = edit(sb, path="a.py", old_text="drop me\n", new_text="")
    assert "text removed at line 2" in out.text and read(sb, "a.py") == "keep\nkeep2\n"


@pytest.mark.parametrize("old, fragment", [("nothing like this", "was not found"), ("a", "occurs 3 times")])
def test_zero_or_many_matches_change_nothing(sb, old, fragment):
    sb.write("a.py", "a b a c a\n")
    out = edit(sb, path="a.py", old_text=old, new_text="Z")
    assert out.is_error and fragment in out.text and read(sb, "a.py") == "a b a c a\n" and sb.writes == []


def test_same_text_is_an_error(sb):
    sb.write("a.py", "x\n")
    out = edit(sb, path="a.py", old_text="x", new_text="x")
    assert out.is_error and "same" in out.text and sb.writes == []


def test_crlf_and_missing_final_newline_are_preserved(sb):
    sb.write("w.txt", b"one\r\ntwo\r\nthree")
    edit(sb, path="w.txt", old_text="two", new_text="2")
    assert (sb.root / "w.txt").read_bytes() == b"one\r\n2\r\nthree"
    assert edit(sb, path="w.txt", old_text="one\r\n", new_text="").is_error is False


def test_unicode_is_preserved(sb):
    sb.write("u.txt", "naïve – café\n")
    edit(sb, path="u.txt", old_text="café", new_text="thé ☕")
    assert read(sb, "u.txt") == "naïve – thé ☕\n"


def test_the_file_mode_is_preserved(sb):
    sb.write("run.sh", "#!/bin/sh\necho hi\n")
    (sb.root / "run.sh").chmod(0o755)
    edit(sb, path="run.sh", old_text="hi", new_text="there")
    assert (sb.root / "run.sh").stat().st_mode & 0o777 == 0o755
    sb.write("plain.txt", "a\n")
    (sb.root / "plain.txt").chmod(0o644)
    sb.commands.clear()
    edit(sb, path="plain.txt", old_text="a", new_text="b")
    assert not [c for c in sb.commands if c[0] == "chmod"]  # nothing to restore


@pytest.mark.parametrize("path, fragment", [
    ("nope.py", "No such file"), ("d", "directory"), ("../x", "'..'"), ("/etc/passwd", "relative"), (".git/config", ".git"),
    ("bin", "binary"), ("latin", "not valid UTF-8"), ("big", "larger than"),
])
def test_edit_errors(sb, path, fragment):
    sb.write("d/x", "1")
    sb.write("bin", b"\x00\x01")
    sb.write("latin", b"caf\xe9")
    sb.write("big", "z" * (er.MAX_FILE_BYTES + 1))
    out = edit(sb, path=path, old_text="1", new_text="2")
    assert out.is_error and fragment in out.text


def test_a_growing_edit_cannot_pass_the_size_limit(sb):
    sb.write("a.txt", "x" * (er.MAX_FILE_BYTES - 10) + "MARK")
    out = edit(sb, path="a.txt", old_text="MARK", new_text="y" * 5000)
    assert out.is_error and "larger than" in out.text


def test_symlinks_out_of_the_repo_cannot_be_written_through(sb, tmp_path):
    (tmp_path / "victim.txt").write_text("original")
    os.symlink(tmp_path / "victim.txt", sb.root / "link.txt")
    os.symlink(tmp_path, sb.root / "outdir")
    for args in (dict(path="link.txt", old_text="original", new_text="pwned"),
                 dict(path="outdir/victim.txt", old_text="original", new_text="pwned"),
                 dict(path="outdir/new.txt", new_text="pwned"),
                 dict(path="link.txt", new_text="pwned")):
        out = edit(sb, **args)
        assert out.is_error and "outside the repository" in out.text, args
    assert (tmp_path / "victim.txt").read_text() == "original" and not (tmp_path / "new.txt").exists() and sb.writes == []


def test_a_symlink_inside_the_repo_is_followed_to_its_real_file(sb):
    sb.write("real.py", "a = 1\n")
    os.symlink(sb.root / "real.py", sb.root / "alias.py")
    out = edit(sb, path="alias.py", old_text="1", new_text="2")
    assert not out.is_error and read(sb, "real.py") == "a = 2\n" and (sb.root / "alias.py").is_symlink()  # the alias is still a link


def test_an_alias_cannot_be_used_to_edit_a_protected_file(sb):
    sb.write("tests/test_a.py", "assert 1\n")
    os.symlink(sb.root / "tests/test_a.py", sb.root / "innocent.py")
    out = edit(sb, path="innocent.py", old_text="1", new_text="0")
    assert out.is_error and "existing test file" in out.text and read(sb, "tests/test_a.py") == "assert 1\n"


# -- create ----------------------------------------------------------------------------------------------


def test_creating_a_file_and_its_folders(sb):
    out = edit(sb, path="pkg/sub/new.py", new_text="print(1)\nprint(2)\n")
    assert out.text.startswith("Created pkg/sub/new.py (2 lines).") and read(sb, "pkg/sub/new.py") == "print(1)\nprint(2)\n"


def test_creating_an_empty_file_is_fine(sb):
    assert not edit(sb, path="pkg/__init__.py", new_text="").is_error and read(sb, "pkg/__init__.py") == ""


def test_creating_over_an_existing_file_or_folder_is_refused(sb):
    sb.write("a.py", "keep")
    sb.write("d/x", "1")
    for path in ("a.py", "d"):
        out = edit(sb, path=path, new_text="clobber")
        assert out.is_error and "already exists" in out.text
    assert read(sb, "a.py") == "keep"


def test_a_file_in_the_way_of_a_folder_is_refused(sb):
    sb.write("a", "i am a file")
    out = edit(sb, path="a/b.py", new_text="x")
    assert out.is_error and "is a file" in out.text


def test_files_the_agent_created_can_be_edited_again(sb):
    tool = EditFile(sb)
    assert not tool.run({"path": "tests/test_new.py", "new_text": "def test_a():\n    assert f() == 1\n"}).is_error
    out = tool.run({"path": "tests/test_new.py", "old_text": "== 1", "new_text": "== 2"})
    assert not out.is_error and "== 2" in read(sb, "tests/test_new.py")


def test_a_test_file_that_existed_cannot_be_edited_even_by_a_second_tool_instance(sb):
    sb.write("tests/test_old.py", "assert 1\n")
    first = EditFile(sb)
    first.run({"path": "tests/test_new.py", "new_text": "x = 1\n"})
    other = EditFile(sb)  # fresh instance: does not know the first one's files
    assert other.run({"path": "tests/test_new.py", "old_text": "1", "new_text": "2"}).is_error
    assert first.run({"path": "tests/test_old.py", "old_text": "1", "new_text": "0"}).is_error


# -- protection through the tool ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["tests/test_a.py", "conftest.py", "pytest.ini", "pyproject.toml", ".github/workflows/ci.yml", "requirements.txt", "uv.lock"])
def test_protected_files_are_refused_for_replace(sb, path):
    sb.write(path, "value = 1\n")
    out = edit(sb, path=path, old_text="1", new_text="2")
    assert out.is_error and "not allowed to change" in out.text and read(sb, path) == "value = 1\n" and sb.writes == []


@pytest.mark.parametrize("path", ["pytest.ini", "conftest.py", "tests/conftest.py", ".github/workflows/ci.yml", "requirements.txt"])
def test_protected_kinds_cannot_be_created(sb, path):
    out = edit(sb, path=path, new_text="x\n")
    assert out.is_error and not (sb.root / path).exists()


def test_new_test_files_may_be_created_in_an_existing_tests_folder(sb):
    sb.write("tests/test_old.py", "pass\n")
    assert not edit(sb, path="tests/test_repro.py", new_text="def test_x():\n    assert 1\n").is_error


@pytest.mark.parametrize("text", ["@pytest.mark.skip\ndef test_a(): pass\n", "import pytest\npytest.skip('x')\n", "@pytest.mark.xfail\ndef test_a(): assert 0\n"])
def test_new_tests_may_not_hide_failures(sb, text):
    out = edit(sb, path="tests/test_new.py", new_text=text)
    assert out.is_error and "skip" in out.text and not (sb.root / "tests/test_new.py").exists()


def test_editing_a_created_test_cannot_add_a_skip(sb):
    tool = EditFile(sb)
    tool.run({"path": "tests/test_new.py", "new_text": "def test_a():\n    assert 0\n"})
    out = tool.run({"path": "tests/test_new.py", "old_text": "def test_a", "new_text": "@pytest.mark.xfail\ndef test_a"})
    assert out.is_error and "xfail" not in read(sb, "tests/test_new.py")


def test_skip_words_are_fine_in_source_files(sb):
    sb.write("src/a.py", "x = 1\n")
    assert not edit(sb, path="src/a.py", old_text="x = 1", new_text="skipif = xfail = 2").is_error


def test_the_caller_can_allow_a_protected_path_but_the_model_cannot(sb):
    sb.write("tox.ini", "[tox]\n")
    sb.write("setup.cfg", "[x]\n")
    tool = EditFile(sb, allowed_paths={"tox.ini"})
    assert not tool.run({"path": "tox.ini", "old_text": "[tox]", "new_text": "[tox2]"}).is_error
    assert tool.run({"path": "setup.cfg", "old_text": "[x]", "new_text": "[y]"}).is_error
    # no argument the model can send changes the rule
    out = tool.run({"path": "setup.cfg", "old_text": "[x]", "new_text": "[y]", "allowed_paths": ["setup.cfg"]})
    assert out.is_error and "allowed_paths" in out.text


def test_edit_arguments_are_checked(sb):
    for args in ({}, {"path": "a"}, {"new_text": "x"}, {"path": "a", "new_text": 5}, {"path": "a", "new_text": "x", "old_text": ""},
                 {"path": "a", "new_text": "x" * (er.MAX_TEXT_CHARS + 1)}, {"path": "a", "new_text": "x", "old_text": "y" * (er.MAX_TEXT_CHARS + 1)}):
        assert EditFile(sb).run(args).is_error


def test_edit_never_uses_a_shell_string_and_reads_nothing_it_does_not_need(sb):
    sb.write("a.py", "x\n")
    edit(sb, path="a.py", old_text="x", new_text="y")
    edit(sb, path="new/b.py", new_text="z")
    assert all(isinstance(c, list) for c in sb.commands)
    assert ReadFile(sb).run({"path": "a.py"}).text == "     1| y"
