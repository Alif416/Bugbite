"""The index: files and symbols, with strict validation of data that comes from the sandbox (untrusted)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import BAD_OUTPUT, RetrievalError

SCHEMA_VERSION = 1

KIND_CLASS = "class"
KIND_FUNCTION = "function"
KIND_METHOD = "method"
KINDS = (KIND_CLASS, KIND_FUNCTION, KIND_METHOD)

TRUNCATION_REASONS = ("max_files", "max_symbols", "max_depth", "output_budget")

MAX_PATH_CHARS = 1024
MAX_TEXT_CHARS = 400
MAX_DECORATORS = 10
MAX_FILES = 50_000
MAX_SYMBOLS = 200_000


def _bad(message: str) -> RetrievalError:
    return RetrievalError(BAD_OUTPUT, f"The code index is not valid: {message}")


def _text(value: Any, what: str, *, limit: int = MAX_TEXT_CHARS, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise _bad(f"{what} must be text")
    if len(value) > limit:
        raise _bad(f"{what} is longer than {limit} characters")
    if not allow_empty and not value:
        raise _bad(f"{what} must not be empty")
    return value


def _count(value: Any, what: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:  # bool is not accepted
        raise _bad(f"{what} must be a whole number of at least {minimum}")
    return value


def check_path(value: Any, what: str = "path") -> str:
    """A relative path inside the repo: no leading slash, no `..`, no backslash, no NUL."""
    path = _text(value, what, limit=MAX_PATH_CHARS, allow_empty=False)
    if path.startswith("/") or "\\" in path or "\x00" in path:
        raise _bad(f"{what} {path[:60]!r} is not a relative repository path")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _bad(f"{what} {path[:60]!r} is not a clean relative path")
    return path


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    language: str  # "python", another known name, "binary" or "other"
    lines: int | None  # None when the file was not read (too large, binary)
    parse_error: str | None = None  # why a file was not read or parsed (so a Python file has no symbols)

    @classmethod
    def from_json(cls, data: Any) -> "FileEntry":
        if not isinstance(data, Mapping):
            raise _bad("a file entry must be an object")
        expected = {"path", "size", "language", "lines", "parse_error"}
        if set(data) != expected:
            raise _bad(f"a file entry must have exactly the fields {sorted(expected)}")
        lines, error = data["lines"], data["parse_error"]
        return cls(
            check_path(data["path"], "file path"),
            _count(data["size"], "file size"),
            _text(data["language"], "language", limit=30, allow_empty=False),
            None if lines is None else _count(lines, "line count"),
            None if error is None else _text(error, "parse error"),
        )

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "language": self.language, "lines": self.lines, "parse_error": self.parse_error}


@dataclass(frozen=True)
class Symbol:
    kind: str  # class | function | method
    name: str
    qualname: str  # Class.method, Outer.Inner, func.<locals>.inner
    path: str
    line: int  # the line of `def` / `class` (decorators come earlier)
    end_line: int
    signature: str  # "(a, b=1) -> int" for functions, "(Base)" for classes, "" if none
    doc: str  # first line of the docstring
    decorators: tuple[str, ...]
    parent: str | None  # qualname of the enclosing class or function
    is_async: bool = False

    @classmethod
    def from_json(cls, data: Any) -> "Symbol":
        if not isinstance(data, Mapping):
            raise _bad("a symbol must be an object")
        expected = {"kind", "name", "qualname", "path", "line", "end_line", "signature", "doc", "decorators", "parent", "is_async"}
        if set(data) != expected:
            raise _bad(f"a symbol must have exactly the fields {sorted(expected)}")
        kind = data["kind"]
        if kind not in KINDS:
            raise _bad(f"unknown symbol kind {str(kind)[:30]!r}")
        decorators = data["decorators"]
        if not isinstance(decorators, list) or len(decorators) > MAX_DECORATORS:
            raise _bad(f"decorators must be a list of at most {MAX_DECORATORS}")
        parent = data["parent"]
        if type(data["is_async"]) is not bool:
            raise _bad("is_async must be true or false")
        line = _count(data["line"], "line", minimum=1)
        end = _count(data["end_line"], "end_line", minimum=line)
        return cls(
            kind,
            _text(data["name"], "symbol name", allow_empty=False),
            _text(data["qualname"], "qualified name", allow_empty=False),
            check_path(data["path"], "symbol path"),
            line,
            end,
            _text(data["signature"], "signature"),
            _text(data["doc"], "docstring line"),
            tuple(_text(d, "decorator") for d in decorators),
            None if parent is None else _text(parent, "parent", allow_empty=False),
            data["is_async"],
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "name": self.name, "qualname": self.qualname, "path": self.path, "line": self.line,
            "end_line": self.end_line, "signature": self.signature, "doc": self.doc, "decorators": list(self.decorators),
            "parent": self.parent, "is_async": self.is_async,
        }  # fmt: skip


@dataclass(frozen=True)
class RepoIndex:
    """What is in the repo: every file, and the symbols of the Python files. Lookups never change it."""

    files: tuple[FileEntry, ...]
    symbols: tuple[Symbol, ...]
    truncated: tuple[str, ...] = ()  # why the index may be incomplete; empty when it is complete
    schema_version: int = SCHEMA_VERSION
    _by_path: dict[str, FileEntry] = field(init=False, repr=False, compare=False)
    _by_name: dict[str, list[Symbol]] = field(init=False, repr=False, compare=False)
    _by_file: dict[str, list[Symbol]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_path = {f.path: f for f in self.files}
        by_name: dict[str, list[Symbol]] = {}
        by_file: dict[str, list[Symbol]] = {}
        for symbol in self.symbols:
            by_name.setdefault(symbol.name, []).append(symbol)
            by_file.setdefault(symbol.path, []).append(symbol)
        for name, value in (("_by_path", by_path), ("_by_name", by_name), ("_by_file", by_file)):
            object.__setattr__(self, name, value)

    # -- lookups ---------------------------------------------------------------------------------
    @property
    def complete(self) -> bool:
        return not self.truncated

    def file(self, path: str) -> FileEntry | None:
        return self._by_path.get(path)

    def find(self, name: str, kind: str | None = None) -> list[Symbol]:
        """Symbols with exactly this name (not qualified), in file and line order."""
        return [s for s in self._by_name.get(name, ()) if kind is None or s.kind == kind]

    def in_file(self, path: str) -> list[Symbol]:
        return list(self._by_file.get(path, ()))

    def by_kind(self, kind: str) -> list[Symbol]:
        if kind not in KINDS:
            raise ValueError(f"unknown symbol kind {kind!r}")
        return [s for s in self.symbols if s.kind == kind]

    def get(self, qualname: str, path: str | None = None) -> Symbol | None:
        """The first symbol with this qualified name (in the given file, if one is named)."""
        for symbol in self.symbols:
            if symbol.qualname == qualname and (path is None or symbol.path == path):
                return symbol
        return None

    def symbol_count(self, path: str) -> int:
        return len(self._by_file.get(path, ()))

    # -- JSON ------------------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "files": [f.to_json() for f in self.files],
            "symbols": [s.to_json() for s in self.symbols],
            "truncated": list(self.truncated),
        }

    @classmethod
    def from_json(cls, data: Any) -> "RepoIndex":
        """Build an index from parsed JSON, refusing anything that is not exactly what the scanner writes."""
        if not isinstance(data, Mapping):
            raise _bad("the top level must be an object")
        if data.get("schema_version") != SCHEMA_VERSION or type(data.get("schema_version")) is not int:
            raise _bad(f"schema_version must be {SCHEMA_VERSION}")
        extra = set(data) - {"schema_version", "files", "symbols", "truncated", "skipped"}
        if extra or not {"files", "symbols", "truncated"} <= set(data):
            raise _bad("unexpected or missing top-level fields")
        files, symbols, truncated = data["files"], data["symbols"], data["truncated"]
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise _bad(f"files must be a list of at most {MAX_FILES}")
        if not isinstance(symbols, list) or len(symbols) > MAX_SYMBOLS:
            raise _bad(f"symbols must be a list of at most {MAX_SYMBOLS}")
        if not isinstance(truncated, list) or any(r not in TRUNCATION_REASONS for r in truncated):
            raise _bad("truncated must be a list of known reasons")
        file_entries = tuple(FileEntry.from_json(f) for f in files)
        known = {f.path: f for f in file_entries}
        if len(known) != len(file_entries):
            raise _bad("a file is listed twice")
        parsed: list[Symbol] = []
        for item in symbols:
            symbol = Symbol.from_json(item)
            entry = known.get(symbol.path)
            if entry is None:
                raise _bad(f"symbol {symbol.qualname[:60]!r} is in a file that is not listed")
            if entry.language != "python" or entry.parse_error is not None:
                raise _bad(f"symbol {symbol.qualname[:60]!r} is in a file that has no symbols")
            if entry.lines is not None and symbol.end_line > entry.lines:
                raise _bad(f"symbol {symbol.qualname[:60]!r} ends after its file does")
            parsed.append(symbol)
        return cls(file_entries, tuple(parsed), tuple(truncated))
