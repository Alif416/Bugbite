"""Rank the files of a repository for an issue, with the reasons (README FR3.3, FR3.4)."""

from __future__ import annotations

from collections import defaultdict

from bugbite.agent.issue_parse import MAX_TEXT_CHARS, TrackedIndex, find_path_mentions, find_test_mentions, parse_tracebacks

from . import signals
from .ranking_types import SCORE_DIGITS, Candidate, Ranking, Reason, SymbolHit
from .types import RepoIndex, Symbol
from .words import identifiers, issue_words

MIN_SCORE = 1.0  # below this a file has only faint word overlap, which is noise on its own
DEFAULT_MAX_RESULTS = 10
NAMED_KINDS = ("traceback", "path", "test")  # signals that mean "the issue points at this file"


def _enclosing(index: RepoIndex, path: str, line: int) -> Symbol | None:
    best = None
    for s in index.in_file(path):
        if s.line <= line <= s.end_line and (best is None or s.end_line - s.line < best.end_line - best.line):
            best = s
    return best


def rank_files(issue_text: str, index: RepoIndex, *, max_results: int = DEFAULT_MAX_RESULTS) -> Ranking:
    """The files most likely to matter for this issue, best first, each with named reasons. Pure and deterministic."""
    if type(max_results) is not int or max_results < 1:
        raise ValueError("max_results must be a whole number of at least 1")
    if not isinstance(issue_text, str):
        raise TypeError("issue_text must be text")
    notes: list[str] = []
    if len(issue_text) > MAX_TEXT_CHARS:
        issue_text = issue_text[:MAX_TEXT_CHARS]
        notes.append(f"the issue text was cut to its first {MAX_TEXT_CHARS} characters")
    if index.truncated:
        notes.append(f"the index is incomplete ({', '.join(index.truncated)}), so some files could not be ranked")

    tracebacks = parse_tracebacks(issue_text)
    reasons: dict[str, list[Reason]] = defaultdict(list)
    hits: dict[str, list[tuple[Symbol, str]]] = defaultdict(list)

    def merge(found: dict[str, list[Reason]]) -> None:
        for path, items in found.items():
            reasons[path].extend(items)

    tb = signals.traceback_signal(tracebacks, index)
    merge(tb)
    for path, items in tb.items():  # the function in the frame is a hit too
        frame_line = _frame_line(tracebacks, path, index)
        symbol = _enclosing(index, path, frame_line) if frame_line else None
        if symbol is not None:
            hits[path].append((symbol, "contains the failing line" if items[0].text.startswith("innermost") else "is on the call path"))
    merge(signals.path_signal(find_path_mentions(issue_text), index))
    merge(signals.test_signal(find_test_mentions(issue_text), index))
    by_symbol, matched = signals.symbol_signal(identifiers(issue_text), index)
    merge(by_symbol)
    for path, symbols in matched.items():
        hits[path].extend((s, "named in the issue") for s in symbols)
    words = issue_words(issue_text)
    merge(signals.word_signal(words, index))
    merge(signals.module_name_signal(words, index))

    candidates: list[Candidate] = []
    for path, items in reasons.items():
        items = list(items)
        if signals.is_test_path(path) and not any(r.kind in NAMED_KINDS for r in items):
            total = sum(r.points for r in items)
            items.append(Reason("test_file", "a test file the issue does not name", signals._round(-total * (1 - signals.TEST_FILE_FACTOR))))
        score = round(sum(r.points for r in items), SCORE_DIGITS)
        if score < MIN_SCORE:
            continue
        seen: set[tuple[str, int]] = set()
        symbol_hits: list[SymbolHit] = []
        for symbol, why in hits.get(path, ()):
            key = (symbol.qualname, symbol.line)
            if key not in seen and len(symbol_hits) < signals.MAX_SYMBOL_HITS:
                seen.add(key)
                symbol_hits.append(SymbolHit(symbol.name, symbol.qualname, symbol.line, symbol.end_line, why))
        symbol_hits.sort(key=lambda h: (h.line, h.qualname))
        candidates.append(Candidate(path, score, tuple(items), tuple(symbol_hits)))
    candidates.sort(key=lambda c: (-c.score, c.path))
    if not candidates:
        notes.append("no file could be linked to the issue: it names no known path, test, symbol or distinctive word")
    return Ranking(tuple(candidates[:max_results]), len(index.files), tuple(notes))


def _frame_line(tracebacks, path: str, index: RepoIndex) -> int | None:
    """The line of the innermost frame that maps to `path`."""
    tracked = TrackedIndex.build([f.path for f in index.files])
    from bugbite.agent.issue_parse import map_to_repo

    for tb in tracebacks:
        for frame in reversed(tb.frames):
            if map_to_repo(frame.path, tracked) == path:
                return frame.line
    return None
