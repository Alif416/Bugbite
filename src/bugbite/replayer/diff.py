"""Finding exactly what differs between two requests or two events."""

from __future__ import annotations

from typing import Any

FINGERPRINT_FIELDS = ("sha256", "bytes", "messages", "system_blocks", "tools", "max_output_tokens", "temperature", "stop_sequences")


def fingerprint_differences(recorded: dict[str, Any], replayed: dict[str, Any]) -> list[str]:
    """Names of the fingerprint fields that differ (the full request, if present, is not a field)."""
    return [name for name in FINGERPRINT_FIELDS if recorded.get(name) != replayed.get(name)]


def first_difference(a: Any, b: Any, path: str = "") -> str | None:
    """The path of the first value that differs between two JSON-like values, or None if they are equal.

    Paths look like `messages[2].blocks[0].content`. A key or item present on one side only is named too.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b), key=str):
            here = f"{path}.{key}" if path else str(key)
            if key not in a or key not in b:
                return here
            found = first_difference(a[key], b[key], here)
            if found is not None:
                return found
        return None
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        for index in range(max(len(a), len(b))):
            here = f"{path}[{index}]"
            if index >= len(a) or index >= len(b):
                return here
            found = first_difference(a[index], b[index], here)
            if found is not None:
                return found
        return None
    if type(a) is not type(b) or a != b:
        return path or "(root)"
    return None


def at_path(value: Any, path: str) -> Any:
    """The value at a path made by `first_difference`, or a marker if it is missing."""
    current = value
    token = ""
    i = 0
    steps: list[Any] = []
    while i < len(path):
        c = path[i]
        if c == ".":
            if token:
                steps.append(token)
                token = ""
            i += 1
        elif c == "[":
            if token:
                steps.append(token)
                token = ""
            j = path.index("]", i)
            steps.append(int(path[i + 1:j]))
            i = j + 1
        else:
            token += c
            i += 1
    if token:
        steps.append(token)
    for step in steps:
        try:
            current = current[step]
        except (KeyError, IndexError, TypeError):
            return "(missing)"
    return current


def short(value: Any, limit: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def excerpts(recorded: Any, replayed: Any, around: int = 30, width: int = 70) -> tuple[str, str]:
    """Both values as short text. Two long strings are cut around the first character where they differ, so the difference is visible."""
    if isinstance(recorded, str) and isinstance(replayed, str):
        common = 0
        for x, y in zip(recorded, replayed):
            if x != y:
                break
            common += 1
        start = max(0, common - around)

        def cut(text: str) -> str:
            piece = text[start:start + width]
            return repr(("..." if start else "") + piece + ("..." if start + width < len(text) else ""))

        return cut(recorded), cut(replayed)
    return short(recorded), short(replayed)
