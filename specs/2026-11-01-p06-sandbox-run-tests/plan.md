# Plan: Sandbox, Run Tests (Roadmap P6)

Branch: `2026-11-01-p06-sandbox-run-tests`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-036 onward).

## 1. Small sandbox additions

1. `Sandbox.write_file(path, content)`: write a file into the container with `put_archive` (tar in memory), owned by uid/gid 1000. The path must be absolute and under `/workspace`; the parent directory must already exist.
2. `Sandbox.run(..., env=None)`: optional extra environment variables for one command, as a dict of strings. Names and values come from Bugbite code only; document that, and reject names that are not valid identifiers.
3. Config: add `test_timeout_s` (default 300) to `SandboxConfig`, its loader, and `config/app.yaml`.
4. Add the `no_tests` code to `InputError` in `src/bugbite/errors.py`.

## 2. The report plugin

1. Create `src/bugbite/sandbox/plugin/bugbite_report.py`, a single self-contained file (standard library only, no f-strings or modern syntax, so it loads on old and new pytest).
2. It appends one JSON object per line to the file named in the environment variable `BUGBITE_REPORT_FILE`, flushing after each line, so partial results survive a timeout or crash:
   - `{"t":"collected","count":N}` once after collection (with `"ids":[...]` when `BUGBITE_LIST_IDS=1`)
   - `{"t":"test","id":nodeid,"outcome":...,"duration":seconds,"message":short text}` once per test, written when its teardown report arrives
   - `{"t":"collect_error","id":...,"message":...}` for each failed collection
   - `{"t":"session","exitstatus":int}` at the end
   - every line carries `"worker"` (the xdist worker name, or `null` on the controller)
3. Outcomes: `passed`, `failed`, `error` (setup or teardown failure), `skipped`, `xfailed`, `xpassed`. A failure is never overwritten by a later pass; messages are cut to 500 characters.
4. Keep the source out of the repo: it lives in the Bugbite package and is copied to `/workspace/.bugbite/bugbite_report.py` before every run.

## 3. Parsing and classification (pure functions, no Docker)

1. `parse_report(text) -> ParsedReport`: tolerate blank or malformed lines (count them), key tests by node ID, take the controller's `session` line, take the largest `collected` count, and collect collection errors.
2. `classify(exit_code, timed_out, report, output_tail) -> (status, reason)` using these rules:
   - timed out gives `timeout`
   - exit 0 or 1 with a `session` line gives `ok`
   - exit 5 with zero collected and no collection errors gives `no_tests`
   - collection errors, or exit 4 (pytest usage error, for example `addopts` naming a plugin that is not installed), give `collection_error` with a reason
   - exit 4 with `bugbite_report` in the output (the plugin itself failed to load), exit 3, a missing `session` line, or any other exit code give `crashed`
3. Dataclasses: `CaseResult(outcome, duration_s, message)`, `CollectionError(id, message)`, `SuiteRun(status, reason, exit_code, tests, collected, collection_errors, duration_s, output_tail, output_truncated, malformed_lines)` with a `counts` property (per outcome) and helper properties `passed_ids`, `failed_ids`.

## 4. Running tests

1. `build_pytest_command(targets, extra_args)`: `/workspace/.venv/bin/python -m pytest -p bugbite_report -p no:cacheprovider --tb=short --color=no`, then the targets and extra arguments. Validate every target: non-empty, no newline or control characters, and not starting with `-` (so it can never be read as a pytest option). `extra_args` is for trusted Bugbite code only.
2. `run_tests(sandbox, targets=(), *, extra_args=(), timeout=None) -> SuiteRun`:
   - create `/workspace/.bugbite`, write the plugin, delete any old report
   - run in `/workspace/repo` with `PYTHONPATH=/workspace/.bugbite` and `BUGBITE_REPORT_FILE`, timeout defaulting to `test_timeout_s`
   - read and parse the report, keep the last 20,000 characters of output, and classify
   - the repo's own pytest configuration is respected; only the flags above are added
3. `collect_tests(sandbox, targets=()) -> SuiteRun`: the same with `--collect-only -q` and `BUGBITE_LIST_IDS=1`, timeout `command_timeout_s`; `tests` is empty and `collected` and the IDs are filled in.
4. `ensure_has_tests(sandbox) -> SuiteRun`: calls `collect_tests`; raises `InputError("no_tests")` with a clear message only when the status is `no_tests`. Collection errors are returned, not rejected.

## 5. Tests

1. Offline, using the host's own pytest in a subprocess (no Docker): drive the real plugin against sample projects covering pass, fail, skip, xfail, xpass, setup error, teardown error, parametrized IDs (including odd characters), test classes, collection error, no tests, `-k` deselection, and a run with `-p xdist` if available. Check the JSONL and the parsed `SuiteRun`.
2. Offline unit tests: `parse_report` (malformed lines, duplicate workers, missing session), `classify` (every rule above), target validation (rejects `-x`, `--pdb`, newlines, empty), command building, config loader for `test_timeout_s`, new error code.
3. Docker plus internet (module-scoped sandbox set up once, network cut, then a fresh project written into the repo for each test):
   - mixed outcomes with exact counts and IDs; all-pass; selecting one file or one node ID
   - repo `addopts` respected (`-k`), usage error from an unknown option gives `collection_error`, import error gives `collection_error` with the message
   - no tests gives `no_tests` and `ensure_has_tests` raises; collect-only lists IDs
   - timeout keeps partial results and the sandbox keeps working
   - stale results never leak between runs; plugin and report are outside the repo
   - corrupted plugin gives `crashed`, not a wrong result
   - tests that try the network fail (the network is cut)
   - pytest pinned to 7.4.4 works with the plugin
   - end to end on `pallets/itsdangerous` at a pinned commit: setup then `run_tests`, all pass
4. Confirm `uv run pytest` passes with Docker unreachable and without internet.

## 6. Docs and wrap-up

1. Add AD-036 to AD-039 to `specs/decisions.md` (written with the specs). Tick P6 in `specs/roadmap.md`.
2. README: how test results are captured and what the statuses mean.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked.
