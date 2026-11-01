"""Pure logic of sandbox setup: no Docker, no network."""

import pytest

from bugbite.github import RepoRef
from bugbite.sandbox import plan_install, repo_clone_url, select_groups, validate_ref
from bugbite.sandbox.setup import (
    CLONE_FAILED,
    INSTALL_FAILED,
    PYTEST_UNAVAILABLE,
    SETUP_TIMEOUT,
    StepResult,
    _failure_reason,
)


def names(files):
    return [step.name for step in plan_install(files)]


def step(plan, name):
    return next(s for s in plan if s.name == name)


@pytest.mark.parametrize("packaging", ["pyproject.toml", "setup.py", "setup.cfg"])
def test_packaging_file_installs_project_editable_with_fallback(packaging):
    plan = plan_install([packaging, "README.md"])
    assert [s.name for s in plan] == ["venv", "project", "pytest"]
    project = step(plan, "project")
    assert project.required is True
    assert project.commands[0][-1] == ".[test,tests,testing]"
    assert project.commands[1][-1] == "."
    assert all("-e" in c for c in project.commands)


def test_requirements_only():
    plan = plan_install(["requirements.txt", "app.py"])
    assert [s.name for s in plan] == ["venv", "requirements", "pytest"]
    assert step(plan, "requirements").commands == (
        ("/workspace/.venv/bin/python", "-m", "pip", "install", "-r", "requirements.txt"),
    )
    assert step(plan, "requirements").required is True


def test_packaging_wins_over_requirements_txt():
    assert names(["pyproject.toml", "requirements.txt"]) == ["venv", "project", "pytest"]


def test_test_requirements_are_optional_and_come_before_pytest():
    plan = plan_install(["setup.py", "requirements-dev.txt", "test-requirements.txt"])
    assert [s.name for s in plan] == [
        "venv",
        "project",
        "test-requirements:requirements-dev.txt",
        "test-requirements:test-requirements.txt",
        "pytest",
    ]
    assert not step(plan, "test-requirements:requirements-dev.txt").required


def test_nothing_to_install_still_gets_venv_and_pytest():
    assert names(["README.md", "main.py"]) == ["venv", "pytest"]
    assert names([]) == ["venv", "pytest"]


def test_pytest_is_last_and_only_installs_when_missing():
    plan = plan_install(["pyproject.toml", "requirements-test.txt"])
    last = plan[-1]
    assert last.name == "pytest" and last.required
    assert "import pytest" in last.commands[0][-1]
    assert "||" in last.commands[0][-1]


def test_every_plan_starts_with_a_venv():
    for files in ([], ["setup.py"], ["requirements.txt"]):
        first = plan_install(files)[0]
        assert first.name == "venv"
        assert first.commands[0] == ("python", "-m", "venv", "/workspace/.venv")


def test_install_commands_never_use_a_shell_with_repo_text():
    for files in (["pyproject.toml", "requirements-dev.txt"], ["requirements.txt"]):
        for s in plan_install(files):
            for command in s.commands:
                if command[0] == "sh":
                    assert s.name == "pytest"  # the only fixed shell string, built from constants


# -- refs ----------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    ["abc1234", "0123456789abcdef0123456789abcdef01234567", "main", "v1.2.3", "release/1.2", "feature_x-1", "A1b2C3d"],
)
def test_valid_refs(ref):
    assert validate_ref(ref) == ref


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "-x",
        "--upload-pack=evil",
        "a b",
        "a;b",
        "a$b",
        "a`b`",
        "a\nb",
        "..",
        "a..b",
        "/abs",
        ".hidden",
        "trailing/",
        "name.lock",
        "a//b",
        "x" * 201,
        "a'b",
        "a|b",
    ],
)
def test_invalid_refs(ref):
    with pytest.raises(ValueError):
        validate_ref(ref)


def test_non_string_ref():
    for bad in (None, 5, b"abc1234"):
        with pytest.raises(ValueError):
            validate_ref(bad)


# -- clone url -----------------------------------------------------------


def test_clone_url_from_repo_ref():
    assert repo_clone_url(RepoRef("octo", "hello")) == "https://github.com/octo/hello.git"


def test_clone_url_requires_a_repo_ref():
    with pytest.raises(TypeError):
        repo_clone_url("https://github.com/octo/hello")


# -- failure reasons -------------------------------------------------------


def make_step(name, timed_out=False):
    return StepResult(name, ("x",), 1, 0.0, timed_out, "", True, False)


def test_failure_reasons():
    assert _failure_reason(make_step("git-clone")) == CLONE_FAILED
    assert _failure_reason(make_step("git-fetch")) == CLONE_FAILED
    assert _failure_reason(make_step("venv")) == INSTALL_FAILED
    assert _failure_reason(make_step("project")) == INSTALL_FAILED
    assert _failure_reason(make_step("requirements")) == INSTALL_FAILED
    assert _failure_reason(make_step("pytest")) == PYTEST_UNAVAILABLE
    assert _failure_reason(make_step("project", timed_out=True)) == SETUP_TIMEOUT
    assert _failure_reason(make_step("git-clone", timed_out=True)) == SETUP_TIMEOUT


# -- dependency groups (PEP 735) -------------------------------------------


@pytest.mark.parametrize(
    "available, expected",
    [
        (["tests"], ["tests"]),
        (["test", "tests", "docs"], ["test", "tests"]),
        (["testing", "dev"], ["testing"]),  # test-like groups win over dev
        (["dev", "docs"], ["dev"]),  # dev only as a fallback
        (["docs", "typing"], []),
        ([], []),
    ],
)
def test_select_groups(available, expected):
    assert select_groups(available) == expected


def test_groups_add_pip_upgrade_and_group_steps_in_order():
    plan = plan_install(["pyproject.toml"], ["tests"])
    assert [s.name for s in plan] == ["venv", "pip-upgrade", "project", "dependency-group:tests", "pytest"]
    assert step(plan, "pip-upgrade").required is False
    assert step(plan, "dependency-group:tests").required is False
    assert step(plan, "dependency-group:tests").commands == (
        ("/workspace/.venv/bin/python", "-m", "pip", "install", "--group", "tests"),
    )
    assert step(plan, "pip-upgrade").commands[0][-1] == "pip>=25.1"


def test_no_groups_means_no_pip_upgrade():
    assert "pip-upgrade" not in names(["pyproject.toml"])


def test_unknown_group_names_are_ignored():
    # Only fixed, whitelisted names can reach a pip command line.
    plan = plan_install(["pyproject.toml"], ["--evil", "docs", "x; rm -rf /"])
    assert [s.name for s in plan] == ["venv", "project", "pytest"]
