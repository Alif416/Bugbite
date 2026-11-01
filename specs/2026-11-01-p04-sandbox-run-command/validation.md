# Validation: Sandbox, Run a Command (Roadmap P4)

The work can be merged when every item below is true.

## Automated (no Docker needed)

- [x] `uv run pytest` passes with Docker **stopped**: docker tests show as skipped with a clear reason, none fail, and the earlier 187 tests still pass (checked with a dead DOCKER_HOST: 233 passed, 35 skipped).
- [x] `SandboxConfig` defaults equal: image `python:3.11-slim`, 1 CPU, 2048 MB, 256 pids, 120 s timeout, 1 MiB output cap, 1800 s lifetime, 1024 MB workspace.
- [x] `load_sandbox_config` covers and passes: no `sandbox:` section gives defaults; partial section fills the rest from defaults; unknown key, wrong type, zero, and negative values raise `ConfigError` naming the field; the shipped `config/app.yaml` loads.
- [x] Existing `load_app_config` still accepts the updated `config/app.yaml`.
- [x] `SandboxError` codes are stable and covered in `tests/test_errors.py`.

## Automated (Docker running)

- [x] `uv run pytest -m docker` passes with zero failures.
- [x] Commands: echo returns stdout and exit 0; a failing command returns its exit code and stderr; command-not-found returns exit 127 without raising.
- [x] Timeout: `sleep 30` with a 2 s timeout gives `timed_out=True`, returns within a few seconds, and the sandbox still runs the next command.
- [x] After a timeout, leftover child processes are gone.
- [x] Output above the cap is truncated and `truncated=True`; output at or below the cap is untouched.
- [x] Files written in `/workspace` persist between `run` calls.
- [x] Isolation:
  - [x] runs as uid 1000, not root
  - [x] `NoNewPrivs` is 1 and effective capabilities are empty
  - [x] host environment variables (set by the test) are not visible inside
  - [x] no Docker socket in the container
  - [x] by default a network connection attempt fails; with `network=True` a network interface exists
- [x] Limits: container `HostConfig` shows the configured CPU, memory, swap (equal to memory), and pids values; a memory hog is killed under a small memory limit; a bounded fork loop is stopped by a small pids limit.
- [x] Cleanup: after `close()`, after an exception inside `with`, and after a failed `start`, no container with the `bugbite.sandbox` label remains; calling `close()` twice is safe.
- [x] `run` after `close` raises `sandbox_closed`.
- [x] An unreachable Docker (bad `DOCKER_HOST`) raises `docker_unavailable` with a hint to start Docker.

## Manual checks

- [x] `docker ps -a --filter label=bugbite.sandbox=1` is empty after the full test run.
- [x] `git grep -n "docker.sock\|volumes\|binds" src/` shows no host mounts or socket use.
- [x] `git grep -n "os.environ" src/bugbite/sandbox` returns nothing (no host environment copied).
- [x] Only the `docker` package (and its own dependencies) was added to `pyproject.toml` / `uv.lock`.
- [x] Error messages read clearly to a non-developer (spot check by hand).

## Docs and process

- [x] `specs/decisions.md` has AD-022 to AD-029 with reasons.
- [x] `specs/roadmap.md` has P4 ticked.
- [x] README development setup explains Docker tests and how to skip them.
- [x] Commits are small and logical on branch `2026-11-01-p04-sandbox-run-command`.
- [x] No files outside this phase's scope were changed (no clone, install, pytest-in-container, or agent code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and stopped, and the branch is ready for review and merge into `main`.
