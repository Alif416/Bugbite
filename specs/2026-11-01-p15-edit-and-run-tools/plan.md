# Plan: Edit and Run Tools (Roadmap P15)

Branch: `2026-11-01-p15-edit-and-run-tools`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-088 onward).

## 1. Protected paths (`src/bugbite/agent/tools/protected.py`)

1. `protection_reason(relative, *, existed, created_by_agent, allowed) -> str | None`: pure function over a cleaned repo-relative path. Returns None if the edit is allowed, or a message for the model.
2. Rules as in `requirements.md`: test files (only if they existed and the agent did not create them), test config, CI files, dependency pins. Names are matched case-insensitively on the file name and on path segments, so `Tests/` and `PYTEST.INI` count.
3. `allowed`: a frozenset of exact relative paths the caller permits. It is a constructor argument of the tool, never an argument of a tool call.
4. `skips_tests(text) -> bool`: true if text contains `pytest.mark.skip`, `pytest.skip(`, `skipif` or `xfail`; used only for test-looking paths the agent creates or edits.

## 2. `edit_file`

1. Extend the sandbox-side resolver (P14) to also report a file's permission bits, so an edit can restore them.
2. Existing file: clean the path, check protection, resolve in the sandbox (must be a file inside the repo), read it (refuse over 1 MB, binary or invalid UTF-8), count occurrences of `old_text`, refuse 0 or more than 1, replace, write with `Sandbox.write_file`, restore the mode with `chmod` if it was not 0644, and return a confirmation with the edited region (numbered, at most 20 lines).
3. New file: path must not exist; find the nearest existing ancestor and resolve it in the sandbox (must be a directory inside the repo), create the missing directories with `mkdir -p` as an argument list, write the file, and remember the path as created by the agent (so it can edit it again and so it is not treated as an existing test).
4. Argument limits from the schema (`maxLength` 20,000 for both texts); `old_text` must be non-empty when given.

## 3. `run_tests`

1. Build on `bugbite.sandbox.run_tests`. Validate `targets` (array of at most 20 strings) with the runner's own checks; map `keyword` to `-k <expr>` as a separate argument after `-k`.
2. `summarise(SuiteRun, target_note) -> str`: status and reason, counts, failing and erroring IDs (up to 15, with the first line of each message cut to 200 characters), collection errors (up to 5), output tail of at most 1,500 characters when anything failed or the status is not ok, and a note when lists were cut. Pure function, unit tested on hand-built `SuiteRun` objects.
3. Invalid targets and sandbox errors come back as error results.

## 4. `run_command`

1. Schema: `command` (string, 1 to 2,000 characters, no NUL), `timeout_s` (integer, 1 to the sandbox's command timeout).
2. Refuse to run if `sandbox.has_network()` is true.
3. Run through the sandbox with the repo as working directory and an environment of `PATH` (virtualenv first), `PYTHONDONTWRITEBYTECODE=1` and nothing else from outside the sandbox; the environment is built from constants.
4. Format: `exit code N` (or `timed out after Ns`), then the output with a head and tail cut and a marker saying how many characters were left out; "(no output)" when empty.

## 5. Registry

`build_agent_tools(sandbox, *, allowed_edit_paths=frozenset()) -> ToolRegistry` with all six tools; `build_read_only_tools` stays. Bump `TOOLS_VERSION` to "2" because the tool text changed. Update the fake sandbox to allow `chmod`, `mkdir` and `sh` for `run_command` and to record writes.

## 6. Tests

1. Protected paths: table of allowed and refused paths, case variants, directory tricks (`tests` as part of a longer name is not a test folder), and the caller's allow list.
2. `edit_file` on a folder-backed fake: single match, no match, many matches, same text, deletion, create, create over an existing file, parent directories, CRLF and no trailing newline preserved, executable bit preserved, binary and non-UTF-8 refused, size cap, symlink out of the repo refused, `.git` refused, edit of a file the agent created, skip/xfail in a new test refused.
3. `run_tests` summary on hand-built results (all passing, failures, errors, collection errors, timeout, crashed, no tests, long lists cut) and argument validation.
4. `run_command`: formatting, cut, timeout, empty output, network-connected refusal, environment contents.
5. Registry: six tools, valid definitions, unique names, bad arguments are error results, `TOOLS_VERSION` is "2".
6. Opt-in Docker tests: edit and test a small repo end to end (edit makes a failing test pass), real `run_command` behaviour (no network, venv python on `PATH`, timeout kills a sleeper), file mode preserved, symlink out of the repo refused.
7. Mutation check: protection off, multiple matches allowed, symlink containment off, mode not restored, network check removed, output cap removed, `-k` built into the same argument as its value.

## 7. Docs

README section "Agent tools (edit and run)" including the known gap with `run_command`; roadmap P15 ticked; findings in `requirements.md`; validation ticked.
