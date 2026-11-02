"""Short, bounded text views of an index, for prompts. They never print the whole repo: they say what they left out."""

from __future__ import annotations

from typing import Iterable

from .ranking_types import Ranking
from .semantic_types import SemanticResults
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


def render_ranking(ranking: Ranking, max_chars: int = 2000) -> str:
    """The ranked files with their reasons, never longer than `max_chars`, cut only between whole lines."""
    if type(max_chars) is not int or max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    blocks: list[list[str]] = []
    for number, c in enumerate(ranking.candidates, 1):
        lines = [_clip(f"{number}. {c.path}  (score {c.score:g})")]
        lines += [_clip(f"   - {r.text}") for r in c.reasons if r.points > 0 or r.kind == "test_file"]
        if c.symbols:
            lines.append(_clip("   symbols: " + "; ".join(f"{h.qualname} {h.line}-{h.end_line}" for h in c.symbols)))
        blocks.append(lines)
    out: list[str] = []
    used = 0
    shown = 0
    for lines in blocks:
        size = sum(len(line) + 1 for line in lines)
        if used + size > max_chars - 60:  # leave room for the closing line
            break
        out.extend(lines)
        used += size
        shown += 1
    left = len(blocks) - shown
    if left:
        out.append(f"... and {left} more candidate files not shown")
    out.extend(_clip(f"note: {n}") for n in ranking.notes)
    text = "\n".join(out)
    if len(text) > max_chars:  # notes can push it over; drop whole trailing lines
        kept = []
        for line in out:
            if sum(len(k) + 1 for k in kept) + len(line) > max_chars:
                break
            kept.append(line)
        text = "\n".join(kept)
    return text


def render_semantic(results: "SemanticResults", max_chars: int = 2000) -> str:
    """The hits with their line ranges, never longer than `max_chars`, cut only between whole lines."""
    if type(max_chars) is not int or max_chars < 100:
        raise ValueError("max_chars must be at least 100")
    blocks = []
    for number, h in enumerate(results.hits, 1):
        lines = [_clip(f"{number}. {h.path}:{h.line}-{h.end_line}  {h.qualname}  (similarity {h.score:.2f})")]
        if h.preview:
            lines.append(_clip(f"   {h.preview}"))
        blocks.append(lines)
    out: list[str] = []
    used = shown = 0
    for lines in blocks:
        size = sum(len(line) + 1 for line in lines)
        if used + size > max_chars - 60:
            break
        out.extend(lines)
        used += size
        shown += 1
    if len(blocks) - shown:
        out.append(f"... and {len(blocks) - shown} more matches not shown")
    out.extend(_clip(f"note: {n}") for n in results.notes)
    kept: list[str] = []
    for line in out:
        if sum(len(k) + 1 for k in kept) + len(line) > max_chars:
            break
        kept.append(line)
    return "\n".join(kept)
