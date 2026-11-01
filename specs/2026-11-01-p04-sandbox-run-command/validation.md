# Validation: Sandbox, Run a Command (Roadmap P4)

The work can be merged when every item below is true.

## Automated (no Docker needed)

- [ ] `uv run pytest` passes with Docker **stopped**: docker tests show as skipped with a clear reason, none fail, and the earlier 187 tests still pass.
- [ ] `SandboxConfig` defaults equal: image `python:3.11-slim`, 1 CPU, 2048 MB, 256 pids, 120 s timeout, 1 MiB output cap, 1800 s lifetime, 1024 MB workspace.
- [ ] `load_sandbox_config` covers and passes: no `sandbox:` section gives defaults; partial section fills the rest from defaults; unknown key, wrong type, zero, and negative values raise `ConfigError` naming the field; the shipped `config/app.yaml` loads.
- [ ] Existing `load_app_config` still accepts the updated `config/app.yaml`.
- [ ] `SandboxError` codes are stable and covered in `tests/test_errors.py`.

## Automated (Docker running)

- [ ] `uv run pytest -m docker` passes with zero failures.
- [ ] Commands: echo returns stdout and exit 0; a failing command returns its exit code and stderr; command-not-found returns exit 127 without raising.
- [ ] Timeout: `sleep 30` with a 2 s timeout gives `timed_out=True`, returns within a few seconds, and the sandbox still runs the next command.
- [ ] After a timeout, leftover child processes are gone.
- [ ] Output above the cap is truncated and `truncated=True`; output at or below the cap is untouched.
- [ ] Files written in `/workspace` persist between `run` calls.
- [ ] Isolation:
  - [ ] runs as uid 1000, not root
  - [ ] `NoNewPrivs` is 1 and effective capabilities are empty
  - [ ] host environment variables (set by the test) are not visible inside
  - [ ] no Docker socket in the container
  - [ ] by default a network connection attempt fails; with `network=True` a network interface exists
- [ ] Limits: container `HostConfig` shows the configured CPU, memory, swap (equal to memory), and pids values; a memory hog is killed under a small memory limit; a bounded fork loop is stopped by a small pids limit.
- [ ] Cleanup: after `close()`, after an exception inside `with`, and after a failed `start`, no container with the `bugbite.sandbox` label remains; calling `close()` twice is safe.
- [ ] `run` after `close` raises `sandbox_closed`.
- [ ] An unreachable Docker (bad `DOCKER_HOST`) raises `docker_unavailable` with a hint to start Docker.

## Manual checks

- [ ] `docker ps -a --filter label=bugbite.sandbox=1` is empty after the full test run.
- [ ] `git grep -n "docker.sock\|volumes\|binds" src/` shows no host mounts or socket use.
- [ ] `git grep -n "os.environ" src/bugbite/sandbox` returns nothing (no host environment copied).
- [ ] Only the `docker` package (and its own dependencies) was added to `pyproject.toml` / `uv.lock`.
- [ ] Error messages read clearly to a non-developer (spot check by hand).

## Docs and process

- [ ] `specs/decisions.md` has AD-022 to AD-028 with reasons.
- [ ] `specs/roadmap.md` has P4 ticked.
- [ ] README development setup explains Docker tests and how to skip them.
- [ ] Commits are small and logical on branch `2026-11-01-p04-sandbox-run-command`.
- [ ] No files outside this phase's scope were changed (no clone, install, pytest-in-container, or agent code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and stopped, and the branch is ready for review and merge into `main`.
