"""What the scanner finds in Python source, and how it copes with awkward files and folders."""

import os

import pytest
from idx_helpers import index_of, names

SOURCE = '''"""Module doc."""
import os


@decorator
@other(1, x=2)
def func(a, b=1, *args, key: int = 2, **kw) -> int:
    """Do the thing.

    Longer text that must not appear.
    """
    def inner(x):
        return x

    class Local:
        def method(self): ...

    return inner(a)


async def fetch(url: str) -> bytes:
    """Fetch."""


class Base(Parent, metaclass=Meta):
    """A class.

    More.
    """

    attr = 1

    def method(self, x):
        pass

    async def amethod(self):
        pass

    @staticmethod
    def static():
        pass

    class Nested:
        def deep(self): ...


if True:
    def conditional(): ...
else:
    def conditional(): ...

try:
    import fast
except ImportError:
    def fallback(): ...

lam = lambda x: x
'''


@pytest.fixture
def idx(tmp_path):
    return index_of(tmp_path, {"pkg/mod.py": SOURCE})[0]


def sym(idx, qualname, nth=0):
    return [s for s in idx.symbols if s.qualname == qualname][nth]


def test_every_kind_of_definition_is_found_in_source_order(idx):
    assert names(idx) == [
        "func", "func.<locals>.inner", "func.<locals>.Local", "func.<locals>.Local.method", "fetch", "Base", "Base.method", "Base.amethod",
        "Base.static", "Base.Nested", "Base.Nested.deep", "conditional", "conditional", "fallback",
    ]


def test_kinds_and_parents(idx):
    kinds = {s.qualname: s.kind for s in idx.symbols}
    assert kinds["func"] == "function" and kinds["func.<locals>.inner"] == "function" and kinds["fetch"] == "function"
    assert kinds["Base"] == "class" and kinds["Base.Nested"] == "class" and kinds["func.<locals>.Local"] == "class"
    assert kinds["Base.method"] == "method" and kinds["Base.Nested.deep"] == "method" and kinds["func.<locals>.Local.method"] == "method"
    assert sym(idx, "func").parent is None and sym(idx, "Base.method").parent == "Base"
    assert sym(idx, "func.<locals>.inner").parent == "func" and sym(idx, "Base.Nested.deep").parent == "Base.Nested"


def lineno(text):
    return next(n for n, line in enumerate(SOURCE.splitlines(), 1) if line == text)


def test_lines_cover_the_whole_definition(idx):
    assert (sym(idx, "func").line, sym(idx, "func").end_line) == (lineno("def func(a, b=1, *args, key: int = 2, **kw) -> int:"), lineno("    return inner(a)"))
    assert (sym(idx, "Base").line, sym(idx, "Base").end_line) == (lineno("class Base(Parent, metaclass=Meta):"), lineno("        def deep(self): ..."))
    assert sym(idx, "Base.static").line == lineno("    def static():")  # the decorator is on the line above it
    assert sym(idx, "Base.static").line - 1 == lineno("    @staticmethod")


def test_a_one_line_definition_starts_and_ends_on_the_same_line(tmp_path):
    one, _ = index_of(tmp_path, {"a.py": "def f(): pass\n"})
    assert (one.symbols[0].line, one.symbols[0].end_line) == (1, 1)


def test_signatures(idx):
    assert sym(idx, "func").signature == "(a, b=1, *args, key: int=2, **kw) -> int"
    assert sym(idx, "fetch").signature == "(url: str) -> bytes" and sym(idx, "fetch").is_async
    assert sym(idx, "Base").signature == "(Parent, metaclass=Meta)"
    assert sym(idx, "Base.Nested").signature == "" and sym(idx, "Base.method").signature == "(self, x)"
    assert not sym(idx, "func").is_async and sym(idx, "Base.amethod").is_async


def test_docstrings_are_the_first_line_only(idx):
    assert sym(idx, "func").doc == "Do the thing." and sym(idx, "Base").doc == "A class." and sym(idx, "fetch").doc == "Fetch."
    assert sym(idx, "Base.method").doc == ""


def test_decorators(idx):
    assert sym(idx, "func").decorators == ("decorator", "other(1, x=2)") and sym(idx, "Base.static").decorators == ("staticmethod",)
    assert sym(idx, "Base.method").decorators == ()


def test_a_name_defined_twice_is_listed_twice_and_get_returns_the_first(idx):
    both = [s for s in idx.symbols if s.name == "conditional"]
    assert len(both) == 2 and both[0].line < both[1].line
    assert idx.get("conditional") == both[0] and idx.get("conditional", "pkg/mod.py") == both[0] and idx.get("nope") is None
    assert idx.get("conditional", "other.py") is None


def test_lambdas_and_assignments_are_not_symbols(idx):
    assert "lam" not in names(idx) and "attr" not in names(idx)


def test_the_file_tree_has_every_file_with_size_language_and_lines(tmp_path):
    idx, _ = index_of(tmp_path, {"b.py": "x = 1\ny = 2\n", "a/c.md": "hi", "a/d.json": "{}\n", "noext": "z\n\n", "e.PY": "def f(): ...\n"})
    got = {f.path: (f.size, f.language, f.lines) for f in idx.files}
    assert got == {"b.py": (12, "python", 2), "a/c.md": (2, "markdown", 1), "a/d.json": (3, "json", 1), "noext": (3, "other", 2), "e.PY": (13, "python", 1)}
    assert idx.file("b.py").parse_error is None and idx.file("missing") is None
    assert names(idx, "e.PY") == ["f"]  # the extension check is not case sensitive


def test_files_come_in_a_stable_order(tmp_path):
    files = {f"d{i % 3}/f{i}.py": "def f(): ...\n" for i in range(12)} | {"top.py": "x=1\n"}
    a, _ = index_of(tmp_path / "a", files)
    b, _ = index_of(tmp_path / "b", dict(reversed(list(files.items()))))
    assert a == b and a.to_json() == b.to_json()


@pytest.mark.parametrize("junk", [".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "x.egg-info", "site-packages"])
def test_junk_folders_are_skipped(tmp_path, junk):
    idx, _ = index_of(tmp_path, {f"{junk}/m.py": "def hidden(): ...\n", f"src/{junk}/m.py": "def hidden2(): ...\n", "ok.py": "def shown(): ...\n"})
    assert [f.path for f in idx.files] == ["ok.py"] and names(idx) == ["shown"]


def test_a_file_that_does_not_parse_is_listed_with_a_reason_and_the_scan_goes_on(tmp_path):
    idx, _ = index_of(tmp_path, {"bad.py": "def (:\n", "good.py": "def ok(): ...\n", "zz.py": "class A: ...\n"})
    assert "SyntaxError" in idx.file("bad.py").parse_error and idx.in_file("bad.py") == []
    assert names(idx) == ["ok", "A"]


def test_null_bytes_and_binary_files(tmp_path):
    idx, _ = index_of(tmp_path, {"n.py": b"def f(): pass\n\x00\n", "blob.bin": b"\x00\x01\x02", "ok.py": "def g(): ...\n"})
    assert idx.file("n.py").parse_error == "contains null bytes" and idx.file("n.py").lines is None and idx.in_file("n.py") == []
    assert idx.file("blob.bin").language == "binary" and idx.file("blob.bin").lines is None and idx.file("blob.bin").parse_error is None
    assert names(idx) == ["g"]


def test_files_in_other_encodings(tmp_path):
    latin = b"# -*- coding: latin-1 -*-\ndef caf\xe9(): ...\n"  # declared latin-1, so valid
    bad = b"x = \"\xff\xfe\"\n"  # not UTF-8 and no declaration
    idx, _ = index_of(tmp_path, {"latin.py": latin, "bad.py": bad, "bom.py": b"\xef\xbb\xbfdef bom(): ...\n"})
    assert names(idx, "latin.py") == ["café"] and names(idx, "bom.py") == ["bom"]
    assert idx.file("bad.py").parse_error and idx.in_file("bad.py") == []


def test_unicode_names_survive_the_trip(tmp_path):
    idx, _ = index_of(tmp_path, {"ü/ñ.py": "class Ünï: ...\ndef 変数(): ...\n"})
    assert names(idx) == ["Ünï", "変数"] and idx.files[0].path == "ü/ñ.py"


def test_empty_files_and_a_file_without_a_final_newline(tmp_path):
    idx, _ = index_of(tmp_path, {"empty.py": "", "nonl.py": "def f(): ...", "blank.py": "\n\n"})
    assert (idx.file("empty.py").lines, idx.file("nonl.py").lines, idx.file("blank.py").lines) == (0, 1, 2)
    assert names(idx) == ["f"]


def test_a_file_over_the_size_limit_is_not_parsed(tmp_path):
    idx, _ = index_of(tmp_path, {"big.py": "def f(): ...\n" + "# pad\n" * 50, "big.txt": "x" * 400, "ok.py": "def g(): ...\n"}, max_file_bytes=300)
    assert "too large" in idx.file("big.py").parse_error and idx.file("big.py").lines is None and idx.in_file("big.py") == []
    assert idx.file("big.txt").lines is None and idx.file("big.txt").parse_error is None
    assert names(idx) == ["g"]


def test_deeply_nested_source_does_not_crash_the_scanner(tmp_path):
    deep = "".join("    " * i + f"def f{i}():\n" for i in range(60)) + "    " * 60 + "pass\n"
    idx, _ = index_of(tmp_path, {"deep.py": deep, "expr.py": "x = " + "(" * 400 + "1" + ")" * 400 + "\n", "ok.py": "def g(): ...\n"})
    assert idx.file("expr.py") is not None and names(idx, "ok.py") == ["g"]
    assert names(idx, "deep.py")[:3] == ["f0", "f0.<locals>.f1", "f0.<locals>.f1.<locals>.f2"]
    assert all(len(q) <= 400 for q in names(idx, "deep.py")) and 1 < len(names(idx, "deep.py")) < 60  # the deepest levels are dropped, nothing breaks


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_symlinks_are_never_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("def stolen(): ...\n")
    box_dir = tmp_path / "r"
    box_dir.mkdir()
    (box_dir / "real.py").write_text("def real(): ...\n")
    os.symlink(outside, box_dir / "linked_dir")
    os.symlink(outside / "secret.py", box_dir / "linked_file.py")
    os.symlink(box_dir, box_dir / "loop")  # a loop back to the repo itself
    os.symlink("real.py", box_dir / "alias.py")  # even a link inside the repo is skipped: the target is listed once
    idx = index_of(tmp_path, {})[0]
    assert [f.path for f in idx.files] == ["real.py"] and names(idx) == ["real"]


def test_match_statements_and_modern_syntax(tmp_path):
    src = "match x:\n    case 1:\n        def in_case(): ...\n\nasync def f():\n    async with a:\n        def in_with(): ...\n"
    idx, _ = index_of(tmp_path, {"m.py": src})
    assert names(idx) == ["in_case", "f", "f.<locals>.in_with"]


def test_limits_mark_the_index_as_truncated(tmp_path):
    files = {f"f{i:02}.py": "def a(): ...\ndef b(): ...\n" for i in range(10)}
    few, _ = index_of(tmp_path / "1", files, max_files=4)
    assert len(few.files) == 4 and few.truncated == ("max_files",) and not few.complete
    many, _ = index_of(tmp_path / "2", files, max_symbols=5)
    assert len(many.symbols) == 5 and "max_symbols" in many.truncated
    small, _ = index_of(tmp_path / "3", files, max_output_bytes=1500)
    assert 0 < len(small.files) < 10 and small.truncated == ("output_budget",)
    deep, _ = index_of(tmp_path / "4", {"a/b/c/d.py": "def f(): ...\n", "top.py": "def g(): ...\n"}, max_depth=2)
    assert names(deep) == ["g"] and deep.truncated == ("max_depth",)
    full, _ = index_of(tmp_path / "5", files)
    assert full.complete and len(full.files) == 10 and len(full.symbols) == 20


def test_the_scanner_writes_nothing_and_runs_no_repo_code(tmp_path):
    marker = tmp_path / "MARKER"
    evil = f"import pathlib\npathlib.Path({str(marker)!r}).write_text('ran')\nraise SystemExit(7)\ndef f(): ...\n"
    idx, box = index_of(tmp_path, {"evil.py": evil, "conftest.py": evil, "setup.py": evil, "__init__.py": evil})
    before = box.snapshot()
    from bugbite.retrieval import build_index

    build_index(box)
    assert not marker.exists() and box.snapshot() == before and names(idx, "evil.py") == ["f"]
    assert box.writes == [] and all(c[0] == "python" for c in box.commands)


def test_random_sources_never_crash_the_scanner_and_ranges_are_valid(tmp_path):
    import random

    rng = random.Random(7)
    pieces = ["def f(a, b=1):\n    pass\n", "class C(B):\n    def m(self): ...\n", "async def g():\n    await x\n", "if x:\n    def h(): ...\n",
              "    @d\n", "def (:\n", ")\n", "\t\n", "x = [\n", "lambda: 1\n", "'''unterminated\n", "é = 1\n", "\x0c\n", "class\n", "@\n", "while 1:\n    class K: ...\n"]
    sources = {f"r{i}.py": "".join(rng.choice(pieces) for _ in range(rng.randint(0, 12))) for i in range(150)}
    idx, _ = index_of(tmp_path, sources)
    assert len(idx.files) == 150
    for s in idx.symbols:
        entry = idx.file(s.path)
        assert 1 <= s.line <= s.end_line <= entry.lines and entry.parse_error is None
