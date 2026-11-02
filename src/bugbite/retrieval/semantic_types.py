"""What a semantic search returns, with strict JSON round trip."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import BAD_OUTPUT, RetrievalError
from .types import KINDS, _count, _text, check_path

CHUNK_KINDS = KINDS + ("file",)  # "file" is the head of a file that has no symbols
MAX_PREVIEW_CHARS = 200
MAX_NOTES = 10


def _bad(message: str) -> RetrievalError:
    return RetrievalError(BAD_OUTPUT, f"The semantic search result is not valid: {message}")


@dataclass(frozen=True)
class SemanticHit:
    path: str
    qualname: str  # the symbol, or the file name for a "file" chunk
    kind: str
    line: int
    end_line: int
    score: float  # similarity in (0, 1]
    preview: str  # one short line: the docstring or the first line of code

    def __post_init__(self) -> None:
        if self.kind not in CHUNK_KINDS:
            raise ValueError(f"unknown chunk kind {self.kind!r}")
        if not (isinstance(self.score, float) and math.isfinite(self.score) and 0 < self.score <= 1):
            raise ValueError("score must be a number above 0 and at most 1")

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "qualname": self.qualname, "kind": self.kind, "line": self.line, "end_line": self.end_line,
                "score": self.score, "preview": self.preview}  # fmt: skip

    @classmethod
    def from_json(cls, data: Any) -> "SemanticHit":
        expected = {"path", "qualname", "kind", "line", "end_line", "score", "preview"}
        if not isinstance(data, Mapping) or set(data) != expected:
            raise _bad(f"a hit must be an object with exactly the fields {sorted(expected)}")
        score = data["score"]
        if type(score) is not float or not math.isfinite(score) or not 0 < score <= 1:
            raise _bad("score must be a number above 0 and at most 1")
        if data["kind"] not in CHUNK_KINDS:
            raise _bad("unknown chunk kind")
        line = _count(data["line"], "line", minimum=1)
        return cls(
            check_path(data["path"], "hit path"), _text(data["qualname"], "qualified name", allow_empty=False), data["kind"],
            line, _count(data["end_line"], "end_line", minimum=line), score, _text(data["preview"], "preview", limit=MAX_PREVIEW_CHARS),
        )  # fmt: skip


@dataclass(frozen=True)
class SemanticResults:
    hits: tuple[SemanticHit, ...]
    considered: int  # how many chunks were searched
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"hits": [h.to_json() for h in self.hits], "considered": self.considered, "notes": list(self.notes)}

    @classmethod
    def from_json(cls, data: Any) -> "SemanticResults":
        if not isinstance(data, Mapping) or set(data) != {"hits", "considered", "notes"}:
            raise _bad("results must be an object with hits, considered and notes")
        hits, notes = data["hits"], data["notes"]
        if not isinstance(hits, list) or len(hits) > 100:
            raise _bad("hits must be a list of at most 100")
        if not isinstance(notes, list) or len(notes) > MAX_NOTES:
            raise _bad(f"notes must be a list of at most {MAX_NOTES}")
        return cls(
            tuple(SemanticHit.from_json(h) for h in hits), _count(data["considered"], "considered"),
            tuple(_text(n, "note", limit=300, allow_empty=False) for n in notes),
        )  # fmt: skip
