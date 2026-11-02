"""The real Chroma store (and, if present, the real model). Skipped when chromadb is not installed."""

from pathlib import Path

import pytest
from sem_helpers import FILES, build

chromadb = pytest.importorskip("chromadb")

from bugbite.retrieval import ChromaDefaultEmbedder, ChromaStore, HashEmbedder, SemanticIndex  # noqa: E402


def test_the_chroma_store_finds_the_same_first_hit_as_the_memory_store(tmp_path):
    with build(tmp_path / "a")[0] as memory:
        expected = memory.search("run again after a timeout error").hits[0]
    index_dir = tmp_path / "b"
    from idx_helpers import index_of

    index, box = index_of(index_dir, FILES)
    with SemanticIndex.build(box, index, HashEmbedder(), store_factory=ChromaStore) as s:
        got = s.search("run again after a timeout error").hits[0]
    assert (got.path, got.qualname) == (expected.path, expected.qualname) and abs(got.score - expected.score) < 0.01


def test_the_chroma_folder_is_removed_after_close(tmp_path, monkeypatch):
    import bugbite.retrieval.semantic as m

    made = []
    real = m.tempfile.mkdtemp
    monkeypatch.setattr(m.tempfile, "mkdtemp", lambda **k: made.append(real(**k)) or made[-1])
    from idx_helpers import index_of

    index, box = index_of(tmp_path, FILES)
    s = SemanticIndex.build(box, index, HashEmbedder(), store_factory=ChromaStore)
    assert any(Path(made[0]).iterdir())
    s.close()
    assert not Path(made[0]).exists()


def test_the_real_model_finds_the_right_chunk_for_a_plain_words_question(tmp_path):
    try:
        ChromaDefaultEmbedder().embed(["warm up"])
    except Exception as exc:
        pytest.skip(f"the embedding model is not available offline: {exc}")
    from idx_helpers import index_of

    index, box = index_of(tmp_path, FILES)
    with SemanticIndex.build(box, index, ChromaDefaultEmbedder(), store_factory=ChromaStore) as s:
        assert s.search("seconds to wait before the next attempt").hits[0].qualname == "backoff_delay"
        assert s.search("load settings from a yaml file").hits[0].qualname == "ConfigParser.load"
        assert s.search("remove the oldest item").hits[0].qualname == "Cache.evict"
        # a vaguer question still lands in the right file: both retry functions come before anything else
        assert {h.qualname for h in s.search("how long to wait before trying again", 2).hits} == {"retry_after_timeout", "backoff_delay"}
