"""Turning text into vectors. The real embedder runs on this machine (nothing is sent anywhere); the hash embedder is for tests."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Protocol, Sequence, runtime_checkable

from .errors import EMBED_FAILED, EMBEDDER_UNAVAILABLE, RetrievalError
from .words import split_words

BATCH_SIZE = 64


@runtime_checkable
class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def check_vectors(vectors: Any, expected: int, embedder_name: str) -> list[list[float]]:
    """Embedders are not trusted: wrong count, ragged, empty or non-finite output is an error, never silent."""
    problem = None
    if not isinstance(vectors, (list, tuple)) or len(vectors) != expected:
        problem = f"returned {len(vectors) if isinstance(vectors, (list, tuple)) else 'no list of'} vectors for {expected} texts"
    else:
        width = None
        for vector in vectors:
            try:
                numbers = [float(x) for x in vector]
            except (TypeError, ValueError):
                problem = "returned a vector that is not a list of numbers"
                break
            if not numbers or not all(math.isfinite(x) for x in numbers):
                problem = "returned an empty vector or one with non-finite numbers"
                break
            if width is None:
                width = len(numbers)
            elif len(numbers) != width:
                problem = "returned vectors of different lengths"
                break
    if problem:
        raise RetrievalError(EMBED_FAILED, f"The embedder '{embedder_name}' {problem}.")
    return [[float(x) for x in v] for v in vectors]


def embed_all(embedder: Embedder, texts: Sequence[str]) -> list[list[float]]:
    """Embed in batches, checking every batch."""
    out: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = list(texts[start : start + BATCH_SIZE])
        try:
            vectors = embedder.embed(batch)
        except RetrievalError:
            raise
        except Exception as exc:  # a third-party model: whatever it raises, the caller gets one clean error
            raise RetrievalError(EMBED_FAILED, f"The embedder '{embedder.name}' failed ({type(exc).__name__}).") from None
        out.extend(check_vectors(vectors, len(batch), embedder.name))
    if out and len({len(v) for v in out}) != 1:
        raise RetrievalError(EMBED_FAILED, f"The embedder '{embedder.name}' returned vectors of different lengths.")
    return out


class HashEmbedder:
    """Deterministic and offline: hashes the words (and their parts) of a text into a fixed-size vector.
    Texts that share words are close. It is a stand-in for tests, not a search engine."""

    def __init__(self, dimensions: int = 256) -> None:
        if type(dimensions) is not int or dimensions < 8:
            raise ValueError("dimensions must be a whole number of at least 8")
        self.dimensions = dimensions
        self.name = f"hash-{dimensions}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in split_words(text):
            digest = hashlib.sha1(word.lower().encode()).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[slot] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector] if norm else vector


class ChromaDefaultEmbedder:
    """Chroma's default model (all-MiniLM-L6-v2 through ONNX), run locally. The first use downloads the model
    once (about 80 MB) from the internet; after that it works offline. Code is never sent anywhere."""

    name = "chroma-default-minilm"

    def __init__(self) -> None:
        self._function: Any = None

    def _load(self) -> Any:
        if self._function is None:
            try:
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction  # lazy: chromadb is optional at import time
            except ImportError:
                raise RetrievalError(
                    EMBEDDER_UNAVAILABLE, "Semantic search needs the 'chromadb' package, which is not installed. Install it, or use another embedder."
                ) from None
            try:
                self._function = DefaultEmbeddingFunction()
            except Exception as exc:
                raise RetrievalError(EMBEDDER_UNAVAILABLE, f"The embedding model could not be loaded ({type(exc).__name__}).") from None
        return self._function

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        function = self._load()
        try:
            return [[float(x) for x in v] for v in function(list(texts))]
        except Exception as exc:
            raise RetrievalError(EMBED_FAILED, f"The embedding model failed ({type(exc).__name__}).") from None
