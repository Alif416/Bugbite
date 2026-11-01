# Validation: Orphan-Proof Cleanup (Roadmap P7)

The work can be merged when every item below is true.

## Automated (no Docker)

- [ ] `uv run pytest` passes with Docker **unreachable**: Docker tests are skipped with visible reasons, none fail, and all earlier tests still pass.
- [ ] `is_orphan` covers and passes: live owner young (kept) and older than lifetime plus grace (orphan); dead owner (orphan, even when young); start-token mismatch (orphan); other host young (kept) and old (orphan); legacy container without labels judged by Docker's creation time; unreadable labels; negative age from clock skew; grace boundary exactly equal (kept) and one second over (orphan).
- [ ] `owner_alive` is true for the current process, false for a finished process, and false when the start token differs for the same process id; unknown when `ps` is unavailable but the process id exists.
- [ ] Labels: building and parsing round-trip; malformed values do not raise.
- [ ] The live-sandbox registry adds on start and removes on close; `close_all_sandboxes` closes every registered sandbox even if one fails.
- [ ] `install_signal_cleanup` skips ignored signals, raises outside the main thread, and its `uninstall` restores the previous handlers.

## Automated (Docker running)

- [ ] **Killed owner:** a child process starts a sandbox and kills itself with `SIGKILL`. Before the sweep the container still exists; after `sweep_orphans()` the container and its volume are both gone, and the report names them.
- [ ] **Normal exit without closing:** the container and volume are gone after the child exits.
- [ ] **SIGTERM and SIGINT** with `install_signal_cleanup` installed: container and volume gone; the child ends by the signal (SIGTERM) or with `KeyboardInterrupt` (SIGINT).
- [ ] **Expiry:** a sandbox with a 5-second lifetime disappears by itself with its volume; `run` afterwards raises `sandbox_closed` with a clear message; `close()` afterwards is safe.
- [ ] **Live owners are safe:** `sweep_orphans()` never removes a sandbox owned by the current process, nor one owned by a live waiting child, even with `grace_s=0` while still within its lifetime.
- [ ] **Sweep at start:** an orphan owned by a dead process is removed when a new sandbox starts; a sweeper that raises does not stop the start and logs a warning.
- [ ] **Other host:** a young container from another host is kept; one older than lifetime plus grace is removed.
- [ ] **Volumes:** an old unreferenced labelled volume is removed; a volume used by a running container is kept; an unlabelled volume is never touched; volumes younger than the grace period are kept.
- [ ] Immediate-exit image still gives `start_failed` with a message that explains why its output is unavailable.
- [ ] Existing sandbox, setup, and test-run tests still pass unchanged (auto-removal does not break them).
- [ ] After the full run: no labelled containers and no labelled volumes remain; no child processes are left running.

## Manual checks

- [ ] `docker ps -a --filter label=bugbite.sandbox=1` and `docker volume ls --filter label=bugbite.sandbox=1` are empty after the full test run.
- [ ] Start a sandbox in a terminal, press Ctrl-C in a script that called `install_signal_cleanup`, and confirm the container disappears (done by hand once).
- [ ] Start a sandbox from a script, `kill -9` the script, run `sweep_orphans()` by hand, and read the report (done by hand once; output noted below).
- [ ] `git grep -n "signal.signal" src/` shows it only inside `install_signal_cleanup` (no handlers on import).
- [ ] `git grep -n "volumes.prune\|containers.prune\|system prune" src/` returns nothing (no blanket prune; removal is by Bugbite label only).
- [ ] Report and error messages read clearly to a non-developer (spot check).

## Docs and process

- [ ] `specs/decisions.md` has AD-040 to AD-044 with reasons.
- [ ] `specs/roadmap.md` has P7 ticked.
- [ ] README explains cleanup, `sweep_orphans()`, `install_signal_cleanup()`, and removal of pre-P7 volumes by hand.
- [ ] Commits are small and logical on branch `2026-11-01-p07-orphan-cleanup`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no CLI, agent, or job manager code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch is ready for review and merge into `main`.
