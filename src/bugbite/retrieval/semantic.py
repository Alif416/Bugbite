"""Semantic search: embed the chunks of a repository once, then find those closest in meaning to a question.

The vector store is built per job in a temporary folder that is deleted on `close()`, also after an error.
Chroma is the real store; a small in-memory store with the same interface lets tests run without it.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from bugbite.sandbox.setup import REPO_DIR

from .chunks import Chunk, ChunkLimits, plan_chunks, read_sources
from .embedders import Embedder, embed_all
from .errors import BAD_QUERY, EMBEDDER_UNAVAILABLE, EMBED_FAILED, RetrievalError
from .semantic_types import SemanticHit, SemanticResults
from .types import RepoIndex

MAX_RESULTS = 50


class VectorStore(Protocol):
    def add(self, vectors: Sequence[Sequence[float]]) -> None: ...  # ids are the positions, in order

    def query(self, vector: Sequence[float], count: int) -> list[tuple[int, float]]: ...  # (position, cosine similarity)

    def close(self) -> None: ...


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else [0.0] * len(vector)


class MemoryStore:
    """Brute force cosine search in plain Python. Fine for thousands of chunks; used by tests."""

    def __init__(self, directory: Path | None = None) -> None:
        self._vectors: list[list[float]] = []

    def add(self, vectors: Sequence[Sequence[float]]) -> None:
        self._vectors.extend(_unit(v) for v in vectors)

    def query(self, vector: Sequence[float], count: int) -> list[tuple[int, float]]:
        query = _unit(vector)
        scored = [(i, sum(a * b for a, b in zip(query, v))) for i, v in enumerate(self._vectors)]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:count]

    def close(self) -> None:
        self._vectors = []


class ChromaStore:
    """The Chroma vector store, kept in the job's temporary folder. Telemetry is off: nothing is reported anywhere."""

    def __init__(self, directory: Path) -> None:
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise RetrievalError(
                EMBEDDER_UNAVAILABLE, "Semantic search needs the 'chromadb' package, which is not installed."
            ) from None
        try:
            self._client = chromadb.PersistentClient(path=str(directory), settings=Settings(anonymized_telemetry=False))
            self._collection = self._client.create_collection("chunks", metadata={"hnsw:space": "cosine"}, embedding_function=None)
        except Exception as exc:
            raise RetrievalError(EMBEDDER_UNAVAILABLE, f"The vector store could not be started ({type(exc).__name__}).") from None
        self._count = 0

    def add(self, vectors: Sequence[Sequence[float]]) -> None:
        try:
            for start in range(0, len(vectors), 500):
                part = vectors[start : start + 500]
                ids = [str(self._count + i) for i in range(len(part))]
                self._collection.add(ids=ids, embeddings=[list(v) for v in part])
                self._count += len(part)
        except Exception as exc:
            raise RetrievalError(EMBED_FAILED, f"The vector store rejected the vectors ({type(exc).__name__}).") from None

    def query(self, vector: Sequence[float], count: int) -> list[tuple[int, float]]:
        try:
            found = self._collection.query(query_embeddings=[list(vector)], n_results=max(1, min(count, self._count)))
            ids, distances = found["ids"][0], found["distances"][0]
            return [(int(i), 1.0 - float(d)) for i, d in zip(ids, distances)]
        except Exception as exc:
            raise RetrievalError(EMBED_FAILED, f"The vector store search failed ({type(exc).__name__}).") from None

    def close(self) -> None:
        self._collection = None
        self._client = None


StoreFactory = Callable[[Path], VectorStore]


class SemanticIndex:
    """Build with `SemanticIndex.build(...)`, search with `.search(...)`, and `.close()` (or use `with`)."""

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder, store: VectorStore, directory: Path, limits: ChunkLimits, notes: Sequence[str]):
        self._chunks = list(chunks)
        self._embedder = embedder
        self._store: VectorStore | None = store
        self._directory = directory
        self._limits = limits
        self._notes = tuple(notes)

    @classmethod
    def build(
        cls,
        sandbox: Any,
        index: RepoIndex,
        embedder: Embedder,
        *,
        limits: ChunkLimits | None = None,
        store_factory: StoreFactory = ChromaStore,
        root: str = REPO_DIR,
        timeout: float | None = None,
    ) -> "SemanticIndex":
        limits = limits or ChunkLimits()
        planned, notes = plan_chunks(index, limits)
        directory = Path(tempfile.mkdtemp(prefix="bugbite-semantic-"))
        store: VectorStore | None = None
        try:
            chunks = read_sources(sandbox, planned, limits, root=root, timeout=timeout)
            store = store_factory(directory)
            if chunks:
                store.add(embed_all(embedder, [c.text for c in chunks]))
            return cls(chunks, embedder, store, directory, limits, notes)
        except BaseException:
            if store is not None:
                store.close()
            shutil.rmtree(directory, ignore_errors=True)
            raise

    # -- use ---------------------------------------------------------------------------------------
    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def closed(self) -> bool:
        return self._store is None

    def search(self, query: str, max_results: int = 10) -> SemanticResults:
        if self._store is None:
            raise RetrievalError(BAD_QUERY, "The semantic index is closed.")
        if not isinstance(query, str):
            raise RetrievalError(BAD_QUERY, "The query must be text.")
        if type(max_results) is not int or not 1 <= max_results <= MAX_RESULTS:
            raise RetrievalError(BAD_QUERY, f"max_results must be a whole number from 1 to {MAX_RESULTS}.")
        notes = list(self._notes)
        text = query.strip()
        if not text:
            return SemanticResults((), len(self._chunks), tuple(notes + ["The query was empty."]))
        if len(text) > self._limits.max_query_chars:
            text = text[: self._limits.max_query_chars]
            notes.append(f"The query was cut to {self._limits.max_query_chars} characters.")
        if not self._chunks:
            return SemanticResults((), 0, tuple(notes + ["There was no code to search."]))
        (vector,) = embed_all(self._embedder, [text])
        found = self._store.query(vector, min(len(self._chunks), max_results * 2))  # over-fetch so ties are broken the same way every time
        hits = []
        for position, similarity in found:
            if not 0 <= position < len(self._chunks) or not math.isfinite(similarity) or similarity <= 0:
                continue
            c = self._chunks[position]
            hits.append(SemanticHit(c.path, c.qualname, c.kind, c.line, c.end_line, round(min(similarity, 1.0), 4), c.preview))
        hits.sort(key=lambda h: (-h.score, h.path, h.line))
        hits = [h for h in hits if h.score > 0][:max_results]
        if not hits:
            notes.append("Nothing in the repository was close in meaning to the query.")
        return SemanticResults(tuple(hits), len(self._chunks), tuple(notes))

    def close(self) -> None:
        store, self._store = self._store, None
        if store is not None:
            store.close()
        shutil.rmtree(self._directory, ignore_errors=True)

    def __enter__(self) -> "SemanticIndex":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
