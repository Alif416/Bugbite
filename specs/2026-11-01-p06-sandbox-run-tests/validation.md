# Validation: Sandbox, Run Tests (Roadmap P6)

The work can be merged when every item below is true.

## Automated (no Docker, no internet)

- [ ] `uv run pytest` passes with Docker **unreachable** and no internet: Docker and internet tests are skipped with visible reasons, none fail, and all earlier tests still pass.
- [ ] Plugin tests (host pytest in a subprocess) cover and pass: passed, failed, skipped, xfailed, xpassed (non-strict), strict xpass as failed, setup error, teardown error, a failure not overwritten by a later pass, parametrized IDs including odd characters, tests in classes, `-k` deselection, collection error, no tests, and the collected count.
- [ ] The plugin keeps working when the report file is in a directory that already contains an old report (it appends only after `run_tests` deletes the old one; the plugin itself never truncates silently).
- [ ] `parse_report` tolerates blank and malformed lines (counted), duplicate and xdist worker lines, a missing `session` line, and unicode.
- [ ] `classify` covers every rule: timeout; exit 0 and 1 with a session line; exit 5 with nothing collected; collection errors; exit 4 usage error; exit 4 with the plugin name in the output; exit 3; missing session line; unknown exit code.
- [ ] Target validation rejects empty, `-x`, `--pdb`, `--rootdir=/`, newline and control characters, and accepts file paths, node IDs with brackets and quotes, and directories.
- [ ] `build_pytest_command` produces the documented command and contains no shell.
- [ ] `SandboxConfig.test_timeout_s` defaults to 300, is validated, and the shipped `config/app.yaml` loads; the `no_tests` error code is covered in `tests/test_errors.py`.
- [ ] `write_file` rejects relative paths and paths outside `/workspace`; `env` rejects invalid names.

## Automated (Docker and internet)

- [ ] Mixed outcomes: exact per-test IDs and outcomes, exact counts, overall status `ok`, exit code 1.
- [ ] All-pass suite: status `ok`, exit code 0.
- [ ] A single file and a single node ID can be selected; only those tests appear in the result.
- [ ] Repo `addopts` is respected (a `-k` filter in `addopts` limits the tests that run).
- [ ] An unknown option in `addopts` gives `collection_error` with a readable reason; an import error in a test module gives `collection_error` listing the module and message.
- [ ] No tests gives `no_tests`; `ensure_has_tests` raises `InputError` code `no_tests`; `collect_tests` lists the IDs of a normal suite.
- [ ] Timeout: `status="timeout"`, tests that finished before the stop are kept, the hanging test is absent, and the sandbox still runs commands afterwards.
- [ ] Two runs in a row with different tests never mix results (stale report removed).
- [ ] The plugin and report are outside the repo (nothing under `/workspace/repo` is created by them).
- [ ] A corrupted plugin file gives `crashed`, never a wrong `ok`.
- [ ] A test that opens a network connection fails (the network is cut).
- [ ] pytest pinned to 7.4.4 works with the plugin.
- [ ] End to end: `setup_repo` then `run_tests` on `pallets/itsdangerous` at a pinned commit gives `ok` with no failures.
- [ ] All Docker tests leave no labelled containers and no dangling volumes.

## Manual checks

- [ ] `docker ps -a --filter label=bugbite.sandbox=1` and `docker volume ls -f dangling=true` show nothing after the full run.
- [ ] `git grep -n "shell=True" src/` returns nothing; the only `sh -c` strings remain the fixed ones built from constants.
- [ ] The plugin file has no imports beyond the standard library (read it).
- [ ] Output tails and `reason` messages read clearly to a non-developer (spot check for each status).
- [ ] One hand run on a second real repo of a different style (not itsdangerous), with the result noted below.

## Docs and process

- [ ] `specs/decisions.md` has AD-036 to AD-039 with reasons.
- [ ] `specs/roadmap.md` has P6 ticked.
- [ ] README explains how results are captured and what each status means.
- [ ] Commits are small and logical on branch `2026-11-01-p06-sandbox-run-tests`.
- [ ] No files outside this phase's scope were changed (no baseline comparison, guards, or agent tools).

## Definition of done

All boxes ticked, tests green locally with Docker and internet available, and also green with Docker unreachable, and the branch is ready for review and merge into `main`.
