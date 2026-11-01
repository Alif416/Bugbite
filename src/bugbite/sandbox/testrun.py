"""Run a repo's pytest suite in the sandbox and return a structured result.

Per-test outcomes come from a small plugin (see plugin/bugbite_report.py) that
is copied into the container for every run, outside the repo. The repo's own
pytest configuration is respected.

Results are only as trustworthy as the code running inside pytest: code that
forges the report is not defended against here. The verifier (P33) re-runs in a
clean container for that.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from bugbite.errors import NO_TESTS, InputError
from bugbite.sandbox.container import Sandbox

PLUGIN_NAME = "bugbite_report"
PLUGIN_SOURCE = Path(__file__).with_name("plugin") / f"{PLUGIN_NAME}.py"
PLUGIN_DIR = "/workspace/.bugbite"
REPORT_PATH = f"{PLUGIN_DIR}/report.jsonl"
REPO_DIR = "/workspace/repo"
PYTHON = "/workspace/.venv/bin/python"
OUTPUT_TAIL_CHARS = 20_000

OUTCOMES = frozenset({"passed", "failed", "error", "skipped", "xfailed", "xpassed"})

# run statuses
OK = "ok"
NO_TESTS_STATUS = "no_tests"
COLLECTION_ERROR = "collection_error"
TIMEOUT = "timeout"
CRASHED = "crashed"


# -- results -----------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    outcome: str
    duration_s: float
    message: str


@dataclass(frozen=True)
class CollectionError:
    id: str
    message: str


@dataclass(frozen=True)
class ParsedReport:
    tests: dict[str, CaseResult]
    collected: int | None
    collected_ids: tuple[str, ...]
    collection_errors: tuple[CollectionError, ...]
    exit_status: int | None
    malformed_lines: int


@dataclass(frozen=True)
class SuiteRun:
    status: str
    reason: str
    exit_code: int
    tests: dict[str, CaseResult]
    collected: int | None
    collected_ids: tuple[str, ...]
    collection_errors: tuple[CollectionError, ...]
    duration_s: float
    output_tail: str
    output_truncated: bool
    malformed_lines: int = 0
    report_missing: bool = False

    @property
    def counts(self) -> dict[str, int]:
        counter = Counter(case.outcome for case in self.tests.values())
        return {outcome: counter.get(outcome, 0) for outcome in sorted(OUTCOMES)}

    def ids_with(self, outcome: str) -> list[str]:
        return sorted(test_id for test_id, case in self.tests.items() if case.outcome == outcome)


# -- parsing and classification (pure) -------------------------------------------


def parse_report(text: str) -> ParsedReport:
    tests: dict[str, CaseResult] = {}
    collected: int | None = None
    collected_ids: tuple[str, ...] = ()
    errors: dict[tuple[str, str], CollectionError] = {}
    exit_status: int | None = None
    malformed = 0

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        kind = record.get("t") if isinstance(record, dict) else None
        if kind == "test":
            outcome, test_id = record.get("outcome"), record.get("id")
            if outcome not in OUTCOMES or not isinstance(test_id, str):
                malformed += 1
                continue
            duration = record.get("duration")
            tests[test_id] = CaseResult(
                outcome=outcome,
                duration_s=float(duration) if isinstance(duration, (int, float)) else 0.0,
                message=str(record.get("message") or ""),
            )
        elif kind == "collected":
            count = record.get("count")
            if not isinstance(count, int):
                malformed += 1
                continue
            ids = record.get("ids")
            if collected is None or count >= collected:
                collected = count
                if isinstance(ids, list):
                    collected_ids = tuple(str(i) for i in ids)
        elif kind == "collect_error":
            key = (str(record.get("id", "")), str(record.get("message", "")))
            errors[key] = CollectionError(id=key[0], message=key[1])
        elif kind == "session":
            status = record.get("exitstatus")
            if not isinstance(status, int):
                malformed += 1
            elif record.get("worker") is None:  # the xdist controller (or a plain run)
                exit_status = status
        else:
            malformed += 1

    return ParsedReport(
        tests=tests,
        collected=collected,
        collected_ids=collected_ids,
        collection_errors=tuple(errors.values()),
        exit_status=exit_status,
        malformed_lines=malformed,
    )


def _last_line(text: str, limit: int = 200) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()[:limit]
    return ""


def _error_line(text: str, limit: int = 200) -> str:
    """The most informative line of pytest's output: the last one that looks like "error: ..."."""
    for line in reversed(text.splitlines()):
        if "error:" in line.lower() and line.strip():
            return line.strip()[:limit]
    return _last_line(text, limit)


def classify(exit_code: int, timed_out: bool, report: ParsedReport | None, output_tail: str) -> tuple[str, str]:
    """Overall status and a human-readable reason for one pytest run."""
    if timed_out:
        return TIMEOUT, "The run hit the time limit and was stopped; results for tests that finished were kept."
    if report is not None and report.collection_errors:
        first = report.collection_errors[0]
        count = len(report.collection_errors)
        return COLLECTION_ERROR, f"{count} collection error(s); first: {first.id}: {first.message}".strip()
    if exit_code == 4:
        if PLUGIN_NAME in output_tail:
            return CRASHED, "The Bugbite report plugin failed to load; no results were recorded."
        return COLLECTION_ERROR, f"pytest could not start (usage error, exit 4): {_error_line(output_tail)}"
    if exit_code == 5:
        return NO_TESTS_STATUS, "pytest collected no tests."
    if exit_code in (0, 1):
        if report is not None and report.exit_status is not None:
            return OK, ""
        return CRASHED, "pytest finished but no report was recorded."
    if exit_code == 3:
        return CRASHED, f"pytest hit an internal error (exit 3): {_error_line(output_tail)}"
    if exit_code == 2:
        return CRASHED, f"pytest was interrupted (exit 2): {_error_line(output_tail)}"
    return CRASHED, f"pytest ended with an unexpected exit code {exit_code}: {_error_line(output_tail)}"


def _validate_targets(targets: Iterable[str]) -> list[str]:
    checked: list[str] = []
    for target in targets:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("test target must be a non-empty string")
        if target.lstrip().startswith("-"):
            raise ValueError(f"test target must not look like an option: {target!r}")
        if any(ord(ch) < 32 or ch == "\x7f" for ch in target):
            raise ValueError("test target contains control characters")
        checked.append(target)
    return checked


def build_pytest_command(
    targets: Sequence[str] = (),
    extra_args: Sequence[str] = (),
    *,
    collect_only: bool = False,
) -> list[str]:
    """The pytest command line. `extra_args` is for trusted Bugbite code only."""
    checked = _validate_targets(targets)
    for arg in extra_args:
        if not isinstance(arg, str) or any(ord(ch) < 32 for ch in arg):
            raise ValueError(f"invalid extra pytest argument: {arg!r}")
    command = [
        PYTHON, "-m", "pytest",
        "-p", PLUGIN_NAME,
        "-p", "no:cacheprovider",
        "--tb=short",
        "--color=no",
    ]  # fmt: skip
    if collect_only:
        command += ["--collect-only", "-q"]
    command += list(extra_args)
    if checked:
        command += ["--", *checked]
    return command


# -- running ---------------------------------------------------------------


def _install_plugin(sandbox: Sandbox) -> None:
    setup = sandbox.run(["mkdir", "-p", PLUGIN_DIR], timeout=60)
    if setup.exit_code != 0:
        raise RuntimeError(f"could not create {PLUGIN_DIR}: {setup.stderr.strip()}")
    sandbox.write_file(f"{PLUGIN_DIR}/{PLUGIN_NAME}.py", PLUGIN_SOURCE.read_text(encoding="utf-8"))
    sandbox.run(["rm", "-f", REPORT_PATH], timeout=60)  # never reuse an old report


def _run(
    sandbox: Sandbox,
    targets: Sequence[str],
    extra_args: Sequence[str],
    timeout: float | None,
    *,
    collect_only: bool,
) -> SuiteRun:
    command = build_pytest_command(targets, extra_args, collect_only=collect_only)
    _install_plugin(sandbox)
    cfg = sandbox.config
    limit = timeout if timeout is not None else (cfg.command_timeout_s if collect_only else cfg.test_timeout_s)
    env = {"PYTHONPATH": PLUGIN_DIR, "BUGBITE_REPORT_FILE": REPORT_PATH, "PYTHONDONTWRITEBYTECODE": "1"}
    if collect_only:
        env["BUGBITE_LIST_IDS"] = "1"

    result = sandbox.run(command, timeout=limit, workdir=REPO_DIR, env=env)
    raw = sandbox.read_file(REPORT_PATH)
    report = parse_report(raw.decode("utf-8", errors="replace")) if raw is not None else None
    tail = (result.stdout + result.stderr).strip()[-OUTPUT_TAIL_CHARS:]
    status, reason = classify(result.exit_code, result.timed_out, report, tail)
    empty = ParsedReport({}, None, (), (), None, 0)
    shown = report or empty
    return SuiteRun(
        status=status,
        reason=reason,
        exit_code=result.exit_code,
        tests=shown.tests,
        collected=shown.collected,
        collected_ids=shown.collected_ids,
        collection_errors=shown.collection_errors,
        duration_s=result.duration_s,
        output_tail=tail,
        output_truncated=result.truncated,
        malformed_lines=shown.malformed_lines,
        report_missing=report is None,
    )


def run_tests(
    sandbox: Sandbox,
    targets: Sequence[str] = (),
    *,
    extra_args: Sequence[str] = (),
    timeout: float | None = None,
) -> SuiteRun:
    """Run the whole suite, or only the given files and test IDs, in /workspace/repo."""
    return _run(sandbox, targets, extra_args, timeout, collect_only=False)


def collect_tests(sandbox: Sandbox, targets: Sequence[str] = ()) -> SuiteRun:
    """Collect without running. `collected_ids` lists every test ID."""
    return _run(sandbox, targets, (), None, collect_only=True)


def ensure_has_tests(sandbox: Sandbox) -> SuiteRun:
    """Collect the suite; reject the repo only if collection worked and found nothing."""
    collected = collect_tests(sandbox)
    if collected.status == NO_TESTS_STATUS:
        raise InputError(
            NO_TESTS,
            "This repository has no tests that pytest can find, so Bugbite cannot verify a fix. "
            "Only repositories with an existing test suite are supported.",
        )
    return collected
