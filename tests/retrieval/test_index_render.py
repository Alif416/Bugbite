"""The text views: always bounded, always say what they left out."""

import pytest
from idx_helpers import index_of

from bugbite.retrieval import render_symbols, render_tree


@pytest.fixture
def idx(tmp_path):
    files = {"src/app/main.py": "class App:\n    def run(self, x) -> int: ...\n", "src/app/util.py": "async def helper(): ...\n", "README.md": "hi\n",
             "tests/test_a.py": "def test_a(): ...\n", "src/z.txt": "z\n"}
    return index_of(tmp_path, files)[0]


def test_the_tree(idx):
    assert render_tree(idx).splitlines() == [
        "src/", "  app/", "    main.py  (2 symbols)", "    util.py  (1 symbols)", "  z.txt", "tests/", "  test_a.py  (1 symbols)", "README.md",
    ]


def test_the_tree_is_bounded_and_says_how_much_is_missing(idx):
    out = render_tree(idx, max_lines=4).splitlines()
    assert len(out) == 4 and out[-1] == "... 5 more lines not shown" and out[0] == "src/"


def test_an_incomplete_index_says_so(tmp_path):
    idx, _ = index_of(tmp_path, {f"f{i}.py": "x=1\n" for i in range(5)}, max_files=2)
    out = render_tree(idx, max_lines=10)
    assert out.splitlines()[-1] == "(index incomplete: max_files)"
    assert len(render_tree(idx, max_lines=2).splitlines()) == 2


def test_symbols(idx):
    assert render_symbols(idx.symbols).splitlines() == [
        "src/app/main.py:1 class App", "src/app/main.py:2 method App.run(self, x) -> int", "src/app/util.py:1 async def helper()", "tests/test_a.py:1 def test_a()",
    ]


def test_docstring_lines_are_shown(tmp_path):
    idx, _ = index_of(tmp_path, {"a.py": 'def f():\n    """Does f."""\n'})
    assert render_symbols(idx.symbols) == "a.py:1 def f() - Does f."


def test_symbols_are_bounded(idx):
    out = render_symbols(idx.symbols, max_lines=2).splitlines()
    assert out == ["src/app/main.py:1 class App", "... and 3 more symbols"]
    assert render_symbols([]) == ""


def test_long_lines_are_cut(tmp_path):
    idx, _ = index_of(tmp_path, {"a.py": "def f(" + ", ".join(f"arg{i}" for i in range(100)) + "): ...\n"})
    assert all(len(line) <= 200 for line in render_symbols(idx.symbols).splitlines())


def test_the_output_is_the_same_every_time(idx):
    assert render_tree(idx) == render_tree(idx) and render_symbols(idx.symbols) == render_symbols(list(idx.symbols))


@pytest.mark.parametrize("bad", [0, 1, -3, 2.5, True, None])
def test_the_line_limit_must_be_sensible(idx, bad):
    with pytest.raises(ValueError):
        render_tree(idx, max_lines=bad)
    with pytest.raises(ValueError):
        render_symbols(idx.symbols, max_lines=bad)
