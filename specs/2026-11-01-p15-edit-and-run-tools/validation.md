# Validation: Edit and Run Tools (Roadmap P15)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable: only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Registry:** six tools (`read_file`, `list_directory`, `search_code`, `edit_file`, `run_tests`, `run_command`) with valid definitions, unique names, `additionalProperties` false; `TOOLS_VERSION` is "2"; bad arguments for every new tool are error results, never exceptions.
- [x] **edit_file replace:** exactly one match replaces; zero or many matches are errors that say how many and what to do; same text is an error; deletion works; the confirmation shows the edited region with line numbers; CRLF, missing trailing newline and file mode are preserved.
- [x] **edit_file create:** creates a new file and missing parent directories; refuses an existing path; created files can be edited again.
- [x] **edit_file limits:** binary, non-UTF-8 and over-1 MB files are refused; the 20,000 character limits are enforced by the schema.
- [x] **Path safety:** `..`, absolute paths, `.git`, and symlinks leading outside the repo are refused for edits and creates; a symlink inside the repo is followed only to a file inside the repo.
- [x] **Protected paths:** existing test files, test config, CI files and dependency pins are refused with a helpful message; new test files can be created; protected config, CI and pins cannot be created either; matching ignores case; a folder merely containing the word "tests" in a longer name is not a test folder; the caller's allow list works and no tool argument can change it.
- [x] **Skip guard:** creating or editing an agent-created test file with skip, skipif or xfail is refused.
- [x] **run_tests:** summary of passing, failing, erroring, collection-error, timeout, crashed and no-tests results; lists and tail are capped with a note; invalid targets are error results; `-k` is passed as separate arguments.
- [x] **run_command:** exit code and output formatted; head and tail cut with a marker; timeout reported; empty output says so; refuses when the sandbox has network access; the environment passed is exactly the constants.
- [x] **No shell for the other tools:** `edit_file` and `run_tests` pass model text only as file content or separate arguments; only `run_command` uses a shell string, asserted in a test.
- [x] **Mutation check:** each of these breakages makes at least one test fail: protection disabled, multiple matches allowed, symlink containment disabled, mode not restored, network check removed, output cap removed, `-k` merged into one argument.

## Docker tests (opt-in; run once before merge)

- [x] Against a real sandbox with a small repo: an edit turns a failing test into a passing one through `run_tests`; `run_command` runs with no network and the virtualenv's Python first on `PATH`; a sleeping command is killed at the timeout; an executable file keeps its mode after an edit; a symlink to outside the repo cannot be written through; no leftover labelled containers or volumes.

## Manual checks

- [x] Read each new tool description as if you were a small model: is it clear what to pass and what comes back?
- [x] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-088 to AD-091 with reasons.
- [x] `specs/roadmap.md` has P15 ticked.
- [x] README explains the tools, the guards, and the `run_command` gap.
- [x] Commits are small and logical on branch `2026-11-01-p15-edit-and-run-tools`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no loop, no caps, no verifier).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
