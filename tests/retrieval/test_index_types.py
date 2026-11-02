"""The index as data: lookups, the exact JSON round trip, and refusal of hostile input from the sandbox."""

import copy
import json

import pytest
from idx_helpers import index_of

from bugbite.retrieval import RepoIndex, RetrievalError, parse_scanner_output
from bugbite.retrieval.errors import BAD_OUTPUT

FILES = {"a.py": "class A:\n    def m(self): ...\n\ndef f(): ...\n", "b.py": "def f(): ...\nclass B: ...\n", "c.txt": "text\n"}


@pytest.fixture
def idx(tmp_path):
    return index_of(tmp_path, FILES)[0]


def test_lookups(idx):
    assert [(s.path, s.qualname) for s in idx.find("f")] == [("a.py", "f"), ("b.py", "f")]
    assert [s.qualname for s in idx.find("f", kind="function")] == ["f", "f"] and idx.find("f", kind="class") == []
    assert [s.qualname for s in idx.in_file("a.py")] == ["A", "A.m", "f"] and idx.in_file("c.txt") == [] and idx.in_file("zzz") == []
    assert [s.qualname for s in idx.by_kind("class")] == ["A", "B"] and [s.qualname for s in idx.by_kind("method")] == ["A.m"]
    assert idx.get("A.m").path == "a.py" and idx.get("f", "b.py").path == "b.py" and idx.symbol_count("a.py") == 3
    assert idx.file("c.txt").language == "text" and idx.complete
    with pytest.raises(ValueError):
        idx.by_kind("module")


def test_lookups_return_copies_so_the_index_cannot_be_changed(idx):
    idx.in_file("a.py").clear()
    idx.find("f").clear()
    assert len(idx.in_file("a.py")) == 3 and len(idx.find("f")) == 2
    with pytest.raises(Exception):
        idx.files[0].path = "x"  # type: ignore[misc]


def test_the_json_round_trip_is_exact(idx, tmp_path):
    rich, _ = index_of(tmp_path / "rich", {"m.py": '@a\n@b(1)\nasync def f(x: int) -> str:\n    """Doc."""\n    class L:\n        def g(self): ...\n', "bad.py": "def (:\n", "t.md": "x\n"})
    assert rich.symbols[0].decorators == ("a", "b(1)") and rich.symbols[0].is_async and rich.symbols[2].parent == "f.<locals>.L"
    assert RepoIndex.from_json(json.loads(json.dumps(rich.to_json()))) == rich
    again = RepoIndex.from_json(json.loads(json.dumps(idx.to_json())))
    assert again == idx and again.to_json() == idx.to_json() and again.find("f") == idx.find("f")
    assert idx.to_json()["schema_version"] == 1 and set(idx.to_json()) == {"schema_version", "files", "symbols", "truncated"}


def good(idx):
    return copy.deepcopy(idx.to_json())


def with_change(idx, change):
    data = good(idx)
    change(data)
    return data


HOSTILE = {
    "not an object": lambda d: [],
    "wrong version": lambda d: d.update(schema_version=2),
    "bool version": lambda d: d.update(schema_version=True),
    "missing files": lambda d: d.pop("files"),
    "extra top field": lambda d: d.update(extra=1),
    "files not a list": lambda d: d.update(files={}),
    "symbols not a list": lambda d: d.update(symbols="x"),
    "unknown truncation": lambda d: d.update(truncated=["because"]),
    "file not an object": lambda d: d["files"].__setitem__(0, "a.py"),
    "file missing field": lambda d: d["files"][0].pop("size"),
    "file extra field": lambda d: d["files"][0].update(mode=0o777),
    "absolute path": lambda d: d["files"][-1].update(path="/etc/passwd"),
    "dotdot path": lambda d: d["files"][-1].update(path="../x.py"),
    "dotdot inside": lambda d: d["files"][-1].update(path="a/../../x.py"),
    "backslash path": lambda d: d["files"][-1].update(path="a\\b.py"),
    "nul in path": lambda d: d["files"][-1].update(path="a\x00.py"),
    "empty path": lambda d: d["files"][-1].update(path=""),
    "double slash": lambda d: d["files"][-1].update(path="a//b.py"),
    "trailing slash": lambda d: d["files"][-1].update(path="a/"),
    "huge path": lambda d: d["files"][-1].update(path="a" * 2000),
    "negative size": lambda d: d["files"][0].update(size=-1),
    "bool size": lambda d: d["files"][0].update(size=True),
    "float lines": lambda d: d["files"][0].update(lines=1.5),
    "text size": lambda d: d["files"][0].update(size="10"),
    "long parse error": lambda d: d["files"][0].update(parse_error="x" * 500),
    "duplicate file": lambda d: d["files"].append(dict(d["files"][0])),
    "bad kind": lambda d: d["symbols"][0].update(kind="module"),
    "end before start": lambda d: d["symbols"][0].update(end_line=0),
    "line zero": lambda d: d["symbols"][0].update(line=0),
    "end beyond the file": lambda d: d["symbols"][0].update(end_line=999),
    "symbol in unlisted file": lambda d: d["symbols"][0].update(path="nope.py"),
    "symbol in text file": lambda d: d["symbols"][0].update(path="c.txt"),
    "huge doc": lambda d: d["symbols"][0].update(doc="d" * 1000),
    "huge name": lambda d: d["symbols"][0].update(name="n" * 1000),
    "empty name": lambda d: d["symbols"][0].update(name=""),
    "decorators not a list": lambda d: d["symbols"][0].update(decorators="x"),
    "too many decorators": lambda d: d["symbols"][0].update(decorators=["d"] * 11),
    "non-text decorator": lambda d: d["symbols"][0].update(decorators=[1]),
    "is_async as number": lambda d: d["symbols"][0].update(is_async=1),
    "parent as number": lambda d: d["symbols"][0].update(parent=5),
    "symbol extra field": lambda d: d["symbols"][0].update(code="import os"),
    "symbol not an object": lambda d: d["symbols"].__setitem__(0, None),
}


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_output_is_refused(idx, name):
    data = good(idx)
    result = HOSTILE[name](data)
    data = result if result is not None else data
    with pytest.raises(RetrievalError) as caught:
        RepoIndex.from_json(data)
    assert caught.value.code == BAD_OUTPUT and "not valid" in caught.value.message


def test_a_parse_error_file_cannot_carry_symbols(tmp_path):
    idx, _ = index_of(tmp_path, {"bad.py": "def (:\n", "ok.py": "def f(): ...\n"})
    data = good(idx)
    data["symbols"][0]["path"] = "bad.py"
    with pytest.raises(RetrievalError, match="no symbols"):
        RepoIndex.from_json(data)


def test_too_many_items_are_refused(idx):
    data = good(idx)
    data["symbols"] = data["symbols"] * 70_000
    with pytest.raises(RetrievalError, match="at most"):
        RepoIndex.from_json(data)


@pytest.mark.parametrize("text", ["", "not json", "[1,", "null", "{}", '{"schema_version": 1}', "[" * 100_000])
def test_scanner_output_that_is_not_an_index_is_refused(text):
    with pytest.raises(RetrievalError) as caught:
        parse_scanner_output(text)
    assert caught.value.code == BAD_OUTPUT


def test_the_error_message_does_not_echo_long_hostile_text(idx):
    data = good(idx)
    data["files"][0]["path"] = "/" + "SECRET" * 100
    with pytest.raises(RetrievalError) as caught:
        RepoIndex.from_json(data)
    assert len(caught.value.message) < 200


def test_error_codes_are_checked():
    with pytest.raises(ValueError):
        RetrievalError("made_up", "x")
    with pytest.raises(ValueError):
        RetrievalError(BAD_OUTPUT, "")
