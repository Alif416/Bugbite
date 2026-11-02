"""Index this repository's own code and check the result against an independent walk with `ast`."""

import ast
import time
from pathlib import Path

import pytest
from idx_helpers import make_repo  # noqa: F401  (also puts tests/agent on the path)
from tool_helpers import LocalSandbox

from bugbite.retrieval import build_index, render_symbols, render_tree

SRC = Path(__file__).resolve().parents[2] / "src" / "bugbite"


@pytest.fixture(scope="module")
def idx():
    box = LocalSandbox(SRC)
    return build_index(box)


def test_known_symbols_are_found(idx):
    run_agent = idx.get("run_agent")
    assert run_agent.path == "agent/loop.py" and run_agent.kind == "function" and run_agent.signature.startswith("(adapter")
    assert idx.get("ModelAdapter", "adapter/base.py").kind == "class"
    assert idx.get("ReplayProvider.generate", "replayer/provider.py").kind == "method"
    assert idx.get("RepoIndex.from_json").parent == "RepoIndex"
    assert idx.get("Sandbox.run", "sandbox/container.py") is not None
    assert [f.path for f in idx.files if f.path.endswith("scanner.py")] == ["retrieval/scanner.py"]


def test_the_whole_repo_fits_and_is_complete(idx):
    assert idx.complete and len(idx.files) > 50 and len(idx.symbols) > 500
    assert all(f.parse_error is None for f in idx.files)  # every file of ours parses


def test_every_symbol_matches_an_independent_ast_walk(idx):
    expected = 0
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        expected += sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in ast.walk(tree))
    assert len(idx.symbols) == expected


def test_line_ranges_are_inside_their_files(idx):
    for s in idx.symbols:
        assert 1 <= s.line <= s.end_line <= idx.file(s.path).lines, s


def test_the_views_stay_small_for_a_big_repo(idx):
    assert len(render_tree(idx, max_lines=60).splitlines()) <= 60 and len(render_symbols(idx.symbols, max_lines=40).splitlines()) <= 40
    assert len(render_tree(idx, max_lines=60)) < 8_000


def test_it_is_fast():
    start = time.monotonic()
    build_index(LocalSandbox(SRC))
    assert time.monotonic() - start < 10
