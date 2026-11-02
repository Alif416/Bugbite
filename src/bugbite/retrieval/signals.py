"""The ranking signals. Each reads the issue and the index and returns `{path: [Reason, ...]}`.

All weights are constants here, in one place, with the reason for each. They were chosen by reasoning about what an
issue usually tells you, then checked against the fixture issues in the tests; they are not learned.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable, Mapping

from bugbite.agent.issue_parse import TestMention, TrackedIndex, Traceback, map_to_repo

from .ranking_types import Reason
from .types import RepoIndex, Symbol
from .words import split_words

# -- weights --------------------------------------------------------------------------------------------------------
TRACEBACK_INNERMOST = 10.0  # the frame that raised is the best single hint an issue gives
TRACEBACK_STEP = 2.0  # each frame further out is worth this much less ...
TRACEBACK_FLOOR = 3.0  # ... but never less than this: the caller is still relevant
PATH_NAMED = 8.0  # the reporter wrote the file name down
TEST_FILE_NAMED = 3.0  # a test is named, so the test file matters a little (it holds the reproduction, not the fix)
TEST_SOURCE_PAIR = 5.0  # and the code it most plausibly covers matters more than the test
SYMBOL_UNIQUE = 6.0  # a name defined once in the repo; divided by the number of places that define it
SYMBOL_QUALIFIED = 8.0  # `Class.method` is more specific than a bare name
SYMBOL_MAX_PLACES = 8  # a name defined in more places than this says nothing
SYMBOL_CAP_PER_FILE = 14.0
WORD_PATH = 1.0  # a word in the file path
WORD_SYMBOL = 0.6  # a word in the name of something the file defines
WORD_DOC = 0.3  # a word in a docstring line
WORD_CAP_PER_FILE = 5.0
MODULE_NAME_MENTIONED = 2.0  # the issue says the file's one-word name ("the scanner" for scanner.py)
MODULE_NAME_MAX_FILES = 3  # a stem shared by more files than this (utils, __init__) says nothing
WORD_BEST_COUNT = 3  # only a file's strongest matches count: ten weak common words must not beat one rare word
WORD_MAX_SHARE = 0.4  # a word found in more than this share of files carries no information
TEST_FILE_FACTOR = 0.5  # a test file the issue does not name is probably not where the fix goes
MAX_SYMBOL_HITS = 5

_TEST_NAME = re.compile(r"^(?:test_(?P<a>.+)|(?P<b>.+)_test)\.py$")


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return any(p in ("tests", "test", "testing") for p in parts[:-1]) or bool(_TEST_NAME.match(name)) or name == "conftest.py"


def _round(value: float) -> float:
    return round(value, 3)


def _tracked(index: RepoIndex) -> TrackedIndex:
    return TrackedIndex.build([f.path for f in index.files])


def traceback_signal(tracebacks: Iterable[Traceback], index: RepoIndex) -> dict[str, list[Reason]]:
    tracked = _tracked(index)
    best: dict[str, tuple[float, str]] = {}
    for tb in tracebacks:
        mapped = [(frame, map_to_repo(frame.path, tracked)) for frame in tb.frames]
        inside = [(n, frame, path) for n, (frame, path) in enumerate(mapped, 1) if path is not None]
        for rank, (n, frame, path) in enumerate(reversed(inside)):  # rank 0 is the innermost frame in the repo
            points = max(TRACEBACK_FLOOR, TRACEBACK_INNERMOST - TRACEBACK_STEP * rank)
            where = f"{frame.function}, line {frame.line}" if frame.function else f"line {frame.line}"
            text = ("innermost frame in the repository" if rank == 0 else f"traceback frame {n} of {len(tb.frames)}") + f": {where}"
            if path not in best or points > best[path][0]:
                best[path] = (points, text)
    return {path: [Reason("traceback", text, points)] for path, (points, text) in best.items()}


def path_signal(paths: Iterable[str], index: RepoIndex) -> dict[str, list[Reason]]:
    tracked = _tracked(index)
    out: dict[str, list[Reason]] = {}
    for mention in paths:
        path = map_to_repo(mention, tracked)
        if path is not None and path not in out:
            points = PATH_NAMED * TEST_FILE_FACTOR if is_test_path(path) else PATH_NAMED  # a named test is where it fails, not where it is fixed
            out[path] = [Reason("path", f"the issue names this file ({mention})", points)]
    return out


def _source_pairs(test_path: str, index: RepoIndex) -> list[str]:
    match = _TEST_NAME.match(test_path.split("/")[-1])
    if not match:
        return []
    stem = match.group("a") or match.group("b")
    pairs = [f.path for f in index.files if f.path.split("/")[-1] == stem + ".py" and not is_test_path(f.path)]
    return pairs if len(pairs) <= 3 else []  # more than three files with that name says nothing


def test_signal(mentions: Iterable[TestMention], index: RepoIndex, tracked: TrackedIndex | None = None) -> dict[str, list[Reason]]:
    tracked = tracked or _tracked(index)
    out: dict[str, list[Reason]] = defaultdict(list)
    named: dict[str, str] = {}
    for mention in mentions:
        if mention.node_id:
            path = map_to_repo(mention.node_id.split("::")[0], tracked)
            if path:
                named.setdefault(path, mention.node_id)
        elif mention.name:
            places = [s for s in index.find(mention.name) if s.kind in ("function", "method")]
            if 0 < len(places) <= 3:
                for s in places:
                    named.setdefault(s.path, mention.name)
    for path, label in named.items():
        out[path].append(Reason("test", f"the issue names the test {label}", TEST_FILE_NAMED))
        for source in _source_pairs(path, index):
            out[source].append(Reason("test", f"covered by {path} (same name), named in the issue", TEST_SOURCE_PAIR))
    return dict(out)


def _qualnames(index: RepoIndex) -> dict[str, list[Symbol]]:
    table: dict[str, list[Symbol]] = defaultdict(list)
    for s in index.symbols:
        if "." in s.qualname and "<locals>" not in s.qualname:
            table[s.qualname].append(s)
    return table


def symbol_signal(names: Iterable[str], index: RepoIndex) -> tuple[dict[str, list[Reason]], dict[str, list[Symbol]]]:
    """Reasons per file, and the symbols that were matched per file."""
    qualified = _qualnames(index)
    reasons: dict[str, list[Reason]] = defaultdict(list)
    hits: dict[str, list[Symbol]] = defaultdict(list)
    spent: dict[str, float] = defaultdict(float)
    for name in names:
        matches: list[Symbol] = []
        weight = SYMBOL_UNIQUE
        if "." in name:
            parts = name.split(".")
            for start in range(len(parts) - 1):  # the longest qualified suffix first
                matches = qualified.get(".".join(parts[start:]), [])
                if matches:
                    weight = SYMBOL_QUALIFIED
                    break
        else:
            matches = index.find(name)
        if not matches or len(matches) > SYMBOL_MAX_PLACES:
            continue
        share = weight / len(matches)
        for symbol in matches:
            room = SYMBOL_CAP_PER_FILE - spent[symbol.path]
            points = _round(min(share * (TEST_FILE_FACTOR if is_test_path(symbol.path) else 1.0), room))
            if points <= 0:
                continue
            spent[symbol.path] += points
            where = f"{symbol.qualname} (lines {symbol.line}-{symbol.end_line})"
            places = "" if len(matches) == 1 else f", one of {len(matches)} places with that name"
            reasons[symbol.path].append(Reason("symbol", f"defines {where}, named in the issue as {name}{places}", points))
            hits[symbol.path].append(symbol)
    return dict(reasons), dict(hits)


def word_signal(words: Mapping[str, str], index: RepoIndex) -> dict[str, list[Reason]]:
    if not words or not index.files:
        return {}
    wanted = set(words)
    in_path: dict[str, set[str]] = {}
    in_symbol: dict[str, set[str]] = defaultdict(set)
    in_doc: dict[str, set[str]] = defaultdict(set)
    for entry in index.files:
        found = wanted.intersection(split_words(entry.path.rsplit(".", 1)[0]))
        in_path[entry.path] = found
    for s in index.symbols:
        in_symbol[s.path].update(wanted.intersection(split_words(s.name)))
        if s.doc:
            in_doc[s.path].update(wanted.intersection(split_words(s.doc)))
    total = len(index.files)
    frequency: dict[str, int] = defaultdict(int)
    for entry in index.files:
        for word in in_path[entry.path] | in_symbol.get(entry.path, set()) | in_doc.get(entry.path, set()):
            frequency[word] += 1
    out: dict[str, list[Reason]] = {}
    for entry in index.files:
        scored: list[tuple[float, str]] = []
        for word in sorted(in_path[entry.path] | in_symbol.get(entry.path, set()) | in_doc.get(entry.path, set())):
            if frequency[word] / total > WORD_MAX_SHARE and total > 4:
                continue
            rarity = math.log(1 + total / frequency[word])
            weight = WORD_PATH if word in in_path[entry.path] else WORD_SYMBOL if word in in_symbol.get(entry.path, ()) else WORD_DOC
            scored.append((weight * rarity, word))
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            used = [word for _, word in scored[:WORD_BEST_COUNT]] + [word for _, word in scored[WORD_BEST_COUNT:]]
            points = _round(min(sum(value for value, _ in scored[:WORD_BEST_COUNT]), WORD_CAP_PER_FILE))
            shown = ", ".join(words[w] for w in used[:4]) + (f" and {len(used) - 4} more" if len(used) > 4 else "")
            out[entry.path] = [Reason("words", f"shares words with the issue in its path, names or docstrings: {shown}", points)]
    return out


def module_name_signal(words: Mapping[str, str], index: RepoIndex) -> dict[str, list[Reason]]:
    """A file whose whole one-word name (without extension) is a word of the issue, such as scanner.py and "the scanner"."""
    stems: dict[str, list[str]] = defaultdict(list)
    for entry in index.files:
        parts = split_words(entry.path.split("/")[-1].rsplit(".", 1)[0])
        if len(parts) == 1 and parts[0] in words:
            stems[parts[0]].append(entry.path)
    out: dict[str, list[Reason]] = {}
    for word, found in stems.items():
        if len(found) <= MODULE_NAME_MAX_FILES:
            for path in found:
                out[path] = [Reason("words", f"the issue mentions the module name '{words[word]}'", MODULE_NAME_MENTIONED)]
    return out
