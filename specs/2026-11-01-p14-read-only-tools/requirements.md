# Requirements: Read-only Agent Tools (Roadmap P14)

## Goal

Give the agent its eyes: three tools that let a model look at the repository inside the sandbox without changing anything. They are the first half of FR5.2; the editing and command tools come in P15 and the loop in P16.

## Scope

**In:**
- `read_file`, `list_directory`, `search_code`, each with a JSON Schema (`ToolDefinition`) that works for native and text-action models
- A small `Tool` base: a definition plus `run(arguments) -> ToolOutput`
- A registry that returns the definitions for a request and runs a tool call by name
- Path safety: every path is relative to the repo root and cannot escape it
- Hard output caps with a clear truncation notice
- Errors returned to the model as error results, never raised into the loop

**Out (later phases):**
- `edit_file`, `run_tests`, `run_command` (P15)
- The loop that calls tools (P16), step/cost/time caps (P17), loop detection (P18)
- Symbol index, semantic search and file ranking (retrieval phases)
- Recording tool calls to the trace store (P21)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Where tools run | Inside the Docker sandbox (`sandbox.run` / `read_file`) | FR5.2 says "in the sandbox"; repo content is untrusted and never read by host code paths (AD-082) |
| Output size | Hard caps with a truncation notice that says how to get more | FR3.4: never flood the prompt; the model can ask for the next part (AD-083) |
| Search | `grep -rnI` in the sandbox, fixed-string by default | No new dependencies; runs next to the files; binary files skipped (AD-084) |
| Shape | `Tool` class with a definition and `run`; results are `ToolOutput(text, is_error)` | One schema layer shared by every adapter; the loop converts to `ToolResultBlock` (AD-085) |
| Paths | Relative to `/workspace/repo`, validated before use; `.git` is hidden | The model cannot read outside the repo or into git internals (AD-086) |

See `specs/decisions.md` AD-082 to AD-086.

## Behaviour

- **read_file(path, start_line?, end_line?)**: returns numbered lines (`  12| text`). At most 200 lines and 20,000 characters per call; if cut, the output ends with `[truncated: showing lines A-B of N; call again with start_line=B+1]`. A missing file, a directory, a binary file, or an over-large file is an error result saying so.
- **list_directory(path?)**: lists one level (default repo root), directories first with a trailing `/`, at most 200 entries, hiding `.git`. Says how many were left out.
- **search_code(pattern, path?, glob?, regex?)**: `grep -rnI` with fixed-string matching unless `regex` is true; skips `.git`, `node_modules`, virtualenvs and caches; at most 50 matches, each line cut to 200 characters; says when results were cut. No matches is a normal (non-error) result.
- All tools have a short timeout (the sandbox default) and report a timeout as an error.

## Context

- README: FR5.2 (the tool list), FR3.4 (small context), FR5.1 (adapter only), section 6 non-functional (safety).
- Builds on P4 to P7 (`Sandbox.run`, `Sandbox.read_file`, `REPO_DIR`) and P8 (`ToolDefinition`, `ToolResultBlock`).
- Repo content and file names are untrusted. Arguments to grep and path commands are passed as an argument list, never through a shell string.

## Constraints

- No shell string built from model input; use argument lists (`--` before patterns and paths).
- No tool changes the repo or the container.
- Default `uv run pytest` needs no Docker, internet or key: unit tests use a fake sandbox. Real-container tests are opt-in/skipped without Docker, like earlier phases.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Large repos: `search_code` may be slow on very big trees; the timeout bounds it, and indexed search comes in the retrieval phases.
- Whether tool output needs secret scrubbing before going to the model is a P17/P21 concern.

## Findings from the build

- The plan said `find` for listing. It became a small Python script run in the container that also resolves symlinks (AD-087), because only the container can see them and `find -printf` is not portable to the Mac the unit tests run on.
- Unit tests use a folder-backed fake sandbox that really runs the script and `grep` on the host and refuses any other command, so "tools only run python and grep, as argument lists" is itself tested. The same behaviour is checked again in real Docker (symlinks to `/etc`, odd file names, binary files).
- Mutation check: 10 breakages (path escape, `.git` visible, line cap, pattern before `--`, shell string, regex default, symlink containment, list cap, match cap, errors escaping the registry) are all caught.
- Not measured: whether 200 lines, 20,000 characters and 50 matches are the right sizes for a real model; that needs real runs (P20).
