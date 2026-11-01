"""Turn a path from the model into a safe path under the repository root."""

from __future__ import annotations

from bugbite.sandbox.setup import REPO_DIR

MAX_PATH_CHARS = 500


class PathRejected(ValueError):
    """The path is not allowed. The message is written for the model."""


def clean_relative(raw: object, *, allow_root: bool = False) -> str:
    """Return a normalised repo-relative path ('' for the root), or raise `PathRejected`."""
    if not isinstance(raw, str):
        raise PathRejected("The path must be a string.")
    if len(raw) > MAX_PATH_CHARS:
        raise PathRejected(f"The path is longer than {MAX_PATH_CHARS} characters.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise PathRejected("The path contains control characters.")
    text = raw.strip().replace("\\", "/")
    if text.startswith("/"):
        raise PathRejected("Use a path relative to the repository root, not an absolute path.")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathRejected("Paths may not contain '..'.")
    if any(part == ".git" for part in parts):
        raise PathRejected("The .git directory is not available.")
    if not parts and not allow_root:
        raise PathRejected("A file path is required.")
    return "/".join(parts)


def absolute(relative: str) -> str:
    return f"{REPO_DIR}/{relative}" if relative else REPO_DIR


def display(path: str) -> str:
    """A sandbox path shown to the model relative to the repo root."""
    return path[len(REPO_DIR) + 1 :] if path.startswith(REPO_DIR + "/") else path
