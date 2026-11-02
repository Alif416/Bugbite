"""The scanner: a stand-alone, standard-library-only Python program that Bugbite runs INSIDE the sandbox.

It walks the repository, lists every file, and parses each Python file with `ast` (parsing only: repo code is never
imported or run). It prints one JSON document. The host treats that output as untrusted data (see `RepoIndex.from_json`).

Usage (what `build_index` does): `python -c <SCANNER_SOURCE> <repo root> <limits as JSON>`.
"""

SCANNER_SOURCE = r'''
import ast, json, os, sys

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".nox",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode", "site-packages"}
LANGUAGES = {
    ".py": "python", ".pyi": "python-stub", ".md": "markdown", ".rst": "restructuredtext", ".txt": "text", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".cfg": "ini", ".ini": "ini", ".js": "javascript", ".ts": "typescript",
    ".c": "c", ".h": "c", ".cpp": "c++", ".go": "go", ".rs": "rust", ".java": "java", ".sh": "shell", ".html": "html", ".css": "css",
}
MAX_TEXT = 300


def clip(text, limit=MAX_TEXT):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def unparse(node):
    try:
        return clip(ast.unparse(node))
    except Exception:
        return ""


def first_doc_line(node):
    try:
        doc = ast.get_docstring(node)
    except Exception:
        return ""
    if not doc:
        return ""
    for line in doc.splitlines():
        if line.strip():
            return clip(line.strip(), 200)
    return ""


def signature(node):
    if isinstance(node, ast.ClassDef):
        parts = [unparse(b) for b in node.bases] + [clip(k.arg + "=" + unparse(k.value) if k.arg else "**" + unparse(k.value)) for k in node.keywords]
        return "(" + ", ".join(parts) + ")" if parts else ""
    text = "(" + unparse(node.args) + ")"
    if node.returns is not None:
        text += " -> " + unparse(node.returns)
    return clip(text)


STRUCT = (ast.stmt, ast.excepthandler) + ((ast.match_case,) if hasattr(ast, "match_case") else ())


def symbols_of(tree, rel, budget):
    """Preorder (source order) walk that only descends into statements. Returns the symbols, and whether the limit cut it short."""
    out = []
    stack = [(child, None, None) for child in reversed(list(ast.iter_child_nodes(tree)))]  # (node, scope qualname, scope kind)
    while stack:
        node, scope, scope_kind = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if len(out) >= budget:
                return out, True
            if isinstance(node, ast.ClassDef):
                kind = "class"
            else:
                kind = "method" if scope_kind == "class" else "function"
            if scope is None:
                qual = node.name
            elif scope_kind == "class":
                qual = scope + "." + node.name
            else:
                qual = scope + ".<locals>." + node.name
            if len(qual) > 400:
                continue  # absurdly deep nesting: skip it and everything inside it, so every qualified name fits the index format
            out.append({
                "kind": kind, "name": clip(node.name), "qualname": qual, "path": rel, "line": node.lineno,
                "end_line": getattr(node, "end_lineno", None) or node.lineno, "signature": signature(node), "doc": first_doc_line(node),
                "decorators": [unparse(d) for d in node.decorator_list[:10]], "parent": scope,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            })
            for child in reversed(list(ast.iter_child_nodes(node))):
                if isinstance(child, STRUCT):
                    stack.append((child, qual, "class" if kind == "class" else "function"))
        else:
            for child in reversed(list(ast.iter_child_nodes(node))):
                if isinstance(child, STRUCT):
                    stack.append((child, scope, scope_kind))
    return out, False


def count_lines(data):
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def main(root, cfg):
    if not os.path.isdir(root):
        raise FileNotFoundError("repository folder not found")
    max_files, max_symbols = cfg["max_files"], cfg["max_symbols"]
    max_file_bytes, budget, max_depth = cfg["max_file_bytes"], cfg["max_output_bytes"], cfg["max_depth"]
    files, symbols, truncated = [], [], []
    used = 0
    stack = [(root, "", 0)]
    done = False

    def stop(reason):
        if reason not in truncated:
            truncated.append(reason)

    while stack and not done:
        folder, prefix, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        subfolders = []
        for entry in entries:
            name = entry.name
            try:
                if entry.is_symlink():
                    continue  # never followed, so a link cannot lead out of the repo or loop
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            rel = prefix + name
            if is_dir:
                if name in SKIP_DIRS or name.endswith(".egg-info"):
                    continue
                if depth + 1 > max_depth:
                    stop("max_depth")
                    continue
                subfolders.append((entry.path, rel + "/", depth + 1))
                continue
            if not is_file:
                continue  # sockets, pipes, devices
            if len(files) >= max_files:
                stop("max_files")
                done = True
                break
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            ext = os.path.splitext(name)[1].lower()
            language = LANGUAGES.get(ext, "other")
            lines, error, found = None, None, []
            if size <= max_file_bytes:
                try:
                    with open(entry.path, "rb") as handle:
                        data = handle.read(max_file_bytes + 1)
                except OSError as exc:
                    data, error = None, clip("could not be read (" + type(exc).__name__ + ")", 200)
                if data is not None:
                    if b"\0" in data[:8000]:
                        language = "binary"
                        if ext == ".py":
                            error = "contains null bytes"
                    else:
                        lines = count_lines(data)
                    if language == "python" and error is None:
                        try:
                            tree = ast.parse(data, filename=rel)
                        except Exception as exc:
                            error = clip(type(exc).__name__ + ": " + str(exc).replace(chr(10), " "), 200)
                        else:
                            found, cut = symbols_of(tree, rel, max_symbols - len(symbols))
                            if cut:
                                stop("max_symbols")
                                done = True
            elif ext == ".py":
                error = "too large to parse (" + str(size) + " bytes, limit " + str(max_file_bytes) + ")"
            record = {"path": rel, "size": size, "language": language, "lines": lines, "parse_error": error}
            cost = len(json.dumps(record)) + sum(len(json.dumps(s)) for s in found) + 2 * (1 + len(found))
            if used + cost > budget:
                stop("output_budget")
                done = True
                break
            used += cost
            files.append(record)
            symbols.extend(found)
            if done:
                break
        stack.extend(reversed(subfolders))
    print(json.dumps({"schema_version": 1, "files": files, "symbols": symbols, "truncated": truncated}))


if True:
    try:
        main(sys.argv[1], json.loads(sys.argv[2]))
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + ": " + str(exc)[:300] + "\n")
        sys.exit(2)
'''
