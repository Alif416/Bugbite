"""Build an index of a throw-away repository with the real scanner, run on the host through the stand-in sandbox."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from tool_helpers import LocalSandbox  # noqa: E402

from bugbite.retrieval import IndexLimits, build_index  # noqa: E402


def make_repo(tmp_path, files):
    (tmp_path / "r").mkdir(parents=True, exist_ok=True)
    box = LocalSandbox(tmp_path / "r")
    for rel, text in files.items():
        box.write(rel, text)
    return box


def index_of(tmp_path, files, **limits):
    box = make_repo(tmp_path, files)
    return build_index(box, limits=IndexLimits(**limits) if limits else None), box


def names(index, path=None):
    return [s.qualname for s in (index.symbols if path is None else index.in_file(path))]
