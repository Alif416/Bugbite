# Requirements: Sandbox, Run Tests (Roadmap P6)

## Goal

Run a repo's pytest suite inside the sandbox and return a precise, structured result: the exact ID and outcome of every test, a clear overall status, and the output for evidence. This is the measuring instrument for the rest of the project: the baseline run before a fix, the reproduction test, the post-fix run, and regression detection all depend on it (FR6.1, FR6.2, FR6.3, FR4.2). It also rejects repos that have no tests, moved here from P3.

## Scope

**In:**
- A small pytest plugin, shipped with Bugbite and kept outside the repo, that records per-test outcomes as JSON lines
- `run_tests` (whole suite or chosen files and test IDs), `collect_tests`, and `ensure_has_tests`
- Outcomes `passed`, `failed`, `error`, `skipped`, `xfailed`, `xpassed` keyed by exact pytest node ID
- Run statuses `ok`, `no_tests`, `collection_error`, `timeout`, `crashed`, each with a human-readable reason
- Partial results kept when a run times out or crashes
- `test_timeout_s` config (default 300 s) and a kept output tail for evidence
- Small sandbox additions: `write_file` and per-command `env`
- Rejection of repos with no tests (`InputError` code `no_tests`)
- Offline plugin tests using the host's pytest, plus Docker and internet tests

**Out (later phases):**
- Comparing baseline and post-fix results, regression logic (P31, P32)
- Verifier-owned checks that a reproduction test fails before and passes after (P33)
- Skip/xfail cheating detection (P35)
- Agent `run_tests` tool wrapper (P15)
- Flaky-test detection and repeated runs
- Parallel execution (`xdist` is tolerated if the repo uses it, not required)
- Per-test timeouts; coverage

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Result capture | Small pytest plugin outside the repo, JSON lines | Exact node IDs, full outcome set, survives timeouts, works across pytest versions (AD-036) |
| Statuses | `ok`, `no_tests`, `collection_error`, `timeout`, `crashed` | Maps to failure labels; import and usage errors are environment problems, not "no tests" (AD-037) |
| Repo config | Respected; only our own flags added | Run the suite the way the project does (AD-038) |
| Time limit | `test_timeout_s`, 300 s | Fits the 10-minute median job target (AD-038) |
| Trust | Results are as honest as the repo code running in pytest; tamper resistance comes from the verifier in P33 | Be explicit about what P6 does and does not guarantee (AD-039) |

See `specs/decisions.md` AD-036 to AD-039.

## Context

- README: FR6.1 to FR6.3 (run the reproduction test, run the full suite and compare against a baseline, report regressions), FR4.2 (confirm a test fails for the right reason, not a syntax error or missing import: the `error` and `collection_error` outcomes make that distinguishable), FR5.7 (run the named failing test directly), FR11 labels ("environment or dependency setup failed", "bad or missing reproduction test"), scope line "Python repositories with an existing test suite", and the risk "Environment setup fails on many repos".
- Mission principles: evidence over opinion (results come from real pytest output, not the model), honesty over success (a failed collection is reported as such), enforce in code.
- Builds on P5: `SetupResult` leaves a venv with pytest at `/workspace/.venv` and the repo at `/workspace/repo`, with the network already cut. Tests therefore run offline; tests that need the internet will fail, which is recorded as-is and handled by baseline comparison later.
- pytest exit codes: 0 all passed, 1 some failed, 2 interrupted (including collection errors), 3 internal error, 4 usage error (including options from `addopts` that name a missing plugin), 5 no tests collected.
- Plugin source must stay compatible with old pytest versions because benchmark repos pin old ones.

## Constraints

- The plugin and its report live outside the repo (`/workspace/.bugbite`) so they never appear in `git diff`.
- The plugin is rewritten and the report deleted before every run, so stale results cannot be mistaken for new ones.
- Targets can never be read as pytest options (no leading `-`); commands use list-form arguments, never a shell with repo or model text.
- Default `uv run pytest` must pass with Docker unreachable and without internet (those tests skip with reasons); the plugin and parser tests run anywhere.
- Tests must not leave containers or volumes behind.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Tamper resistance (a malicious `conftest.py` that fakes the report, or edits to the plugin file) is deliberately left to the verifier (P33), which will re-run in a clean container; recorded as a known gap.
- Repos whose `addopts` need unavailable plugins fail as `collection_error`; whether to retry without `addopts` is left for the failure-analysis phases.
- Large suites (tens of thousands of tests) produce large reports; revisit if a chosen benchmark repo needs it.
- The workspace size is not re-checked after test runs; later phases call `check_workspace()` where needed.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-036 to AD-039).

## Findings from manual runs (2026-11-01)

- `pallets/itsdangerous` (flit, dependency groups): setup ok, 297 tests pass.
- `psf/requests` (setup.py, `requirements-dev.txt`, dependency group `test`): setup ok in 26 s; 615 passed, 4 failed, 15 skipped, 1 xfailed in 78 s. The 4 failures are timeout tests that connect to `10.255.255.1`: they need a network, which is cut, so they would also fail in a baseline run.
- `kjd/idna` (flit): setup ok, but the run is `collection_error` because `hypothesis` is declared only in an `all` extra and in CI lock files (`.github/requirements/`), which the install heuristic does not read. The failure is reported correctly and names the missing module. Left as a known limitation of the heuristic (AD-032, AD-035).
