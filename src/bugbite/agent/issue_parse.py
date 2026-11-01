"""Read tracebacks, file paths and test names out of issue text (README FR5.7).

Everything here is a pure function over untrusted text. What it returns are claims, not facts: nothing is
used until the caller has matched it against the repository. Work is bounded and linear in the text size.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TEXT_CHARS = 30_000
MAX_TRACEBACKS = 5
MAX_FRAMES = 40
MAX_PATHS = 30
MAX_NAMES = 5
MAX_EXCEPTION_CHARS = 300

_HEADER = re.compile(r"Traceback \(most recent call last\):")
_FRAME = re.compile(r'File "(?P<path>[^"\n]{1,400})", line (?P<line>\d{1,7})(?:, in (?P<func>[^\n]{1,200}))?$')
_PYTEST_FRAME = re.compile(r"(?P<path>(?:[\w.\-]+/)*[\w.\-]+\.py):(?P<line>\d{1,7}): (?P<rest>.{0,200})$")
_CARET = re.compile(r"[\s^~]+$")
_PATH = re.compile(r"(?<![\w./\\\-])((?:[\w.\-]+[/\\])*[\w.\-]+\.py)(?![\w]|\.\w)")
_NODE = re.compile(
    r"(?<![\w./\\\-])((?:[\w.\-]+/)*[\w.\-]+\.py)((?:::[A-Za-z_]\w*)+)(\[[A-Za-z0-9_.\-,:=/\[\]]{0,100}\])?"
)
_BARE_TEST = re.compile(r"(?<![\w./\\:\-])(test_[A-Za-z0-9_]{1,80})(?![\w]|\.py|::)")
SAFE_NODE_ID = re.compile(r"[A-Za-z0-9_./\-\[\],:=]{1,400}")


@dataclass(frozen=True)
class Frame:
    path: str
    line: int
    function: str | None = None


@dataclass(frozen=True)
class Traceback:
    frames: tuple[Frame, ...]
    exception: str | None = None


@dataclass(frozen=True)
class TestMention:
    __test__ = False  # not a pytest class

    node_id: str | None = None  # a full pytest id such as tests/test_a.py::TestX::test_y
    name: str | None = None  # a bare function name such as test_y


_QUOTE_MARKS = re.compile(r"^\s*(?:>\s?)+")


def _unquote(line: str) -> str:
    """The line without leading quote markers (`>`), keeping the indentation after them."""
    return _QUOTE_MARKS.sub("", line)


def _clean(line: str) -> str:
    return _unquote(line).strip()


def _indent(line: str) -> int:
    expanded = _unquote(line).expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def parse_tracebacks(text: str) -> list[Traceback]:
    lines = text[:MAX_TEXT_CHARS].splitlines()
    found: list[Traceback] = []
    index = 0
    while index < len(lines) and len(found) < MAX_TRACEBACKS:
        if not _HEADER.fullmatch(_clean(lines[index]).strip()):
            index += 1
            continue
        index += 1
        frames: list[Frame] = []
        exception: str | None = None
        frame_indent = None
        while index < len(lines):
            raw = lines[index]
            cleaned = _clean(raw).strip()
            if not cleaned or cleaned.startswith("```"):
                break
            match = _FRAME.fullmatch(cleaned)
            if match:
                frames.append(Frame(match["path"], int(match["line"]), (match["func"] or "").strip() or None))
                frame_indent = _indent(raw)
                index += 1
                continue
            if frames and frame_indent is not None and (_indent(raw) > frame_indent or _CARET.fullmatch(cleaned)):
                index += 1  # the source line or the caret line under a frame
                continue
            if cleaned.startswith("[Previous line repeated"):
                index += 1
                continue
            if frames and _HEADER.fullmatch(cleaned) is None and re.match(r"[A-Za-z_]", cleaned):
                exception = cleaned[:MAX_EXCEPTION_CHARS]
                index += 1
            break
        if frames:
            found.append(Traceback(tuple(frames[-MAX_FRAMES:]), exception))
    if len(found) < MAX_TRACEBACKS:
        pytest_frames: list[Frame] = []
        reason: str | None = None
        for raw in lines:
            match = _PYTEST_FRAME.fullmatch(_clean(raw).strip())
            if match:
                rest = match["rest"].strip()
                function = rest[3:].strip() if rest.startswith("in ") else None
                if function is None and rest and reason is None:
                    reason = rest[:MAX_EXCEPTION_CHARS]
                pytest_frames.append(Frame(match["path"], int(match["line"]), function))
                if len(pytest_frames) >= MAX_FRAMES:
                    break
        if pytest_frames:
            found.append(Traceback(tuple(pytest_frames), reason))
    return found


def find_path_mentions(text: str) -> list[str]:
    """`.py` paths in the text (forward slashes, no line numbers), in order, without repeats."""
    seen: dict[str, None] = {}
    for match in _PATH.finditer(text[:MAX_TEXT_CHARS]):
        seen.setdefault(match.group(1).replace("\\", "/"), None)
        if len(seen) >= MAX_PATHS:
            break
    return list(seen)


def find_test_mentions(text: str) -> list[TestMention]:
    """Pytest ids (also from `FAILED ...` lines) and bare `test_...` names, in order, without repeats."""
    body = text[:MAX_TEXT_CHARS]
    ids: dict[str, None] = {}
    for match in _NODE.finditer(body):
        node_id = match.group(1) + match.group(2) + (match.group(3) or "")
        if SAFE_NODE_ID.fullmatch(node_id) and not node_id.startswith("-"):
            ids.setdefault(node_id, None)
    names: dict[str, None] = {}
    without_ids = _NODE.sub(" ", body)
    for match in _BARE_TEST.finditer(without_ids):
        names.setdefault(match.group(1), None)
        if len(names) >= MAX_NAMES:
            break
    return [TestMention(node_id=i) for i in ids] + [TestMention(name=n) for n in names]


# -- mapping to the repository -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackedIndex:
    files: frozenset[str]
    tails: dict[str, tuple[str, ...]]

    @classmethod
    def build(cls, tracked: list[str] | tuple[str, ...] | frozenset[str]) -> "TrackedIndex":
        tails: dict[str, list[str]] = {}
        for path in tracked:
            parts = path.split("/")
            for start in range(len(parts)):
                tails.setdefault("/".join(parts[start:]), []).append(path)
        return cls(frozenset(tracked), {tail: tuple(paths) for tail, paths in tails.items()})


_NOT_OURS = ("site-packages", "dist-packages")
_STDLIB = re.compile(r"(^|/)lib/python3(\.\d+)?/")


def map_to_repo(path: str, index: TrackedIndex) -> str | None:
    """The tracked file this path from an issue most likely means, or None when unknown or ambiguous."""
    if not isinstance(path, str) or "\x00" in path:
        return None
    text = path.replace("\\", "/")
    if len(text) > 400 or any(part in text.split("/") for part in _NOT_OURS) or _STDLIB.search(text):
        return None
    parts = [p for p in re.sub(r"^[A-Za-z]:", "", text).split("/") if p not in ("", ".")]
    if not parts or ".." in parts or ".git" in parts:
        return None
    for start in range(len(parts)):  # the longest tail first
        tail = "/".join(parts[start:])
        matches = index.tails.get(tail, ())
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None  # a shorter tail could only be more ambiguous
    return None
