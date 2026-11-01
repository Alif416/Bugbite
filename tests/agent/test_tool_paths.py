import random

import pytest

from bugbite.agent.tools.paths import PathRejected, absolute, clean_relative, display

BAD = [
    "/etc/passwd", "../x", "a/../../x", "a/..", "..", "a/b/../../..", ".git", ".git/config", "a/.git/x", "./.git",
    "a\\..\\b", "..\\x", "x\x00y", "x\ny", "x\ty", "\x7f", "", "   ", "a" * 501, 5, None, b"x",
]


@pytest.mark.parametrize("raw", BAD)
def test_unsafe_paths_are_rejected(raw):
    with pytest.raises(PathRejected):
        clean_relative(raw)


@pytest.mark.parametrize("raw, expected", [
    ("src/app.py", "src/app.py"), ("./src//app.py", "src/app.py"), ("src\\app.py", "src/app.py"),
    ("  a/b/ ", "a/b"), ("a/./b", "a/b"), (".github/x.yml", ".github/x.yml"), ("..foo/x", "..foo/x"), ("a/.gitignore", "a/.gitignore"),
])
def test_valid_paths_are_normalised(raw, expected):
    assert clean_relative(raw) == expected


def test_the_root_is_allowed_only_when_asked_for():
    for raw in ("", ".", "./", " "):
        assert clean_relative(raw, allow_root=True) == ""
        with pytest.raises(PathRejected):
            clean_relative(raw)


def test_absolute_and_display_round_trip():
    assert absolute("a/b") == "/workspace/repo/a/b" and absolute("") == "/workspace/repo"
    assert display("/workspace/repo/a/b") == "a/b" and display("/elsewhere") == "/elsewhere"


def test_no_random_input_resolves_outside_the_repo():
    rng = random.Random(1234)
    alphabet = ["a", "b", ".", "..", "/", "\\", ".git", " ", "x.py", "\x00", "\n", "~"]
    for _ in range(5000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
        try:
            rel = clean_relative(raw, allow_root=True)
        except PathRejected:
            continue
        parts = rel.split("/") if rel else []
        assert ".." not in parts and ".git" not in parts and not rel.startswith("/") and "\x00" not in rel and "\n" not in rel
        assert absolute(rel).startswith("/workspace/repo")
