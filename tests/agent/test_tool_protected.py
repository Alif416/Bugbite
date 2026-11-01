import pytest

from bugbite.agent.tools.protected import hides_failures, is_test_path, kind_of, protection_reason

EXISTING_BLOCKED = [
    "tests/test_a.py", "tests/data/fixture.json", "test/helpers.py", "pkg/tests/x.py", "src/test_thing.py", "src/thing_test.py",
    "TESTS/test_a.py", "Tests/Sub/x.txt", "testing/x.py",
]
ALWAYS_BLOCKED = [
    "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "noxfile.py", ".coveragerc", "PYTEST.INI", "sub/tox.ini",
    ".github/workflows/ci.yml", ".github/x", ".circleci/config.yml", ".gitlab-ci.yml", ".travis.yml", "azure-pipelines.yml", "Jenkinsfile", "conftest.py", "pkg/conftest.py",  # a new conftest can change how tests behave
    "requirements.txt", "requirements-dev.txt", "requirements/base.txt".replace("requirements/", "requirements_"), "constraints.txt",
    "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock", "environment.yml", "sub/requirements.txt",
]
FREE = [
    "src/app.py", "app.py", "README.md", "docs/tests.md", "src/contest.py", "src/latest.py", "attests/x.py", "mytests/x.py",
    "src/testimony.py", "setup.py", "src/pytest_plugin.py", "requirements.py", "src/requirements.txt.bak",
]


@pytest.mark.parametrize("path", EXISTING_BLOCKED)
def test_existing_test_files_are_protected_but_new_ones_are_not(path):
    assert "not allowed" in protection_reason(path, existed=True)
    assert "create a new test file" in protection_reason(path, existed=True)
    assert protection_reason(path, existed=False) is None
    assert protection_reason(path, existed=True, created_by_agent=True) is None


@pytest.mark.parametrize("path", ALWAYS_BLOCKED)
@pytest.mark.parametrize("existed", [True, False])
def test_config_ci_and_pins_are_protected_even_when_new(path, existed):
    reason = protection_reason(path, existed=existed)
    assert reason and "not allowed" in reason and "Fix the source code instead." in reason


@pytest.mark.parametrize("path", FREE)
def test_ordinary_files_are_free(path):
    assert protection_reason(path, existed=True) is None and protection_reason(path, existed=False) is None


def test_created_by_agent_does_not_unlock_config_or_ci():
    assert protection_reason("pytest.ini", existed=False, created_by_agent=True)
    assert protection_reason(".github/ci.yml", existed=False, created_by_agent=True)
    assert protection_reason("tests/test_new.py", existed=True, created_by_agent=True) is None


def test_the_callers_allow_list_is_exact():
    assert protection_reason("tox.ini", existed=True, allowed={"tox.ini"}) is None
    assert protection_reason("sub/tox.ini", existed=True, allowed={"tox.ini"})
    assert protection_reason("tests/test_a.py", existed=True, allowed=("tests/test_a.py",)) is None
    assert protection_reason("tests/test_b.py", existed=True, allowed=("tests/test_a.py",))


def test_kinds_and_test_paths():
    assert kind_of("") is None and kind_of("tests/test_a.py") == "test" and kind_of("pytest.ini") == "config"
    assert is_test_path("tests/new.py") and is_test_path("src/test_x.py") and not is_test_path("src/app.py")


@pytest.mark.parametrize("text, expected", [
    ("@pytest.mark.skip\ndef test_a(): pass", True), ("pytest.skip('no')", True), ("@pytest.mark.skipif(True, reason='x')", True),
    ("@pytest.mark.xfail", True), ("pytest.mark.xfail(strict=True)", True), ("def test_a():\n    assert f() == 1", False),
    ("# skipping nothing", False), ("def skipper(): pass", False),
])
def test_skip_and_xfail_markers_are_detected(text, expected):
    assert hides_failures(text) is expected
