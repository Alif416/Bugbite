# Requirements: File tree and symbol index (Roadmap P25)

Branch: `2026-11-02-p25-file-tree-symbol-index` (from `main` at `ecf2d62`). Covers FR3.1: build a file tree and a symbol index (functions, classes) for the repo. It is the base for ranking (P26, FR3.3, FR3.4) and embeddings search (P27).

## Decisions made with the owner

1. **Where it runs:** the index is built inside the sandbox by a small standard-library-only Python script that parses files with `ast` and prints JSON; the host reads that JSON as data. Repo code is never parsed or run on the host.
2. **Languages:** Python only. Other files appear in the file tree with no symbols.
3. **Agent access:** library only. No agent tool and no prompt change in this phase, so the tool set, the tools version and the golden and replay fixtures do not change. P26 is the first consumer and adds what it needs.

## In scope

- `bugbite.retrieval`: `FileTree`, `Symbol`, `RepoIndex` (file entries plus symbols), built by `build_index(sandbox)`, with lookups: by name, by file, by kind, by qualified name.
- The in-sandbox script (a string/file the host writes and runs with `python`), with limits on files, bytes and symbols; skip directories like `.git`, `node_modules`, `.venv`; do not follow symlinks out of the repo; survive unparsable, binary, huge and oddly-encoded files (a file that does not parse is listed with a reason, not fatal).
- For each symbol: kind (function, async function, method, class), name, qualified name (`Class.method`, nested), file, start and end line, signature (parameter text), first line of the docstring, decorators, parent. Module-level constants are not symbols in this phase.
- A compact, bounded text rendering of the tree and of a symbol list (for use in prompts later); never the whole repo.
- JSON round trip (`to_json` / `from_json`) with a schema version, so an index can be recorded, cached or sent to ranking.
- A full-pipeline test against the real sandbox when Docker is available (skipped otherwise), and a fast test path through the same script on a plain folder.

## Out of scope

- Ranking (P26), embeddings (P27), context trimming (P28), any agent tool, incremental updates, other languages, call graphs and imports.

## Constraints that still hold

- No new dependencies; no network; no credentials in the sandbox; the repo's code is only parsed (`ast.parse`), never imported or executed.
- Output from the sandbox is untrusted data: validated and size-limited on the host.
- No `Co-Authored-By` trailer on commits.

## Findings

(Filled in during the build.)
