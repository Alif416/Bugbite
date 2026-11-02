"""Build a `RepoIndex` by running the scanner inside the sandbox."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from bugbite.sandbox.setup import REPO_DIR

from .errors import BAD_LIMITS, BAD_OUTPUT, OUTPUT_TOO_LARGE, SCAN_FAILED, SCAN_TIMEOUT, RetrievalError
from .scanner import SCANNER_SOURCE
from .types import RepoIndex


@dataclass(frozen=True)
class IndexLimits:
    """What the scanner may read and report. The output budget must stay under the sandbox's output cap (1 MiB by default)."""

    max_files: int = 5_000
    max_symbols: int = 20_000
    max_file_bytes: int = 500_000
    max_output_bytes: int = 900_000
    max_depth: int = 30

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value <= 0:
                raise RetrievalError(BAD_LIMITS, f"{name} must be a whole number greater than zero")


def parse_scanner_output(text: str) -> RepoIndex:
    try:
        data: Any = json.loads(text)
    except (ValueError, RecursionError):
        raise RetrievalError(BAD_OUTPUT, "The scanner's output was not valid JSON.") from None
    return RepoIndex.from_json(data)


def build_index(sandbox: Any, *, limits: IndexLimits | None = None, root: str = REPO_DIR, timeout: float | None = None) -> RepoIndex:
    """Index the repository at `root` inside `sandbox`. Nothing is written, and no repo code is run."""
    limits = limits or IndexLimits()
    kwargs = {} if timeout is None else {"timeout": timeout}
    done = sandbox.run(["python", "-c", SCANNER_SOURCE, root, json.dumps(asdict(limits))], **kwargs)
    if done.timed_out:
        raise RetrievalError(SCAN_TIMEOUT, "Indexing the repository took too long and was stopped.")
    if done.truncated:
        raise RetrievalError(OUTPUT_TOO_LARGE, "The index was larger than the sandbox allows; lower the limits.")
    if done.exit_code != 0:
        detail = (done.stderr or "").strip()[:300]
        raise RetrievalError(SCAN_FAILED, f"The scanner failed (exit code {done.exit_code}){': ' + detail if detail else ''}.")
    return parse_scanner_output(done.stdout)
