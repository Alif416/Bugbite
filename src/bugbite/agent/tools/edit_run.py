"""edit_file, run_tests, run_command: change the repo, run its tests, run a command. All inside the sandbox."""

from __future__ import annotations

from typing import Any, Callable, Collection

from bugbite.adapter.types import ToolDefinition
from bugbite.sandbox import SuiteRun, run_tests
from bugbite.sandbox.setup import REPO_DIR
from bugbite.sandbox.testrun import OK

from .base import Tool, ToolOutput, error
from .paths import PathRejected, clean_relative
from .protected import hides_failures, is_test_path, protection_reason
from .resolve import PROBLEMS, resolve

MAX_TEXT_CHARS = 20_000
MAX_FILE_BYTES = 1_000_000
SHOW_LINES = 20
MAX_TARGETS = 20
MAX_FAILURES_SHOWN = 15
MAX_COLLECTION_ERRORS_SHOWN = 5
TEST_TAIL_CHARS = 1_500
MESSAGE_CHARS = 200
COMMAND_CHARS = 2_000
OUTPUT_HEAD_CHARS = 3_000
OUTPUT_TAIL_CHARS = 3_000
# built from constants only: nothing from the host environment, the repo, the issue or the model
COMMAND_ENV = {
    "PATH": "/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _problem(kind: str, path: str) -> ToolOutput:
    return error(PROBLEMS[kind].format(path=path or "."))


class EditFile(Tool):
    definition = ToolDefinition(
        "edit_file",
        "Change a file in the repository. To edit an existing file, give old_text (copied exactly from the "
        "file, including spaces and indentation, and it must occur exactly once) and new_text to replace it "
        "with. To create a new file, leave old_text out and give the whole content as new_text. You cannot "
        "change existing test files, test configuration, CI files or dependency files (new test files are fine): "
        "fix the source code instead. Example: {\"path\": \"src/app.py\", \"old_text\": \"return a - b\", \"new_text\": \"return a + b\"}",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the repository root."},
                "old_text": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS, "description": "Exact text to replace (must occur once). Omit to create a new file."},
                "new_text": {"type": "string", "maxLength": MAX_TEXT_CHARS, "description": "The replacement text, or the full content of a new file."},
            },
            "required": ["path", "new_text"],
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any, allowed_paths: Collection[str] = (), created: set[str] | None = None) -> None:
        self.sandbox = sandbox
        self.allowed = frozenset(allowed_paths)  # set by the caller; there is no way to change it from a tool call
        self.created: set[str] = created if created is not None else set()

    def _blocked(self, *paths: str, existed: bool) -> ToolOutput | None:
        for path in dict.fromkeys(paths):  # the path as asked and as resolved through any symlink
            reason = protection_reason(path, existed=existed, created_by_agent=path in self.created, allowed=self.allowed)
            if reason:
                return error(reason)
        return None

    def _run(self, arguments: dict[str, Any]) -> ToolOutput:
        try:
            rel = clean_relative(arguments["path"])
        except PathRejected as exc:
            return error(str(exc))
        new_text = arguments["new_text"]
        old_text = arguments.get("old_text")
        return self._create(rel, new_text) if old_text is None else self._replace(rel, old_text, new_text)

    def _skip_check(self, rel: str, new_text: str) -> ToolOutput | None:
        if is_test_path(rel) and hides_failures(new_text):
            return error("Tests you write must not use skip, skipif or xfail: a test that is skipped proves nothing.")
        return None

    def _replace(self, rel: str, old_text: str, new_text: str) -> ToolOutput:
        info = resolve(self.sandbox, rel)
        if info.kind == "dir":
            return error(f"{rel} is a directory, not a file.")
        if info.kind == "missing":
            return error(f"No such file: {rel}. To create a new file, leave old_text out.")
        if info.kind != "file":
            return _problem(info.kind, rel)
        if (bad := self._blocked(rel, info.rel, existed=True)):
            return bad
        if old_text == new_text:
            return error("old_text and new_text are the same, so nothing would change.")
        if info.size > MAX_FILE_BYTES:
            return error(f"{rel} is larger than {MAX_FILE_BYTES} bytes; this tool will not edit it.")
        data = self.sandbox.read_file(info.absolute, max_bytes=MAX_FILE_BYTES)
        if data is None:
            return _problem("missing", rel)
        if b"\x00" in data[:8000]:
            return error(f"{rel} looks like a binary file; this tool only edits text.")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return error(f"{rel} is not valid UTF-8 text; this tool will not edit it.")
        count = text.count(old_text)
        if count == 0:
            return error(
                f"old_text was not found in {rel}. It must match exactly, including spaces and indentation. "
                "Use read_file and copy the text from there."
            )
        if count > 1:
            return error(
                f"old_text occurs {count} times in {rel}. Include more surrounding lines so it matches exactly once."
            )
        if (bad := self._skip_check(info.rel, new_text) if info.rel in self.created else None):
            return bad
        index = text.index(old_text)
        updated = text[:index] + new_text + text[index + len(old_text) :]
        encoded = updated.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            return error(f"The edit would make {rel} larger than {MAX_FILE_BYTES} bytes.")
        self.sandbox.write_file(info.absolute, encoded)
        if info.mode != 0o644:
            self.sandbox.run(["chmod", "--", format(info.mode, "o"), info.absolute], timeout=30)
        first = updated.count("\n", 0, index) + 1
        return ToolOutput(f"Edited {rel}: replaced 1 occurrence.\n{_region(updated, first, new_text)}")

    def _create(self, rel: str, new_text: str) -> ToolOutput:
        info = resolve(self.sandbox, rel)
        if info.kind in ("outside", "git", "other"):
            return _problem(info.kind, rel)
        if info.kind in ("file", "dir"):
            return error(f"{rel} already exists. To change it, give old_text; to replace part of it, copy that part exactly.")
        target = info.rel  # where the new file will really land, after any symlinked folders
        if not target:
            return error("A file path is required.")
        if (bad := self._blocked(rel, target, existed=False)):
            return bad
        if (bad := self._skip_check(target, new_text)):
            return bad
        parent = target.rpartition("/")[0]
        missing_from = parent
        while True:  # walk up to the nearest folder that exists, and check what it really is
            above = resolve(self.sandbox, missing_from)
            if above.kind == "dir":
                break
            if above.kind != "missing":
                return _problem(above.kind, missing_from) if above.kind != "file" else error(f"{missing_from} is a file, not a folder.")
            if not missing_from:
                break
            missing_from = missing_from.rpartition("/")[0]
        if parent:
            made = self.sandbox.run(["mkdir", "-p", "--", f"{REPO_DIR}/{parent}"], timeout=30)
            if made.exit_code != 0:
                return error(f"Could not create the folder for {rel}.")
        self.sandbox.write_file(f"{REPO_DIR}/{target}", new_text)
        self.created.add(target)
        lines = new_text.count("\n") + (0 if new_text.endswith("\n") or not new_text else 1)
        return ToolOutput(f"Created {target} ({lines} lines).\n{_region(new_text, 1, new_text)}")


def _region(text: str, first_line: int, changed: str) -> str:
    """The changed lines, numbered, at most SHOW_LINES of them."""
    lines = text.split("\n")
    span = max(1, changed.count("\n") + (0 if changed.endswith("\n") or not changed else 1))
    shown = lines[first_line - 1 : first_line - 1 + min(span, SHOW_LINES)]
    rows = [f"{first_line + i:>6}| {line}" for i, line in enumerate(shown)]
    if span > SHOW_LINES:
        rows.append(f"[{span - SHOW_LINES} more changed lines not shown]")
    return "\n".join(rows) if changed else f"(text removed at line {first_line})"


class RunTests(Tool):
    definition = ToolDefinition(
        "run_tests",
        "Run the repository's tests with pytest and get a short summary: counts, the failing tests with a "
        "one-line reason each, and the end of the output if something failed. Give targets (test files or "
        "test ids such as tests/test_a.py::test_x) to run only those; leave them out to run everything. "
        "keyword selects tests by name like pytest -k. Example: {\"targets\": [\"tests/test_a.py::test_x\"]}",
        {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 300}, "maxItems": MAX_TARGETS,
                    "description": "Test files or test ids to run. Default: all tests.",
                },
                "keyword": {"type": "string", "minLength": 1, "maxLength": 200, "description": "Only run tests whose names match this expression."},
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any, runner: Callable[..., SuiteRun] = run_tests) -> None:
        self.sandbox = sandbox
        self.runner = runner

    def _run(self, arguments: dict[str, Any]) -> ToolOutput:
        keyword = arguments.get("keyword")
        if keyword is not None and keyword.lstrip().startswith("-"):
            return error("keyword must not start with '-'.")
        extra = ["-k", keyword] if keyword else []
        try:
            suite = self.runner(self.sandbox, list(arguments.get("targets", ())), extra_args=extra)
        except ValueError as exc:
            return error(f"Invalid test target: {exc}")
        return ToolOutput(summarise(suite))


def _first_line(text: str) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= MESSAGE_CHARS else line[:MESSAGE_CHARS] + " [cut]"


def summarise(suite: SuiteRun) -> str:
    counts = {name: n for name, n in suite.counts.items() if n}
    total = sum(counts.values())
    lines: list[str] = []
    if suite.status == OK:
        parts = ", ".join(f"{n} {name}" for name, n in counts.items()) or "nothing ran"
        lines.append(f"Ran {total} tests: {parts}.")
    else:
        lines.append(f"Test run status: {suite.status}. {suite.reason}".strip())
        if total:
            lines.append("Results recorded before it stopped: " + ", ".join(f"{n} {name}" for name, n in counts.items()) + ".")
    bad = [(tid, case) for tid, case in sorted(suite.tests.items()) if case.outcome in ("failed", "error")]
    for tid, case in bad[:MAX_FAILURES_SHOWN]:
        lines.append(f"{case.outcome.upper()} {tid}: {_first_line(case.message)}".rstrip(": "))
    if len(bad) > MAX_FAILURES_SHOWN:
        lines.append(f"[{len(bad) - MAX_FAILURES_SHOWN} more failing tests not shown]")
    errors = suite.collection_errors
    for item in errors[:MAX_COLLECTION_ERRORS_SHOWN]:
        lines.append(f"COLLECTION ERROR {item.id}: {_first_line(item.message)}".rstrip(": "))
    if len(errors) > MAX_COLLECTION_ERRORS_SHOWN:
        lines.append(f"[{len(errors) - MAX_COLLECTION_ERRORS_SHOWN} more collection errors not shown]")
    if bad or errors or suite.status != OK:
        tail = suite.output_tail.strip()[-TEST_TAIL_CHARS:]
        if tail:
            lines.append("End of output:\n" + tail)
    return "\n".join(lines)


class RunCommand(Tool):
    definition = ToolDefinition(
        "run_command",
        "Run a shell command in the repository directory inside the sandbox and get its exit code and output "
        "(the start and end of long output). There is no internet. The project's Python virtualenv is first "
        "on PATH. Use it for things like running a script or a single python snippet; use run_tests for tests. "
        "Example: {\"command\": \"python -c 'import app; print(app.add(1, 2))'\"}",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1, "maxLength": COMMAND_CHARS, "description": "The shell command."},
                "timeout_s": {"type": "integer", "minimum": 1, "description": "Seconds before it is stopped. Default and maximum: the sandbox limit."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )

    def __init__(self, sandbox: Any) -> None:
        self.sandbox = sandbox

    def _run(self, arguments: dict[str, Any]) -> ToolOutput:
        command = arguments["command"]
        if "\x00" in command:
            return error("The command contains a NUL character.")
        if self.sandbox.has_network:
            return error("Refusing to run: the sandbox still has network access. This is a Bugbite setup problem, not something you can fix.")
        limit = self.sandbox.config.command_timeout_s
        timeout = min(arguments.get("timeout_s", limit), limit)
        result = self.sandbox.run(command, timeout=timeout, workdir=REPO_DIR, env=COMMAND_ENV)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output and not output.endswith("\n") else "") + "[stderr]\n" + result.stderr
        head = f"timed out after {timeout}s" if result.timed_out else f"exit code {result.exit_code}"
        if not output.strip():
            return ToolOutput(f"{head}\n(no output)")
        if len(output) > OUTPUT_HEAD_CHARS + OUTPUT_TAIL_CHARS:
            left_out = len(output) - OUTPUT_HEAD_CHARS - OUTPUT_TAIL_CHARS
            output = output[:OUTPUT_HEAD_CHARS] + f"\n[... {left_out} characters left out ...]\n" + output[-OUTPUT_TAIL_CHARS:]
        elif result.truncated:
            output += "\n[the sandbox cut the output at its limit]"
        return ToolOutput(f"{head}\n{output.rstrip()}")
