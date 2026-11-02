import os

import pytest
from sem_helpers import FILES, build
from idx_helpers import index_of

from bugbite.retrieval import Chunk, ChunkLimits, RetrievalError
from bugbite.retrieval.chunks import plan_chunks, read_sources


def test_one_chunk_per_symbol_and_a_head_chunk_for_symbol_less_files(tmp_path):
    index, box = index_of(tmp_path, FILES)
    chunks, notes = plan_chunks(index, ChunkLimits())
    names = [(c.path, c.qualname, c.kind) for c in chunks]
    assert ("src/retry.py", "retry_after_timeout", "function") in names
    assert ("src/config.py", "ConfigParser.load", "method") in names
    assert ("src/config.py", "ConfigParser", "class") in names
    assert ("notes.txt", "notes.txt", "file") in names
    assert notes == []
    assert names.index(("tests/test_retry.py", "test_retry_after_timeout", "function")) == len(names) - 1 or names[-1][0].startswith("tests/")


def test_nested_functions_and_binary_files_are_skipped(tmp_path):
    files = {"a.py": "def outer():\n    def inner():\n        pass\n    return inner\n", "b.bin": b"\x00\x01\x02" * 50}
    index, _ = index_of(tmp_path, files)
    chunks, _ = plan_chunks(index, ChunkLimits())
    assert [c.qualname for c in chunks] == ["outer"]


def test_a_class_chunk_is_short_and_a_function_chunk_is_longer(tmp_path):
    body = "".join(f"    x{i} = {i}\n" for i in range(100))
    index, _ = index_of(tmp_path, {"a.py": "class Big:\n    '''Doc.'''\n" + body + "\ndef f():\n" + body})
    chunks, _ = plan_chunks(index, ChunkLimits())
    spans = {c.qualname: c.end_line - c.line + 1 for c in chunks}
    assert spans["Big"] == 12 and spans["f"] == 40


def test_the_chunk_cap_keeps_source_before_test_files_and_says_so(tmp_path):
    index, _ = index_of(tmp_path, FILES)
    chunks, notes = plan_chunks(index, ChunkLimits(max_chunks=3))
    assert len(chunks) == 3 and not any(c.path.startswith("tests/") for c in chunks)
    assert "Only 3 of" in notes[0]


def test_an_incomplete_index_is_noted(tmp_path):
    index, _ = index_of(tmp_path, FILES, max_files=2)
    _, notes = plan_chunks(index, ChunkLimits())
    assert any("incomplete" in n for n in notes)


def test_source_text_is_read_and_cut_to_the_limit(tmp_path):
    index, box = index_of(tmp_path, FILES)
    chunks, _ = plan_chunks(index, ChunkLimits(max_chunk_chars=60))
    filled = read_sources(box, chunks, ChunkLimits(max_chunk_chars=60))
    assert len(filled) == len(chunks) and all(len(c.source) <= 60 for c in filled)
    assert "TimeoutError" in next(c for c in read_sources(box, plan_chunks(index, ChunkLimits())[0], ChunkLimits()) if c.qualname == "retry_after_timeout").source


def test_a_symlink_out_of_the_repo_is_never_read(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET\n")
    index, box = index_of(tmp_path, {"a.py": "x = 1\n"})
    os.symlink(secret, box.root / "leak.txt")
    chunk = Chunk("leak.txt", "leak.txt", "file", 1, 5, "file", "")
    assert read_sources(box, [chunk], ChunkLimits())[0].source == ""


def test_many_chunks_are_read_in_several_bounded_calls(tmp_path):
    index, box = index_of(tmp_path, {f"m{i}.py": f"def f{i}():\n    return {i}\n" for i in range(150)})
    chunks, _ = plan_chunks(index, ChunkLimits())
    before = len(box.commands)
    filled = read_sources(box, chunks, ChunkLimits())
    assert len(box.commands) - before > 1 and all(c.source for c in filled)


def test_bad_limits_are_refused():
    for bad in (0, -1, True, 1.5):
        with pytest.raises(RetrievalError):
            ChunkLimits(max_chunks=bad)


def test_reader_output_that_does_not_match_is_refused(tmp_path):
    index, box = index_of(tmp_path, FILES)
    chunks, _ = plan_chunks(index, ChunkLimits())

    class Liar:
        def run(self, *a, **k):
            from bugbite.sandbox import CommandResult
            return CommandResult(0, "[]", "", False, 0.0, False)

    with pytest.raises(RetrievalError, match="did not match"):
        read_sources(Liar(), chunks, ChunkLimits())
