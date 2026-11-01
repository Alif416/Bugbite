"""Files the agent may not change (README FR6.5), decided in code and not in the prompt.

Test files that already exist, test configuration, CI files and dependency pins are protected, and so is
creating a new conftest.py or test configuration. New test files are allowed. The caller (never the model)
can allow exact paths, for the case where the issue really is about one of them.
"""

from __future__ import annotations

import re
from typing import Collection

_TEST_DIRS = {"tests", "test", "testing"}
_TEST_FILE = re.compile(r"(test_.*\.py|.*_test\.py)", re.IGNORECASE)
_CONFIG_NAMES = {
    "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "noxfile.py", ".coveragerc", "conftest.py",
}
_CI_DIRS = {".github", ".circleci"}
_CI_NAMES = {".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "jenkinsfile"}
_PIN_NAMES = {"pipfile", "pipfile.lock", "poetry.lock", "uv.lock", "environment.yml"}
_PIN_PATTERN = re.compile(r"(requirements|constraints)[^/]*\.txt", re.IGNORECASE)
_SKIP_MARKERS = re.compile(r"pytest\.mark\.skip|pytest\.skip\s*\(|skipif|xfail")

TEST, CONFIG, CI, PINS = "test", "config", "ci", "pins"


def kind_of(relative: str) -> str | None:
    """Which protected group a cleaned repo-relative path belongs to, if any."""
    parts = [part for part in relative.lower().split("/") if part]
    if not parts:
        return None
    name = parts[-1]
    if name in _CONFIG_NAMES:
        return CONFIG
    if parts[0] in _CI_DIRS or name in _CI_NAMES:
        return CI
    if name in _PIN_NAMES or _PIN_PATTERN.fullmatch(name):
        return PINS
    if _TEST_FILE.fullmatch(name) or any(part in _TEST_DIRS for part in parts[:-1]):
        return TEST
    return None


_WHAT = {
    TEST: "an existing test file",
    CONFIG: "test configuration",
    CI: "a CI file",
    PINS: "a dependency pin file",
}


def protection_reason(
    relative: str, *, existed: bool, created_by_agent: bool = False, allowed: Collection[str] = ()
) -> str | None:
    """None if the agent may change this path, else a message for the model."""
    if relative in allowed:
        return None
    kind = kind_of(relative)
    if kind is None:
        return None
    if kind == TEST and (not existed or created_by_agent):
        return None
    advice = (
        "Fix the source code instead. If you need a test, create a new test file."
        if kind == TEST
        else "Fix the source code instead."
    )
    return f"{relative} is {_WHAT[kind]}, which you are not allowed to change. {advice}"


def is_test_path(relative: str) -> bool:
    return kind_of(relative) == TEST


def hides_failures(text: str) -> bool:
    """A simple check for skip and xfail markers in test code the agent writes (the verifier does the real one)."""
    return bool(_SKIP_MARKERS.search(text))
