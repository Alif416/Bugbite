"""The result of ranking: files best first, each with the reasons that produced its score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import BAD_OUTPUT, RetrievalError

REASON_KINDS = ("traceback", "path", "test", "symbol", "words", "test_file")
SCORE_DIGITS = 3


def _bad(message: str) -> RetrievalError:
    return RetrievalError(BAD_OUTPUT, f"The ranking is not valid: {message}")


@dataclass(frozen=True)
class Reason:
    kind: str  # one of REASON_KINDS
    text: str  # readable evidence, for example "innermost frame in the repository: parse_config, line 88"
    points: float  # what it added to the score (negative for a penalty)

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "points": self.points}

    @classmethod
    def from_json(cls, data: Any) -> "Reason":
        if not isinstance(data, Mapping) or set(data) != {"kind", "text", "points"}:
            raise _bad("a reason must have exactly kind, text and points")
        if data["kind"] not in REASON_KINDS or not isinstance(data["text"], str) or type(data["points"]) not in (int, float):
            raise _bad("a reason has a wrong field type")
        return cls(data["kind"], data["text"], data["points"])


@dataclass(frozen=True)
class SymbolHit:
    name: str
    qualname: str
    line: int
    end_line: int
    why: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "qualname": self.qualname, "line": self.line, "end_line": self.end_line, "why": self.why}

    @classmethod
    def from_json(cls, data: Any) -> "SymbolHit":
        if not isinstance(data, Mapping) or set(data) != {"name", "qualname", "line", "end_line", "why"}:
            raise _bad("a symbol hit has the wrong fields")
        if not all(isinstance(data[k], str) for k in ("name", "qualname", "why")) or not all(type(data[k]) is int for k in ("line", "end_line")):
            raise _bad("a symbol hit has a wrong field type")
        return cls(data["name"], data["qualname"], data["line"], data["end_line"], data["why"])


@dataclass(frozen=True)
class Candidate:
    path: str
    score: float  # the sum of the reasons' points
    reasons: tuple[Reason, ...]
    symbols: tuple[SymbolHit, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "score": self.score, "reasons": [r.to_json() for r in self.reasons], "symbols": [s.to_json() for s in self.symbols]}

    @classmethod
    def from_json(cls, data: Any) -> "Candidate":
        if not isinstance(data, Mapping) or set(data) != {"path", "score", "reasons", "symbols"}:
            raise _bad("a candidate has the wrong fields")
        if not isinstance(data["path"], str) or type(data["score"]) not in (int, float):
            raise _bad("a candidate has a wrong field type")
        if not isinstance(data["reasons"], list) or not isinstance(data["symbols"], list):
            raise _bad("reasons and symbols must be lists")
        return cls(data["path"], data["score"], tuple(Reason.from_json(r) for r in data["reasons"]), tuple(SymbolHit.from_json(s) for s in data["symbols"]))


@dataclass(frozen=True)
class Ranking:
    candidates: tuple[Candidate, ...]  # best first; ties by path
    considered: int  # how many files the index had
    notes: tuple[str, ...] = ()  # things the reader should know ("index incomplete", "no signals found", ...)

    def to_json(self) -> dict[str, Any]:
        return {"candidates": [c.to_json() for c in self.candidates], "considered": self.considered, "notes": list(self.notes)}

    @classmethod
    def from_json(cls, data: Any) -> "Ranking":
        if not isinstance(data, Mapping) or set(data) != {"candidates", "considered", "notes"}:
            raise _bad("the ranking has the wrong fields")
        if not isinstance(data["candidates"], list) or type(data["considered"]) is not int or not isinstance(data["notes"], list):
            raise _bad("the ranking has a wrong field type")
        if not all(isinstance(n, str) for n in data["notes"]):
            raise _bad("notes must be text")
        return cls(tuple(Candidate.from_json(c) for c in data["candidates"]), data["considered"], tuple(data["notes"]))
