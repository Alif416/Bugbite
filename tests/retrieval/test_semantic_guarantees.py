import json
import re
from pathlib import Path

import pytest
from sem_helpers import FILES, build
from idx_helpers import index_of

from bugbite.retrieval import (ChromaDefaultEmbedder, ChunkLimits, HashEmbedder, MemoryStore, RetrievalError, SemanticHit, SemanticIndex,
                               SemanticResults, render_semantic)
import bugbite.retrieval.semantic as semantic_module


def test_cleanup_after_close_with_block_and_error(tmp_path, monkeypatch):
    made = []
    real = semantic_module.tempfile.mkdtemp
    monkeypatch.setattr(semantic_module.tempfile, "mkdtemp", lambda **k: made.append(real(**k)) or made[-1])
    s, _, _ = build(tmp_path)
    assert Path(made[0]).is_dir()
    s.close()
    assert not Path(made[0]).exists() and s.closed
    s.close()  # twice is fine
    with build(tmp_path)[0]:
        assert Path(made[1]).is_dir()
    assert not Path(made[1]).exists()

    class Boom:
        name = "boom"

        def embed(self, texts):
            raise RuntimeError("secret detail")

    index, box = index_of(tmp_path / "x", FILES)
    with pytest.raises(RetrievalError, match="failed") as info:
        SemanticIndex.build(box, index, Boom(), store_factory=MemoryStore)
    assert "secret detail" not in str(info.value)
    assert not Path(made[2]).exists()


def test_search_on_a_closed_index_is_refused(tmp_path):
    s, _, _ = build(tmp_path)
    s.close()
    with pytest.raises(RetrievalError, match="closed"):
        s.search("retry")


@pytest.mark.parametrize("query, note", [("", "empty"), ("   \n", "empty"), ("zzzqqq", "close in meaning")])
def test_useless_queries_give_no_hits_and_a_note(tmp_path, query, note):
    with build(tmp_path)[0] as s:
        result = s.search(query)
        assert result.hits == () and any(note in n for n in result.notes)


def test_an_empty_repository_gives_no_hits_and_a_note(tmp_path):
    index, box = index_of(tmp_path, {"data.bin": b"\x00\x00"})
    with SemanticIndex.build(box, index, HashEmbedder(), store_factory=MemoryStore) as s:
        assert s.search("anything").notes[-1] == "There was no code to search." and s.chunk_count == 0


@pytest.mark.parametrize("bad", [0, -1, 51, True, 2.5, "3"])
def test_bad_max_results_are_refused(tmp_path, bad):
    with build(tmp_path)[0] as s, pytest.raises(RetrievalError):
        s.search("retry", bad)


def test_a_non_text_query_is_refused(tmp_path):
    with build(tmp_path)[0] as s, pytest.raises(RetrievalError):
        s.search(None)  # type: ignore[arg-type]


def test_max_results_limits_hits_and_order_is_deterministic(tmp_path):
    with build(tmp_path)[0] as s:
        a, b = s.search("cache retry config", 2), s.search("cache retry config", 2)
        assert len(a.hits) <= 2 and a == b
        scores = [h.score for h in s.search("cache retry config", 10).hits]
        assert scores == sorted(scores, reverse=True)


def test_a_huge_query_is_cut_and_noted(tmp_path):
    with build(tmp_path, limits=ChunkLimits(max_query_chars=50))[0] as s:
        result = s.search("retry " * 100_000)
        assert any("cut to 50" in n for n in result.notes) and result.hits


def test_many_symbols_stay_bounded(tmp_path):
    files = {f"m{i}.py": "".join(f"def func_{i}_{j}():\n    return {j}\n" for j in range(10)) for i in range(60)}
    with build(tmp_path, files, limits=ChunkLimits(max_chunks=100))[0] as s:
        assert s.chunk_count == 100 and len(s.search("func", 10).hits) <= 10


@pytest.mark.parametrize("make, fragment", [
    (lambda n: [[1.0]], "vectors for"),
    (lambda n: [[1.0], [1.0, 2.0]], "different lengths"),
    (lambda n: [[float("nan")]] * n, "non-finite"),
    (lambda n: [[]] * n, "empty"),
    (lambda n: "abc", "no list"),
    (lambda n: [["x"]] * n, "not a list of numbers"),
])
def test_bad_embedder_output_is_an_error_not_silence(tmp_path, make, fragment):
    class Bad:
        name = "bad"

        def embed(self, texts):
            return make(len(texts))

    index, box = index_of(tmp_path, {"a.py": "def f():\n    pass\n\ndef g():\n    pass\n"})
    with pytest.raises(RetrievalError, match=fragment):
        SemanticIndex.build(box, index, Bad(), store_factory=MemoryStore)


def test_results_round_trip_and_damaged_results_are_refused(tmp_path):
    with build(tmp_path)[0] as s:
        result = s.search("retry after timeout")
    assert SemanticResults.from_json(json.loads(json.dumps(result.to_json()))) == result
    data = result.to_json()
    for mutate in (lambda d: d["hits"][0].update(score=2.0), lambda d: d["hits"][0].update(path="../x"), lambda d: d["hits"][0].update(kind="nope"),
                   lambda d: d["hits"][0].update(line=0), lambda d: d.update(extra=1), lambda d: d["hits"].append({})):
        copy = json.loads(json.dumps(data))
        mutate(copy)
        with pytest.raises(RetrievalError):
            SemanticResults.from_json(copy)
    with pytest.raises(ValueError):
        SemanticHit("a.py", "f", "function", 1, 1, 0.0, "")


def test_rendering_is_short_whole_lines_and_says_what_was_left_out(tmp_path):
    with build(tmp_path)[0] as s:
        result = s.search("cache retry config timeout", 10)
    text = render_semantic(result, 2000)
    assert len(text) <= 2000 and "src/retry.py:" in text
    small = render_semantic(result, 200)
    assert len(small) <= 200 and "more matches not shown" in small
    assert all(line.startswith(("1.", "2.", "3.", "4.", "5.", "   ", "...", "note:")) for line in small.splitlines())
    with pytest.raises(ValueError):
        render_semantic(result, 50)


def test_the_module_reads_no_environment_and_uses_no_network_or_model_apis():
    root = Path(semantic_module.__file__).parent
    for name in ("semantic.py", "chunks.py", "embedders.py", "semantic_types.py"):
        source = (root / name).read_text()
        assert not re.search(r"os\.environ|getenv|import (requests|httpx|socket|urllib)|api_key", source), name
    assert "import chromadb" not in (root / "embedders.py").read_text().split("def _load")[0]  # imported lazily, inside the function


def test_a_missing_chromadb_gives_a_clear_error(monkeypatch, tmp_path):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("chromadb"):
            raise ImportError("no chromadb")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(RetrievalError, match="chromadb"):
        ChromaDefaultEmbedder().embed(["x"])
    index, box = index_of(tmp_path, FILES)
    with pytest.raises(RetrievalError, match="chromadb"):
        SemanticIndex.build(box, index, HashEmbedder())  # the default store is Chroma


def test_the_hash_embedder_is_deterministic_and_validates_size():
    a, b = HashEmbedder().embed(["retry timeout"]), HashEmbedder().embed(["retry timeout"])
    assert a == b and abs(sum(x * x for x in a[0]) - 1) < 1e-9
    with pytest.raises(ValueError):
        HashEmbedder(2)


def test_memory_store_ties_break_by_position():
    store = MemoryStore()
    store.add([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    assert store.query([1.0, 0.0], 3) == [(0, 1.0), (1, 1.0), (2, 0.0)]


class Spy:
    """Records what the embedder and the store are asked."""

    name = "spy"

    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return HashEmbedder().embed(texts)


def test_the_query_is_cut_before_it_reaches_the_embedder(tmp_path):
    spy = Spy()
    with build(tmp_path, embedder=spy, limits=ChunkLimits(max_query_chars=40))[0] as s:
        spy.texts.clear()
        s.search("retry " * 1000)
        assert spy.texts and all(len(t) == 40 for t in spy.texts)


def test_the_store_is_asked_for_more_than_is_returned_so_ties_break_the_same_way(tmp_path):
    asked = []

    class Store(MemoryStore):
        def query(self, vector, count):
            asked.append(count)
            return super().query(vector, count)

    index, box = index_of(tmp_path, {f"m{i}.py": f"def f{i}():\n    return 1\n" for i in range(10)})
    with SemanticIndex.build(box, index, HashEmbedder(), store_factory=Store) as s:
        s.search("f", 3)
    assert asked == [6]


def test_source_files_come_before_test_files_even_when_tests_sort_first(tmp_path):
    from bugbite.retrieval.chunks import plan_chunks

    index, _ = index_of(tmp_path, {"a_tests/test_one.py": "def test_one():\n    pass\n", "z.py": "def real():\n    pass\n"})
    chunks, _ = plan_chunks(index, ChunkLimits(max_chunks=1))
    assert [c.path for c in chunks] == ["z.py"]


def test_the_vector_check_catches_ragged_vectors_on_its_own():
    from bugbite.retrieval.embedders import check_vectors

    with pytest.raises(RetrievalError, match="different lengths"):
        check_vectors([[1.0], [1.0, 2.0]], 2, "x")


def test_an_embedders_own_retrieval_error_is_passed_on_unchanged(tmp_path):
    from bugbite.retrieval.errors import EMBEDDER_UNAVAILABLE

    class Missing:
        name = "missing"

        def embed(self, texts):
            raise RetrievalError(EMBEDDER_UNAVAILABLE, "model not installed")

    index, box = index_of(tmp_path, FILES)
    with pytest.raises(RetrievalError) as info:
        SemanticIndex.build(box, index, Missing(), store_factory=MemoryStore)
    assert info.value.code == EMBEDDER_UNAVAILABLE and "not installed" in str(info.value)
