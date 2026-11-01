# Requirements: Edit and Run Tools (Roadmap P15)

## Goal

Give the agent its hands: a tool to change files, a tool to run the repo's tests, and a tool to run a command. Together with the read-only tools (P14) this completes the tool list in FR5.2. The loop that uses them is P16; the whole-patch checks and hard caps come later (P17, P33 to P36).

## Scope

**In:**
- `edit_file`: exact find-and-replace in an existing file, or create a new file
- `run_tests`: run the repo's pytest (optionally only some tests) and return a compact summary
- `run_command`: run a shell command in the sandbox with a timeout and capped output
- Tool-level cheating guards in `edit_file` (FR6.5): existing test files, test configuration, CI files and dependency pins cannot be changed by the agent; a new test file cannot hide failures with skip or xfail
- The same error-result behaviour as P14: a bad call never raises

**Out (later phases):**
- The loop (P16), step/cost/time caps (P17), loop detection (P18)
- Checking the whole patch: size caps, diffing against the baseline, protected files seen through `run_command`, clean-container re-verification (P33 to P36). The tool guards are a first line, not the verifier
- Reproduction-test workflow (FR4)
- Linter and formatter runs (FR6.4)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Edit style | Exact find-and-replace; omit `old_text` to create a new file | Minimal edits (FR5.6), cheap in tokens, small models handle it better than diffs (AD-088) |
| Guards | `edit_file` refuses protected paths in code; the caller (not the model) can allow specific paths when the issue is about them | FR6.5 must hold in code, not in the prompt (AD-089) |
| `run_command` | Any shell command, run only in the sandbox with the network off, timeout and output cap | The sandbox is the safety boundary; an allow-list would block legitimate debugging (AD-090) |
| `run_tests` output | Compact summary built from the structured pytest report | Small context (FR3.4); the model needs failures, not logs (AD-091) |

See `specs/decisions.md` AD-088 to AD-091.

## Behaviour

- **edit_file(path, new_text, old_text?)**
  - With `old_text`: the file must exist, `old_text` must occur exactly once (0 or more than 1 is an error that says how many times and asks for more context), and `new_text` replaces it. `old_text` equal to `new_text` is an error. `new_text` may be empty (a deletion).
  - Without `old_text`: creates a new file and fails if the path exists. Parent directories are created. The agent can keep editing files it created itself.
  - Text only: files that are binary or not valid UTF-8, or larger than 1 MB, are refused. Line endings and the trailing newline are preserved exactly. File permissions (for example an executable script) are preserved.
  - `old_text` and `new_text` are limited to 20,000 characters each.
  - The reply confirms what changed and shows the edited region with line numbers (at most 20 lines).
- **Protected paths** (refused with a message that says what to do instead):
  - Existing test files: anything under a `tests/`, `test/` or `testing/` folder, `test_*.py`, `*_test.py`, `conftest.py`. New test files can be created.
  - Test configuration: `pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`, `noxfile.py`, `.coveragerc`.
  - CI files: `.github/`, `.gitlab-ci.yml`, `.circleci/`, `.travis.yml`, `azure-pipelines.yml`, `Jenkinsfile`.
  - Dependency pins: `requirements*.txt`, `constraints*.txt`, `Pipfile`, `Pipfile.lock`, `poetry.lock`, `uv.lock`, `environment.yml`.
  - Test configuration, CI files and pins are protected whether or not they exist yet. Test files are protected only if they existed before the agent started.
  - A test file the agent creates may not contain `pytest.mark.skip`, `pytest.skip(`, `skipif` or `xfail` (a simple check; the verifier does the real one).
- **run_tests(targets?, keyword?)**: runs pytest in `/workspace/repo` through the existing runner. Returns the status, counts by outcome, up to 15 failing or erroring test IDs with a one-line message each, up to 5 collection errors, and a capped tail of the output (1,500 characters) when anything failed or the run did not finish normally. A timeout, a crash, or "no tests" is stated plainly. `targets` are file paths or test IDs validated by the existing runner (at most 20); `keyword` is pytest's `-k` expression.
- **run_command(command, timeout_s?)**: runs the shell command in `/workspace/repo` with the project's virtualenv first on `PATH`. Returns the exit code, whether it timed out, and the output (stdout and stderr), cut to the first 3,000 and last 3,000 characters with a marker in between. `timeout_s` is 1 to the sandbox's command timeout (default 120). The tool refuses to run if the sandbox still has network access.

## Context

- README: FR5.2, FR5.6 (minimal edits), FR6.5 (cheating guards), FR3.4 (small context).
- Builds on P4 to P7 (`Sandbox.run`, `write_file`, `run_tests`, report parsing) and P14 (`Tool`, `ToolRegistry`, path rules, the sandbox-side path resolver).
- The model's text becomes file content and, for `run_command`, a command line. Everything runs as the unprivileged sandbox user with no network and no credentials.

## Constraints

- `edit_file` writes only through `Sandbox.write_file` to a path resolved inside the repo (symlinks followed, `.git` excluded); it never writes through a symlink that leaves the repo.
- The only place model text is run as a shell command is `run_command`, and it is documented as such.
- Protected-path rules live in code in one place, with the caller able to allow exact paths; there is no argument the model can pass to switch them off.
- Default `uv run pytest` needs no Docker, internet or key: unit tests use the folder-backed fake sandbox from P14, extended. Real-container tests are opt-in.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- `run_command` can change a protected file (for example `sed -i` on a test) or the pytest report plugin in the sandbox, so the `edit_file` guards can be walked around. The real defence is the verifier diffing the final patch against the original and re-running tests in a clean container (P33 to P36). This gap must be noted in the README and closed there.
- Patch-size caps (FR6.5) are not enforced here.
- Whether the issue is "about" a protected file is for the caller to decide; this phase only gives the caller the switch.
- Output sizes are starting values to be tuned with real runs (P20).
