"""Cutting a repository into searchable chunks: one per symbol, plus the head of files that have none.

Source text is read inside the sandbox by a small stdlib snippet (many chunks per call, bounded output),
because the sandbox is where the repository lives. File contents are untrusted data and are only ever embedded.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from bugbite.sandbox.setup import REPO_DIR

from .errors import BAD_LIMITS, BAD_OUTPUT, OUTPUT_TOO_LARGE, READ_FAILED, RetrievalError
from .signals import is_test_path
from .types import RepoIndex

READER_SOURCE = r'''
import json, os, sys
root = os.path.realpath(sys.argv[1])
out = []
for path, start, end, limit in json.loads(sys.argv[2]):
    text = None
    try:
        real = os.path.realpath(os.path.join(root, path))
        if (real == root or real.startswith(root + os.sep)) and os.path.isfile(real):
            lines = []
            with open(real, "r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if number < start:
                        continue
                    if number > end:
                        break
                    lines.append(line)
                    if sum(len(x) for x in lines) > limit:
                        break
            text = "".join(lines)[:limit]
    except Exception:
        text = None
    out.append(text)
print(json.dumps(out))
'''

MAX_BATCH_CHARS = 100_000  # JSON escaping can multiply size by 6; the sandbox output cap is 1 MiB


@dataclass(frozen=True)
class ChunkLimits:
    max_chunks: int = 3_000
    max_chunk_chars: int = 1_500
    function_lines: int = 40  # source lines taken for a function or method
    class_lines: int = 12  # a class is its header and docstring; its methods are chunks of their own
    head_lines: int = 30  # for files with no symbols
    max_query_chars: int = 2_000

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise RetrievalError(BAD_LIMITS, f"{name} must be a whole number greater than zero")


@dataclass(frozen=True)
class Chunk:
    path: str
    qualname: str
    kind: str  # class | function | method | file
    line: int
    end_line: int
    head: str  # "method Cache.get(self, key)"
    doc: str
    source: str = ""

    @property
    def text(self) -> str:
        """What gets embedded: the name and signature, the docstring, then the code."""
        return "\n".join(part for part in (f"{self.path} {self.head}", self.doc, self.source) if part)

    @property
    def preview(self) -> str:
        line = self.doc or next((l.strip() for l in self.source.splitlines() if l.strip()), "")
        return line[:197] + "..." if len(line) > 200 else line


def plan_chunks(index: RepoIndex, limits: ChunkLimits) -> tuple[list[Chunk], list[str]]:
    """The chunks (without source text yet) and notes about what was left out. Source files come before test files."""
    candidates: list[Chunk] = []
    for symbol in index.symbols:
        entry = index.file(symbol.path)
        if "<locals>" in symbol.qualname or entry is None or entry.language == "binary":
            continue
        span = limits.class_lines if symbol.kind == "class" else limits.function_lines
        candidates.append(Chunk(symbol.path, symbol.qualname, symbol.kind, symbol.line, min(symbol.end_line, symbol.line + span - 1),
                                f"{symbol.kind} {symbol.qualname}{symbol.signature}", symbol.doc))  # fmt: skip
    for entry in index.files:
        if entry.language != "binary" and entry.lines and entry.parse_error is None and index.symbol_count(entry.path) == 0:
            candidates.append(Chunk(entry.path, entry.path.rsplit("/", 1)[-1], "file", 1, min(entry.lines, limits.head_lines), "file", ""))
    candidates.sort(key=lambda c: (is_test_path(c.path), c.path, c.line))
    notes = []
    if len(candidates) > limits.max_chunks:
        notes.append(f"Only {limits.max_chunks} of {len(candidates)} chunks were searched (test files last); raise max_chunks to search more.")
        candidates = candidates[: limits.max_chunks]
    if not index.complete:
        notes.append("The code index was incomplete (" + ", ".join(index.truncated) + "), so some code is not searched.")
    return candidates, notes


def read_sources(sandbox: Any, chunks: Sequence[Chunk], limits: ChunkLimits, *, root: str = REPO_DIR, timeout: float | None = None) -> list[Chunk]:
    """Fill in each chunk's source text. A chunk whose file cannot be read keeps only its name and docstring."""
    kwargs = {} if timeout is None else {"timeout": timeout}
    result: list[Chunk] = []
    batch: list[Chunk] = []
    used = 0

    def flush() -> None:
        nonlocal batch, used
        if not batch:
            return
        requests = [[c.path, c.line, c.end_line, limits.max_chunk_chars] for c in batch]
        done = sandbox.run(["python", "-c", READER_SOURCE, root, json.dumps(requests)], **kwargs)
        if done.timed_out:
            raise RetrievalError(READ_FAILED, "Reading the source files took too long and was stopped.")
        if done.truncated:
            raise RetrievalError(OUTPUT_TOO_LARGE, "The source text was larger than the sandbox allows; lower max_chunk_chars.")
        if done.exit_code != 0:
            raise RetrievalError(READ_FAILED, f"Reading the source files failed (exit code {done.exit_code}).")
        try:
            texts = json.loads(done.stdout)
        except (ValueError, RecursionError):
            raise RetrievalError(BAD_OUTPUT, "The source reader's output was not valid JSON.") from None
        if not isinstance(texts, list) or len(texts) != len(batch) or not all(t is None or isinstance(t, str) for t in texts):
            raise RetrievalError(BAD_OUTPUT, "The source reader's output did not match the request.")
        for chunk, text in zip(batch, texts):
            result.append(Chunk(**{**chunk.__dict__, "source": (text or "")[: limits.max_chunk_chars]}))
        batch, used = [], 0

    for chunk in chunks:
        if batch and used + limits.max_chunk_chars > MAX_BATCH_CHARS:
            flush()
        batch.append(chunk)
        used += limits.max_chunk_chars
    flush()
    return result
