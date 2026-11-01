# Plan: Orphan-Proof Cleanup (Roadmap P7)

Branch: `2026-11-01-p07-orphan-cleanup`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-040 onward).

## 1. Let Docker remove sandboxes by itself

1. Create containers with `auto_remove=True`, so Docker deletes the container and its anonymous workspace volume the moment it exits (normal expiry after `max_lifetime_s`, kill, or crash of the keep-alive process).
2. Handle the side effects:
   - in `_check_ready`, a container that exited at once is already gone: treat `NotFound` as "exited right after starting" and say its output is unavailable because Docker removes exited sandboxes
   - in `run`, a `NotFound` from Docker means the sandbox expired or was removed: mark the sandbox closed and raise `sandbox_closed` with a clear message instead of a raw Docker error
   - `close()` already treats `NotFound` as success; keep it that way
3. Label the workspace volume too: `Mount(..., labels=...)` with the same Bugbite labels.

## 2. Ownership labels

1. Create `src/bugbite/sandbox/cleanup.py` with `Owner(host, pid, started)` and `current_owner()`:
   - `host`: the machine's hostname
   - `pid`: the current process id
   - `started`: a process start token read with `ps -o lstart= -p <pid>` (works on macOS and Linux), so a reused process id is not mistaken for the original owner; an empty token if `ps` is unavailable
2. Add labels to every container and volume: `bugbite.sandbox=1`, `bugbite.job`, `bugbite.owner_host`, `bugbite.owner_pid`, `bugbite.owner_started`, `bugbite.created` (epoch seconds), `bugbite.max_lifetime` (seconds).
3. Add an optional `owner` argument to `Sandbox` so tests can create containers that look like they belong to another process or host.

## 3. The orphan decision (pure function)

1. `is_orphan(labels, status, docker_created, now, grace_s=60, local_owner_alive=...)` returns `(True/False, reason)` using these rules:
   - labels missing or unreadable (containers made before P7): judge by Docker's own creation time and the default lifetime
   - owner on this host: if the owner process is gone (or its start token differs), it is an orphan immediately; if the owner is alive, it is an orphan only when older than `max_lifetime + grace_s`
   - owner on another host: orphan only when older than `max_lifetime + grace_s`
   - a negative age (clock skew) is treated as age zero
2. `owner_alive(owner)` checks the process id with `os.kill(pid, 0)` and compares the start token when both are known.

## 4. The sweeper

1. `sweep_orphans(client=None, *, grace_s=60) -> SweepReport` lists containers with the `bugbite.sandbox=1` label, removes the orphans with `force=True` and `v=True`, and records what it removed and what it left alone with the reason.
2. Then remove leftover volumes: list volumes with the label, skip those younger than `grace_s`, and try to remove each one; Docker refuses volumes still in use, which are skipped. Volumes without our label are never touched.
3. Failures on a single item are recorded in the report and do not stop the sweep.
4. `Sandbox.start()` runs the sweeper first. A sweeper failure is logged as a warning and never blocks starting.

## 5. Exit hooks

1. Keep a registry of live sandboxes (weak references, guarded by a lock); `start()` adds and `close()` removes.
2. `close_all_sandboxes()` closes every registered sandbox, ignoring individual errors; register it with `atexit` once.
3. `install_signal_cleanup(signals=(SIGTERM, SIGINT)) -> uninstall`: opt-in, main thread only. On a signal it closes all sandboxes, restores the previous handler, and lets that handler run (so `SIGINT` still raises `KeyboardInterrupt` and `SIGTERM` still ends the process). Signals that are currently ignored are left alone.

## 6. Tests

1. Offline unit tests: every `is_orphan` rule (live owner young/old, dead owner, token mismatch, other host young/old, legacy labels, clock skew, grace edges); label building and parsing; `owner_alive` for the current process, a finished process, and a reused-pid token mismatch; the registry and `close_all_sandboxes` with fake sandboxes; signal installer argument handling (ignored signal skipped, non-main-thread error).
2. Docker tests with real crashes, using child processes:
   - **killed owner**: a child starts a sandbox and kills itself with `SIGKILL`; the container is still there before the sweep and gone, with its volume, after `sweep_orphans()`
   - **normal exit without closing**: container gone after the child exits (atexit)
   - **SIGTERM and SIGINT** with `install_signal_cleanup`: container gone, child ends by the signal or `KeyboardInterrupt`
   - **expiry**: a sandbox with a 5-second lifetime disappears by itself, with its volume, and `run` afterwards raises `sandbox_closed`
   - **live owners are safe**: a sweep in one process never removes a sandbox owned by a live process (itself, or a waiting child)
   - **sweeper at start**: an orphan from a dead owner is removed when a new sandbox starts; a failing sweeper does not stop the start
   - **other host**: young is kept, old is removed
   - **volumes**: an old unreferenced labelled volume is removed, an in-use one is kept, an unlabelled volume is untouched
   - the immediate-exit image still gives `start_failed`
3. Confirm `uv run pytest` passes with Docker unreachable (docker tests skip) and that no containers or volumes remain after the full run.

## 7. Docs and wrap-up

1. Add AD-040 to AD-044 to `specs/decisions.md` (written with the specs). Tick P7 in `specs/roadmap.md`.
2. README: how cleanup works, the `sweep_orphans()` and `install_signal_cleanup()` helpers, and the limit that volumes created before P7 carry no label and are not touched.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked. Commit messages carry no co-author trailer.
