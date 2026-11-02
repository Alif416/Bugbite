# Plan: File tree and symbol index (Roadmap P25)

Branch: `2026-11-02-p25-file-tree-symbol-index`. See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-128 onward).

## 1. Code (`src/bugbite/retrieval/`)

1. `types.py`: frozen dataclasses `FileEntry(path, size, language, lines, parse_error)`, `Symbol(kind, name, qualname, path, line, end_line, signature, doc, decorators, parent)`, `RepoIndex(files, symbols, truncated, schema_version)` with JSON round trip and strict validation of untrusted input (types, lengths, no paths outside the repo).
2. `scanner.py`: `SCANNER_SOURCE`, the stdlib-only script run inside the sandbox: walks the repo (no symlink escape, skips junk dirs, size and count limits), parses `.py` files with `ast`, emits one JSON document on stdout. Also runnable on a plain folder, which is how fast tests use it.
3. `index.py`: `build_index(sandbox, *, limits)` writes the script, runs it with `python`, bounds and validates the output, and returns a `RepoIndex`; errors become a clear `RetrievalError`. Lookups: `find(name)`, `in_file(path)`, `by_kind(kind)`, `get(qualname)`.
4. `render.py`: `render_tree(index, max_lines)`, `render_symbols(symbols, max_lines)`; always bounded, says how much was left out.
5. `__init__.py` exports; `errors.py` gets a `RetrievalError` code if the project's error pattern calls for it.

## 2. Tests

1. Scanner on a temp folder: functions, async, classes, methods, nested classes and functions, decorators, signatures (defaults, `*args`, keyword-only, annotations), docstrings, line ranges, lambdas excluded, unicode names, syntax errors and null bytes and non-UTF-8 files, empty files, huge files skipped with a reason, symlink loops and symlinks out of the repo, junk directories skipped, file and symbol limits with `truncated`.
2. Index: lookups, ordering stable, JSON round trip, hostile JSON rejected (wrong types, absolute or `..` paths, giant strings, too many items), schema version.
3. Rendering: bounded output, deterministic, says what was cut.
4. Through the stand-in sandbox (`LocalSandbox`) and, marked `docker`, through the real sandbox on a small repo; the real sandbox must come away clean (no leftover containers).
5. Real code: index this repository's own `src/bugbite` and check known symbols (for example `run_agent`, `ModelAdapter`), and that the run finishes within a few seconds.
6. Properties: random Python sources never crash the scanner; every symbol's line range is inside its file.
7. No import or execution of repo code: a test repo whose module raises or writes a marker file on import is indexed with no side effect.
8. Mutation check: scanner ignoring async functions, off-by-one lines, wrong qualname for nested items, following symlinks out, not skipping `.git`, no size limit, host accepting an absolute path, truncation flag dropped.

## 3. Docs

README section "Code index"; decisions; roadmap tick; findings.

## 4. Commits (small, logical)

1. Specs. 2. Types and validation. 3. Scanner. 4. Index and rendering. 5. Tests and the Docker test. 6. Docs and ticks.
