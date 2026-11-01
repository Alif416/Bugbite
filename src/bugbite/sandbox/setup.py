"""Get a repo into the sandbox and ready to test: clone, install, cut the network.

Setup failures are returned as a `SetupResult` (with a `failure_reason` that the
failure classifier can use later). Exceptions are for infrastructure problems.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from bugbite.errors import WORKSPACE_FULL, SandboxError
from bugbite.github.urls import RepoRef
from bugbite.sandbox.container import Sandbox

REPO_DIR = "/workspace/repo"
VENV_DIR = "/workspace/.venv"
_PY = f"{VENV_DIR}/bin/python"
_PIP = (_PY, "-m", "pip")
OUTPUT_TAIL_CHARS = 2000

# failure_reason values
CLONE_FAILED = "clone_failed"
INSTALL_FAILED = "install_failed"
PYTEST_UNAVAILABLE = "pytest_unavailable"
SETUP_TIMEOUT = "setup_timeout"
WORKSPACE_FULL_REASON = "workspace_full"

_PACKAGING_FILES = ("pyproject.toml", "setup.py", "setup.cfg")
_TEST_REQUIREMENTS = (
    "requirements-dev.txt",
    "requirements-test.txt",
    "requirements_test.txt",
    "test-requirements.txt",
    "dev-requirements.txt",
)
_TEST_GROUPS = ("test", "tests", "testing")
# PEP 735 dependency groups need pip 25.1 or newer; the base image ships an older pip.
_MIN_PIP_FOR_GROUPS = "pip>=25.1"
_GROUP_SCRIPT = (
    "import sys, tomllib\n"
    "data = tomllib.load(open(sys.argv[1], 'rb'))\n"
    "print(*data.get('dependency-groups', {}))\n"
)
_HEX_REF = re.compile(r"[0-9a-fA-F]{7,40}")
_NAME_REF = re.compile(r"[A-Za-z0-9._/-]{1,200}")


# -- results ---------------------------------------------------------------


@dataclass(frozen=True)
class StepResult:
    name: str
    command: tuple[str, ...]
    exit_code: int
    duration_s: float
    timed_out: bool
    output_tail: str
    required: bool
    ok: bool


@dataclass(frozen=True)
class SetupResult:
    ok: bool
    head_commit: str | None
    steps: tuple[StepResult, ...]
    warnings: tuple[str, ...]
    workspace_mb: int | None
    failure_reason: str | None


@dataclass(frozen=True)
class InstallStep:
    """One install step. `commands` are alternatives: the first to succeed wins."""

    name: str
    commands: tuple[tuple[str, ...], ...]
    required: bool


# -- pure helpers (no Docker) ----------------------------------------------


def repo_clone_url(repo: RepoRef) -> str:
    """HTTPS clone URL built only from a validated `RepoRef`."""
    if not isinstance(repo, RepoRef):
        raise TypeError("repo_clone_url needs a validated RepoRef")
    return f"https://github.com/{repo.owner}/{repo.name}.git"


def validate_ref(ref: str) -> str:
    """Accept a commit hash, branch, or tag name; reject anything that could act as an option."""
    if not isinstance(ref, str) or not ref:
        raise ValueError("ref must be a non-empty string")
    if _HEX_REF.fullmatch(ref):
        return ref
    bad = (
        not _NAME_REF.fullmatch(ref)
        or ref.startswith(("-", "/", "."))
        or ref.endswith(("/", ".", ".lock"))
        or ".." in ref
        or "//" in ref
    )
    if bad:
        raise ValueError(f"invalid ref: {ref!r}")
    return ref


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or url.startswith("-") or any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValueError(f"invalid clone URL: {url!r}")
    return url


def select_groups(names: Iterable[str]) -> list[str]:
    """Pick the dependency groups worth installing: test-like ones, else `dev` as a fallback."""
    available = set(names)
    chosen = [name for name in _TEST_GROUPS if name in available]
    if chosen:
        return chosen
    return ["dev"] if "dev" in available else []


def plan_install(files: Iterable[str], groups: Iterable[str] = ()) -> list[InstallStep]:
    """Ordered install steps for a repo.

    `files` are the names of its top-level files; `groups` are the PEP 735
    dependency groups to install (already filtered with `select_groups`).
    """
    present = set(files)
    wanted_groups = [g for g in groups if g in (*_TEST_GROUPS, "dev")]
    steps = [InstallStep("venv", (("python", "-m", "venv", VENV_DIR),), required=True)]
    if wanted_groups:
        steps.append(InstallStep("pip-upgrade", ((*_PIP, "install", "--upgrade", _MIN_PIP_FOR_GROUPS),), required=False))

    if any(name in present for name in _PACKAGING_FILES):
        steps.append(
            InstallStep(
                "project",
                (
                    (*_PIP, "install", "-e", ".[test,tests,testing]"),
                    (*_PIP, "install", "-e", "."),
                ),
                required=True,
            )
        )
    elif "requirements.txt" in present:
        steps.append(InstallStep("requirements", ((*_PIP, "install", "-r", "requirements.txt"),), required=True))

    for group in wanted_groups:
        steps.append(InstallStep(f"dependency-group:{group}", ((*_PIP, "install", "--group", group),), required=False))

    for name in _TEST_REQUIREMENTS:
        if name in present:
            steps.append(InstallStep(f"test-requirements:{name}", ((*_PIP, "install", "-r", name),), required=False))

    steps.append(
        InstallStep(
            "pytest",
            (
                (
                    "sh",
                    "-c",
                    f"{_PY} -c 'import pytest' 2>/dev/null || {_PY} -m pip install pytest",
                ),
            ),
            required=True,
        )
    )
    return steps


def _tail(stdout: str, stderr: str) -> str:
    text = (stdout + stderr).strip()
    return text[-OUTPUT_TAIL_CHARS:]


# -- running setup ---------------------------------------------------------


def _run_step(
    sandbox: Sandbox,
    name: str,
    command: tuple[str, ...],
    *,
    required: bool,
    workdir: str,
) -> StepResult:
    result = sandbox.run(list(command), timeout=sandbox.config.setup_timeout_s, workdir=workdir)
    return StepResult(
        name=name,
        command=command,
        exit_code=result.exit_code,
        duration_s=result.duration_s,
        timed_out=result.timed_out,
        output_tail=_tail(result.stdout, result.stderr),
        required=required,
        ok=result.exit_code == 0 and not result.timed_out,
    )


def clone_repo(sandbox: Sandbox, clone_url: str, ref: str | None = None) -> list[StepResult]:
    """Clone shallowly into /workspace/repo. Returns the steps run (last one failed if cloning failed)."""
    url = _validate_url(clone_url)
    workdir = "/workspace"
    git = ("git", "-c", "protocol.ext.allow=never")
    steps: list[StepResult] = []

    if ref is None:
        commands = [("clone", git + ("clone", "--depth", "1", "--no-recurse-submodules", "--", url, REPO_DIR))]
    else:
        safe_ref = validate_ref(ref)
        commands = [
            ("init", git + ("init", "--", REPO_DIR)),
            ("remote", git + ("-C", REPO_DIR, "remote", "add", "--", "origin", url)),
            ("fetch", git + ("-C", REPO_DIR, "fetch", "--depth", "1", "--no-recurse-submodules", "origin", safe_ref)),
            ("checkout", git + ("-C", REPO_DIR, "checkout", "--detach", "FETCH_HEAD")),
        ]
    for name, command in commands:
        step = _run_step(sandbox, f"git-{name}", command, required=True, workdir=workdir)
        steps.append(step)
        if not step.ok:
            break
    return steps


def _failure_reason(step: StepResult) -> str:
    if step.timed_out:
        return SETUP_TIMEOUT
    if step.name.startswith("git-"):
        return CLONE_FAILED
    if step.name == "pytest":
        return PYTEST_UNAVAILABLE
    return INSTALL_FAILED


def setup_workspace(sandbox: Sandbox, clone_url: str, ref: str | None = None) -> SetupResult:
    """Clone, install, check the workspace size, and always cut the network at the end."""
    try:
        return _setup(sandbox, clone_url, ref)
    finally:
        # Fail closed: if the network cannot be cut, this raises and the caller must not continue.
        sandbox.disconnect_network()


def setup_repo(sandbox: Sandbox, repo: RepoRef, ref: str | None = None) -> SetupResult:
    return setup_workspace(sandbox, repo_clone_url(repo), ref)


def _setup(sandbox: Sandbox, clone_url: str, ref: str | None) -> SetupResult:
    steps: list[StepResult] = []
    warnings: list[str] = []

    def finish(reason: str | None, head: str | None = None, used: int | None = None) -> SetupResult:
        return SetupResult(
            ok=reason is None,
            head_commit=head,
            steps=tuple(steps),
            warnings=tuple(warnings),
            workspace_mb=used,
            failure_reason=reason,
        )

    # 1. clone
    clone_steps = clone_repo(sandbox, clone_url, ref)
    steps.extend(clone_steps)
    if not clone_steps[-1].ok:
        return finish(_failure_reason(clone_steps[-1]))
    head_command = ("git", "-C", REPO_DIR, "rev-parse", "HEAD")
    head_run = sandbox.run(list(head_command), timeout=60)
    steps.append(
        StepResult(
            name="git-rev-parse",
            command=head_command,
            exit_code=head_run.exit_code,
            duration_s=head_run.duration_s,
            timed_out=head_run.timed_out,
            output_tail=_tail(head_run.stdout, head_run.stderr),
            required=True,
            ok=head_run.exit_code == 0 and not head_run.timed_out,
        )
    )
    if not steps[-1].ok:
        return finish(CLONE_FAILED)
    head = head_run.stdout.strip()

    try:
        used = sandbox.check_workspace()
    except SandboxError as exc:
        if exc.code == WORKSPACE_FULL:
            return finish(WORKSPACE_FULL_REASON, head)
        raise

    # 2. install
    listing = sandbox.run(["ls", "-A", REPO_DIR], timeout=60)
    files = listing.stdout.split()
    if not any(name in files for name in (*_PACKAGING_FILES, "requirements.txt")):
        warnings.append("No packaging file or requirements.txt found; only pytest was installed.")
    groups: list[str] = []
    if "pyproject.toml" in files:
        found = sandbox.run(["python", "-c", _GROUP_SCRIPT, f"{REPO_DIR}/pyproject.toml"], timeout=60)
        if found.exit_code == 0:
            groups = select_groups(found.stdout.split())
        else:
            warnings.append("Could not read pyproject.toml to look for dependency groups.")
    for step in plan_install(files, groups):
        succeeded = False
        for command in step.commands:
            result = _run_step(sandbox, step.name, command, required=step.required, workdir=REPO_DIR)
            steps.append(result)
            if result.ok:
                succeeded = True
                break
            if result.timed_out:
                break  # a timeout is not worth retrying with a fallback
        if succeeded:
            continue
        if step.required:
            return finish(_failure_reason(steps[-1]), head)
        warnings.append(f"Optional step '{step.name}' failed; continuing.")

    # 3. size check after install
    try:
        used = sandbox.check_workspace()
    except SandboxError as exc:
        if exc.code == WORKSPACE_FULL:
            return finish(WORKSPACE_FULL_REASON, head)
        raise
    return finish(None, head, used)
