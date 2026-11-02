"""Short, bounded text views of an index, for prompts. They never print the whole repo: they say what they left out."""

from __future__ import annotations

from typing import Iterable

from .types import RepoIndex, Symbol

MAX_LINE_CHARS = 200


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 3] + "..."


def render_tree(index: RepoIndex, max_lines: int = 100) -> str:
    """The file tree, folders first, with a symbol count on Python files. At most `max_lines` lines."""
    if type(max_lines) is not int or max_lines < 2:
        raise ValueError("max_lines must be at least 2")
    tree: dict = {}
    for entry in index.files:
        node = tree
        *folders, name = entry.path.split("/")
        for folder in folders:
            node = node.setdefault(folder + "/", {})
        node[name] = entry
    lines: list[str] = []

    def walk(node: dict, depth: int) -> None:
        for key in sorted(node, key=lambda k: (not k.endswith("/"), k)):
            child = node[key]
            if isinstance(child, dict):
                lines.append("  " * depth + key)
                walk(child, depth + 1)
            else:
                count = index.symbol_count(child.path)
                lines.append("  " * depth + key + (f"  ({count} symbols)" if count else ""))

    walk(tree, 0)
    footer = [f"(index incomplete: {', '.join(index.truncated)})"] if index.truncated else []
    room = max_lines - len(footer)
    if len(lines) > room:
        hidden = len(lines) - (room - 1)
        lines = lines[: room - 1] + [f"... {hidden} more lines not shown"]
    return "\n".join(_clip(line) for line in lines + footer)


def _label(symbol: Symbol) -> str:
    prefix = "async " if symbol.is_async else ""
    return "class" if symbol.kind == "class" else prefix + ("method" if symbol.kind == "method" else "def")


def render_symbols(symbols: Iterable[Symbol], max_lines: int = 50) -> str:
    """One line per symbol: `path:line label qualname(signature) - first docstring line`."""
    if type(max_lines) is not int or max_lines < 2:
        raise ValueError("max_lines must be at least 2")
    items = list(symbols)
    shown = items if len(items) <= max_lines else items[: max_lines - 1]
    lines = []
    for s in shown:
        text = f"{s.path}:{s.line} {_label(s)} {s.qualname}{s.signature}"
        lines.append(_clip(text + (f" - {s.doc}" if s.doc else "")))
    if len(shown) < len(items):
        lines.append(f"... and {len(items) - len(shown)} more symbols")
    return "\n".join(lines)
