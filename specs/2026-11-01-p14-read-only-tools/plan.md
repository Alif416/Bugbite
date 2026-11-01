# Plan: Read-only Agent Tools (Roadmap P14)

Branch: `2026-11-01-p14-read-only-tools`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-082 onward).

## 1. Tool base and registry (`src/bugbite/agent/tools/`)

1. `base.py`: `ToolOutput(text, is_error=False)` (frozen); `Tool` with `definition: ToolDefinition` and `run(arguments: dict) -> ToolOutput`. A helper validates arguments against the definition's JSON Schema (jsonschema is already a dependency) and returns an error result listing what is wrong.
2. `registry.py`: `ToolRegistry(tools)` with `definitions()` and `execute(name, arguments) -> ToolOutput`. An unknown tool, bad arguments, or an unexpected exception from a tool becomes an error result; nothing is raised into the loop. Duplicate names are rejected.
3. `build_read_only_tools(sandbox)` returns the three tools bound to one sandbox.

## 2. Path safety

`paths.py`: `resolve_repo_path(raw) -> str` turns a model-supplied path into an absolute path under `/workspace/repo`. It rejects absolute paths, `..` segments, NUL and newline, empty strings where a file is needed, and any path touching `.git`. Backslashes and a leading `./` are normalised. This is tested with a seeded property test and a list of known escape tricks.

## 3. `list_directory`

Runs `find` with an argument list (one level, `-mindepth 1 -maxdepth 1`) and formats directories first, sorted, capped at 200 entries, `.git` removed. A path that is a file or does not exist gives an error result.

## 4. `read_file`

Reads through `Sandbox.read_file` with a byte limit, rejects directories (missing returns `None`), rejects binary content (NUL bytes), decodes as UTF-8 with replacement, numbers lines, applies the line and character caps, and appends the continuation hint. `start_line` and `end_line` are 1-based, inclusive, validated (`start <= end`, `start >= 1`); a start past the end is an error that states the file's length.

## 5. `search_code`

Runs `grep` with `-rnI` (add `-F` unless `regex` is true), `--exclude-dir` for `.git node_modules .venv venv __pycache__ .tox .mypy_cache .pytest_cache`, optional `--include=<glob>` (glob validated: no `/`, no control characters), then `--` and the pattern and path. Exit 1 means no matches (normal), exit 2 or a timeout is an error. The output is trimmed to 50 matches with each line cut to 200 characters, paths shown relative to the repo.

## 6. Tool descriptions

Write each description for a small model: one sentence of purpose, each argument, the caps, and an example. Descriptions are plain text with no secrets and are version-tagged (`TOOLS_VERSION = "1"`) so recordings can say which tool text a run used.

## 7. Tests

1. A `FakeSandbox` (in-memory files, simple `run` for `find`/`grep` that mimics output) for fast unit tests of caps, formatting, and error results; plus a command-capture test proving no shell string is built and that `--` precedes model input.
2. Path-safety tests: escape tricks, property test.
3. Registry tests: unknown tool, bad arguments, exception inside a tool, duplicate names, definitions pass `ToolDefinition` validation and work with `TextActionAdapter` schema checks.
4. Opt-in Docker tests against a real sandbox with a small repo: real `find`/`grep` output matches what the parser expects, including a file with a weird name, a binary file, and a symlink pointing outside the repo.
5. Mutation check on the safety properties (path escape allowed, shell string used, cap removed, `.git` visible).

## 8. Docs

README section "Agent tools (read-only)"; roadmap P14 ticked; findings added to `requirements.md`; validation ticked.
