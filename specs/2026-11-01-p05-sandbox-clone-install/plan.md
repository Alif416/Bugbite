# Plan: Sandbox Clone and Install (Roadmap P5)

Branch: `2026-11-01-p05-sandbox-clone-install`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-030 onward).

## 1. Sandbox image

1. Add `docker/sandbox.Dockerfile`: `python:3.11-slim` plus `git` and `ca-certificates` (no recommends, apt lists cleaned). Create `/workspace` owned by `1000:1000` (an anonymous volume inherits this ownership). Set `HOME=/workspace/.home`, `PIP_CACHE_DIR=/workspace/.cache/pip`, `PIP_DISABLE_PIP_VERSION_CHECK=1`, `GIT_TERMINAL_PROMPT=0`.
2. Add `ensure_sandbox_image()` in `src/bugbite/sandbox/image.py`: if the configured image is Bugbite's own tag (`bugbite-sandbox:py3.11-1`) and is missing locally, build it from the Dockerfile; any other image is pulled as before. The tag carries a version suffix that is bumped whenever the Dockerfile changes.
3. Change the default `SandboxConfig.image` to `bugbite-sandbox:py3.11-1`. Add `setup_timeout_s` (default 900) to `SandboxConfig`, the loader, and `config/app.yaml`. Change `workspace_mb` default to 2048 and document it as a soft cap.

## 2. Disk-backed workspace and soft size cap

1. Replace the `/workspace` tmpfs with an anonymous Docker volume (removed with the container via `v=True`).
2. Add `Sandbox.workspace_usage_mb()` (runs `du -sm /workspace` inside) and `Sandbox.check_workspace()` which raises `SandboxError("workspace_full")` when usage exceeds `workspace_mb`. Add `workspace_full` to the sandbox error codes.
3. Update the P4 tests and P4 notes that assumed a tmpfs (workspace-size test, `Tmpfs` inspection, default values).

## 3. Network on for setup, then cut

1. `Sandbox(network=True)` keeps starting the container on the default bridge network.
2. Add `Sandbox.disconnect_network()`: disconnects the container from every network it is attached to, idempotently. Add `Sandbox.has_network` (read from Docker, not remembered).
3. Setup always cuts the network in a `finally`, whether setup succeeded or failed.

## 4. Clone

1. Create `src/bugbite/sandbox/setup.py`.
2. `clone_repo(sandbox, clone_url, ref=None)`: run `git clone --depth 1` into `/workspace/repo` using list-form arguments (no shell). With a `ref`, validate it (a 7 to 40 character hex commit, or a branch or tag name made of letters, digits, `.`, `_`, `-`, `/`, not starting with `-`), then `git init`, `git fetch --depth 1 origin <ref>`, `git checkout FETCH_HEAD`.
3. Disable submodule recursion and the `ext` protocol; never place credentials in the URL or environment. Private repos are out of scope (see `requirements.md`).
4. Record the resolved commit with `git rev-parse HEAD`.
5. `repo_clone_url(RepoRef)` builds `https://github.com/<owner>/<name>.git` from the validated reference.

## 5. Install

1. `plan_install(files)`: a pure function from the set of top-level file names to an ordered list of install steps (testable without Docker):
   - always: create the virtual environment `/workspace/.venv`
   - if `pyproject.toml`, `setup.py`, or `setup.cfg` exists: `pip install -e ".[test,tests,testing]"` (pip only warns about extras that do not exist), with `pip install -e .` as the fallback if that fails
   - if there is no packaging file but `requirements.txt` exists: `pip install -r requirements.txt` (required)
   - if `pyproject.toml` declares PEP 735 `[dependency-groups]`, install the test-like ones (`test`, `tests`, `testing`, else `dev`) with `pip install --group`, preceded by an optional `pip>=25.1` upgrade (AD-035)
   - optional test requirements (`requirements-dev.txt`, `requirements-test.txt`, `requirements_test.txt`, `test-requirements.txt`, `dev-requirements.txt`): installed best effort; failure is a warning
   - finally: install `pytest` only if it is not already importable, so repo pins are not overridden
2. Each step runs with `setup_timeout_s` and is recorded as `StepResult(name, command, exit_code, duration_s, timed_out, output_tail, required, ok)`; the tail keeps the last 2,000 characters of combined output.
3. `setup_workspace(sandbox, clone_url, ref=None) -> SetupResult` runs clone, install, and the workspace size check, stops at the first failed required step, and always cuts the network at the end. `SetupResult(ok, head_commit, steps, warnings, workspace_mb, failure_reason)` where `failure_reason` is one of `clone_failed`, `install_failed`, `pytest_unavailable`, `setup_timeout`, `workspace_full`, or `None`.
4. `setup_repo(sandbox, repo_ref, ref=None)` is the public convenience that builds the clone URL from a `RepoRef`.
5. Setup failures are results, not exceptions; exceptions stay for infrastructure problems (Docker down, sandbox closed).

## 6. Tests

1. Offline unit tests: `plan_install` for each file combination; ref validation (accepts hashes, branches, tags; rejects leading dash, spaces, shell characters, empty); clone URL builder; config loader additions.
2. Docker integration tests (`docker` marker), repos created inside the container so GitHub is not needed:
   - the image has `git`, and `/workspace` is a volume (not tmpfs), owned by uid 1000
   - volume is removed with the container (no dangling volume left)
   - `disconnect_network()` removes `eth0` and routes and is idempotent; connections fail afterwards
   - workspace soft cap raises `workspace_full`
   - setup on a local repo: clone, venv, install, pytest available, `git diff` works, network cut afterwards
   - requirements-only repo; packaging repo with the extras fallback; repo with nothing to install; repo whose install fails (bad requirement) gives `install_failed` with an output tail; install timeout gives `setup_timeout`; network is cut in every case
   - ref checkout of a specific commit
3. Tests that need the internet (`internet` marker, skipped when pypi.org is unreachable): the pip installs above, and one real clone of `octocat/Hello-World` pinned to a commit through `setup_repo`.
4. Confirm `uv run pytest` still passes with Docker unreachable (docker and internet tests skipped with reasons).

## 7. Docs and wrap-up

1. Add AD-030 to AD-035 to `specs/decisions.md` (written with the specs) and mark AD-026 as superseded in part.
2. README: how the image is built on first use, and the `internet` marker.
3. Update CI to build the image up front. Tick P5 in `specs/roadmap.md`; add "prune dangling workspace volumes" to P7.
4. Commit in small logical commits, then merge into `main` with `--no-ff` when asked.
