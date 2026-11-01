"""read_file, list_directory, search_code: look at the repository, change nothing."""

from __future__ import annotations

from typing import Any

from bugbite.adapter.types import ToolDefinition

from .base import Tool, ToolOutput, error
from .paths import PathRejected, absolute, clean_relative, display
from .resolve import PROBLEMS, TIMEOUT_S, resolve

MAX_READ_LINES = 200
MAX_READ_CHARS = 20_000
MAX_READ_FILE_BYTES = 1_000_000
MAX_LIST_ENTRIES = 200
MAX_MATCHES = 50
MAX_MATCH_CHARS = 200
MAX_PATTERN_CHARS = 300
SKIPPED_DIRS = (".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache")


def _problem(kind: str, path: str) -> ToolOutput:
    return error(PROBLEMS[kind].format(path=path or "."))


def _safe(path: object, *, allow_root: bool = False):
    try:
        return clean_relative(path, allow_root=allow_root), None
    except PathRejected as exc:
        return None, error(str(exc))


class ReadFile(Tool):
    definition = ToolDefinition(
        "read_file",
        "Read a text file from the repository. Returns numbered lines. Shows at most 200 lines or "
        "20000 characters per call; if the file is longer the output says which start_line to use next. "
        "Example: {\"path\": \"src/app.py\", \"start_line\": 1, \"end_line\": 80}",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the repository root."},
                "start_line": {"type": "integer", "minimum": 1, "description": "First line to show (1-based). Default 1."},
                "end_line": {"type": "integer", "minimum": 1, "description": "Last line to show (inclusive)."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any) -> None:
        self.sandbox = sandbox

    def _run(self, arguments: dict[str, Any], time_limit_s: float | None = None) -> ToolOutput:
        rel, bad = _safe(arguments["path"])
        if bad:
            return bad
        start = arguments.get("start_line", 1)
        end = arguments.get("end_line")
        if end is not None and end < start:
            return error(f"end_line ({end}) is before start_line ({start}).")
        info = resolve(self.sandbox, rel)
        if info.kind == "dir":
            return error(f"{rel} is a directory; use list_directory.")
        if info.kind != "file":
            return _problem(info.kind, rel)
        if info.size > MAX_READ_FILE_BYTES:
            return error(f"{rel} is {info.size} bytes, too large to read whole. Use search_code to find the part you need.")
        data = self.sandbox.read_file(info.absolute, max_bytes=MAX_READ_FILE_BYTES)
        if data is None:
            return _problem("missing", rel)
        if b"\x00" in data[:8000]:
            return error(f"{rel} looks like a binary file.")
        lines = data.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        if total == 0:
            return ToolOutput(f"{rel} is empty.")
        if start > total:
            return error(f"start_line {start} is past the end of {rel}, which has {total} lines.")
        last = min(total, end if end is not None else total, start + MAX_READ_LINES - 1)
        shown: list[str] = []
        used = 0
        for number in range(start, last + 1):
            row = f"{number:>6}| {lines[number - 1]}"
            if used + len(row) + 1 > MAX_READ_CHARS:
                if not shown:  # one enormous line: show the start of it rather than nothing
                    shown.append(row[:MAX_READ_CHARS] + " [line cut]")
                    last = number
                else:
                    last = number - 1
                break
            shown.append(row)
            used += len(row) + 1
        text = "\n".join(shown)
        wanted_end = end if end is not None else total
        if last < min(wanted_end, total):
            text += f"\n[truncated: showing lines {start}-{last} of {total}; call again with start_line={last + 1}]"
        return ToolOutput(text)


class ListDirectory(Tool):
    definition = ToolDefinition(
        "list_directory",
        "List the files and folders directly inside a directory of the repository (one level). Folders "
        "come first and end with '/'. Shows at most 200 entries. Example: {\"path\": \"src\"}",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory relative to the repository root. Default: the root."}},
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any) -> None:
        self.sandbox = sandbox

    def _run(self, arguments: dict[str, Any], time_limit_s: float | None = None) -> ToolOutput:
        rel, bad = _safe(arguments.get("path", ""), allow_root=True)
        if bad:
            return bad
        info = resolve(self.sandbox, rel, "list")
        if info.kind == "file":
            return error(f"{rel} is a file; use read_file.")
        if info.kind != "dir":
            return _problem(info.kind, rel)
        entries = sorted(info.entries, key=lambda e: (e[1] != "d", e[0].lower(), e[0]))
        total = len(entries)
        rows = [f"{name}/" if kind == "d" else f"{name}@" if kind == "l" else name for name, kind in entries[:MAX_LIST_ENTRIES]]
        if not rows:
            return ToolOutput(f"{rel or '.'} is empty.")
        text = "\n".join(rows)
        if total > MAX_LIST_ENTRIES:
            text += f"\n[{total - MAX_LIST_ENTRIES} more entries not shown; list a subdirectory]"
        return ToolOutput(text)


class SearchCode(Tool):
    definition = ToolDefinition(
        "search_code",
        "Search the repository's text files for a string and list matching lines as path:line:text. "
        "Plain text by default; set regex to true for a regular expression. Shows at most 50 matches. "
        "Example: {\"pattern\": \"def parse\", \"path\": \"src\", \"glob\": \"*.py\"}",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1, "description": "Text (or regex) to look for."},
                "path": {"type": "string", "description": "Directory or file to search, relative to the root. Default: everything."},
                "glob": {"type": "string", "description": "Only search files whose name matches, e.g. *.py (no slashes)."},
                "regex": {"type": "boolean", "description": "Treat pattern as a regular expression. Default false."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any) -> None:
        self.sandbox = sandbox

    def _run(self, arguments: dict[str, Any], time_limit_s: float | None = None) -> ToolOutput:
        pattern = arguments["pattern"]
        if len(pattern) > MAX_PATTERN_CHARS or "\n" in pattern or "\x00" in pattern:
            return error(f"The pattern must be one line of at most {MAX_PATTERN_CHARS} characters.")
        glob = arguments.get("glob")
        if glob is not None and (not glob or "/" in glob or "\\" in glob or any(ord(c) < 32 for c in glob) or glob.startswith("-")):
            return error("glob must be a file-name pattern such as *.py, without slashes.")
        rel, bad = _safe(arguments.get("path", ""), allow_root=True)
        if bad:
            return bad
        info = resolve(self.sandbox, rel)
        if info.kind not in ("file", "dir"):
            return _problem(info.kind, rel)
        command = ["grep", "-rnIH", "-E" if arguments.get("regex", False) else "-F"]
        command += [f"--exclude-dir={name}" for name in SKIPPED_DIRS]
        if glob:
            command.append(f"--include={glob}")
        command += ["--", pattern, info.absolute]
        result = self.sandbox.run(command, timeout=TIMEOUT_S)
        if result.timed_out:
            return error("The search took too long. Search a smaller directory or use a more specific pattern.")
        if result.exit_code == 1 and not result.stdout.strip():
            return ToolOutput("No matches.")
        if result.exit_code not in (0, 1) and not result.stdout.strip():
            detail = result.stderr.strip().splitlines()[-1][:200] if result.stderr.strip() else "unknown error"
            return error(f"The search failed: {detail}")
        lines = [display(line) for line in result.stdout.splitlines() if line]
        shown = [line if len(line) <= MAX_MATCH_CHARS else line[:MAX_MATCH_CHARS] + " [cut]" for line in lines[:MAX_MATCHES]]
        text = "\n".join(shown)
        if len(lines) > MAX_MATCHES or result.truncated:
            more = "more than " + str(MAX_MATCHES) if result.truncated else str(len(lines))
            text += f"\n[showing the first {MAX_MATCHES} of {more} matches; narrow the search with path or glob]"
        return ToolOutput(text)
