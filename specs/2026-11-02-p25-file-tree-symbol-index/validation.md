# Validation: File tree and symbol index (Roadmap P25)

The work can be merged when every item below is true.

## Automated

- [ ] `uv run pytest` passes with Docker unreachable (foreground); with Docker running the sandbox test passes and no labelled container or volume is left.
- [ ] **Symbols:** functions, async functions, classes, methods, nested classes and functions are found with correct kind, name, qualified name, start and end line, signature, decorators, first docstring line and parent.
- [ ] **Tree:** every non-skipped file appears with size, language and line count; `.git`, `node_modules`, virtualenvs and caches are skipped; order is stable.
- [ ] **Hard inputs:** syntax errors, null bytes, non-UTF-8, empty and very large files are listed with a reason and never stop the scan.
- [ ] **Limits:** file, byte and symbol limits hold, and `truncated` says so.
- [ ] **Safety:** symlinks that leave the repo or loop are not followed; repo code is never imported or run (a module that writes a marker on import leaves no marker).
- [ ] **Untrusted output:** hostile JSON from the sandbox (wrong types, absolute or `..` paths, oversized strings, too many items, bad version) is rejected with a clear error.
- [ ] **JSON round trip** is exact; **rendering** is bounded, deterministic and says what was left out.
- [ ] **Real code:** indexing this repository's `src/bugbite` finds known symbols in a few seconds.
- [ ] **Real sandbox** (Docker): the same script builds the index inside the container, with no network and no credentials.
- [ ] **No agent change:** tool definitions, tools version and the golden and replay fixtures are untouched; no new dependency (`pyproject.toml`, `uv.lock` unchanged).
- [ ] **Mutation check:** each of the listed breakages fails at least one test.

## Manual

- [ ] README has a "Code index" section; `specs/decisions.md` has an AD for each choice; roadmap P25 ticked; no `Co-Authored-By` on any commit.
