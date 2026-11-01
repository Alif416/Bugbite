# Plan: Sandbox, Run a Command (Roadmap P4)

Branch: `2026-11-01-p04-sandbox-run-command`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-022 onward).

## 1. Dependency, config, and errors

1. Add the `docker` (Docker SDK for Python) package to `pyproject.toml` and refresh `uv.lock`.
2. Add a `SandboxConfig` frozen dataclass in `src/bugbite/config.py` with defaults:
   `image="python:3.11-slim"`, `cpus=1`, `memory_mb=2048`, `pids_limit=256`, `command_timeout_s=120`, `max_output_bytes=1_048_576`, `max_lifetime_s=1800`, `workspace_mb=1024`.
3. Add `load_sandbox_config(path)`: reads the optional `sandbox:` section of `config/app.yaml`, fills missing fields from the defaults, and rejects unknown keys, wrong types, and zero or negative values with a clear `ConfigError`.
4. Add a `sandbox:` section to `config/app.yaml` showing the defaults.
5. Add `SandboxError(code, message)` to `src/bugbite/errors.py` with codes `docker_unavailable`, `image_unavailable`, `start_failed`, `exec_failed`, `sandbox_closed`, `backstop_timeout`.

## 2. Sandbox container lifecycle

1. Create `src/bugbite/sandbox/container.py` with `Sandbox(config, *, network=False, job_id=None)`.
2. `start()`:
   - connect to Docker; if the daemon is unreachable raise `docker_unavailable` with a hint to start Docker
   - make sure the image exists locally, pulling it if missing; failure raises `image_unavailable`
   - create and start one container with: `sleep <max_lifetime_s>` as the keep-alive process (so a forgotten container expires by itself), labels `bugbite.sandbox=1` and `bugbite.job=<id>`, `network_mode="none"` unless `network=True`, `nano_cpus`, `mem_limit` with `memswap_limit` equal to it (no swap), `pids_limit`, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`, non-root user `1000:1000`, working dir `/workspace`, a size-limited `tmpfs` at `/workspace` owned by that user
   - no host mounts, no Docker socket, and no environment variables copied from the host
3. `close()`: force-remove the container; safe to call twice; swallow "already gone".
4. Support `with Sandbox(...) as sb:` so cleanup runs even when the body raises. Calling `run` after close raises `sandbox_closed`.

## 3. Running a command

1. `run(command, *, timeout=None) -> CommandResult` with frozen dataclass `CommandResult(exit_code, stdout, stderr, timed_out, duration_s, truncated)`.
2. `command` is a list of arguments (no shell) or a string run with `sh -c`; document which.
3. Run inside the container via the low-level exec API, wrapped in the in-container `timeout --kill-after=2 <seconds>` so the whole process group is killed on expiry. Exit codes 124 and 137 from the wrapper set `timed_out`.
4. Stream output and keep at most `max_output_bytes` each for stdout and stderr; keep draining past the cap but discard, and set `truncated`.
5. Host-side backstop: if the exec has not returned within `timeout + 15` seconds, kill the container and raise `backstop_timeout`.
6. A command that is not found returns its shell exit code (127) and stderr as a normal result, not an exception.
7. Decode output as UTF-8 with replacement for invalid bytes.

## 4. Orphan labelling helper

1. Add `list_sandbox_containers()` returning containers with the `bugbite.sandbox` label, used by tests to prove cleanup. Full orphan sweeping is P7.

## 5. Tests

1. Unit tests (no Docker): `SandboxConfig` defaults and validation, `load_sandbox_config` with and without a `sandbox:` section, unknown keys, bad values, `SandboxError` codes.
2. Docker integration tests in `tests/sandbox/` marked `@pytest.mark.docker`, skipped with a clear reason when no daemon is reachable (and register the marker in `pyproject.toml`):
   - echo returns stdout and exit 0; non-zero exit code and stderr are captured
   - command-not-found gives exit 127, no exception
   - timeout: `sleep 30` with a 2 s timeout gives `timed_out`, returns quickly, and the sandbox still works afterwards
   - leftover child processes are killed after a timeout
   - output cap: a command printing more than the cap is truncated and flagged
   - state persists between runs in `/workspace`
   - isolation: runs as uid 1000; `NoNewPrivs` is 1 and effective capabilities are empty; the host's environment variables are not visible; no Docker socket; no network (a connection attempt fails); with `network=True` the container has a network interface
   - limits: `HostConfig` shows the configured CPU, memory, swap, and pids values; a memory hog is killed under a small limit; a bounded fork loop is stopped by a small pids limit
   - cleanup: after `close()` and after an exception inside `with`, no labelled container remains; `close()` twice is safe
   - `run` after close raises `sandbox_closed`
   - unreachable Docker (bad `DOCKER_HOST`) raises `docker_unavailable`
3. Confirm the default `uv run pytest` still passes when Docker is not running (docker tests skipped, not failed).

## 6. CI, docs, and wrap-up

1. Update `.github/workflows/ci.yml` only if needed. `ubuntu-latest` already has Docker, so the docker tests run there; pre-pull the image in a step to keep timing steady.
2. Add a short "Docker tests" note to the README development setup (Docker must be running; how to run `-m docker` or skip them with `-m "not docker"`).
3. Add AD-022 to AD-028 to `specs/decisions.md` (written with the specs). Tick P4 in `specs/roadmap.md`.
4. Commit in small logical commits, then merge into `main` with `--no-ff` when asked.
