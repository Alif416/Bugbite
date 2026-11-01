# Requirements: Orphan-Proof Cleanup (Roadmap P7)

## Goal

Make sure a crashed or killed job never leaves containers or workspace volumes behind, and that cleanup can never remove a sandbox a live job is still using. This delivers the README reliability rule "a crashed job must not leave orphan containers" (NFR Reliability) and FR2.5 (clean up the container after each job), and completes the sandbox foundation (P4 to P7) before the agent runs in it.

## Scope

**In:**
- Docker auto-removal of sandbox containers and their anonymous volumes when they exit
- Ownership and age labels on containers and workspace volumes
- A pure, tested orphan decision rule (dead owner, outlived lifetime, other hosts, legacy containers)
- `sweep_orphans()`: removes orphaned containers and leftover labelled volumes, returns a report
- Automatic sweep before each sandbox start (never blocks the start) and on demand
- `atexit` cleanup of live sandboxes, and opt-in `install_signal_cleanup()` for entry points
- Clear `sandbox_closed` error when a sandbox expired
- Tests that really kill a process mid-job

**Out (later phases):**
- A `bugbite cleanup` CLI command (P45) and calling the sweeper from the job manager (P66)
- Pruning volumes created before this phase (they carry no label, so they cannot be told apart from other programs' volumes)
- Disk quotas, sandbox pools, and concurrency limits (P50)
- Removing images, or cleaning anything outside Bugbite's own labels
- Cleanup of cloud or remote Docker hosts beyond what the Docker API already reaches

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Layers | Docker auto-remove + sweeper + exit hooks | Defense in depth; the owner's choice (AD-040, AD-044) |
| Sweep timing | Before each sandbox start, and callable on demand | Crashes heal themselves; the owner's choice (AD-042) |
| Orphan rule | Owner process gone, or outlived lifetime + 60 s grace | Never touches a live job; the owner's choice (AD-041) |
| Exit hooks | `atexit` automatic; signal handlers opt-in | A library should not take over global signal handling; the owner's choice (AD-044) |
| Volumes | Labelled at creation; removed when old and unreferenced | Safe against other programs' volumes (AD-043) |

See `specs/decisions.md` AD-040 to AD-044.

## Context

- README: NFR Reliability ("A crashed job must not leave orphan containers"), FR2.5, section 6 Safety. Roadmap P7 also asks to prune leftover workspace volumes (AD-033).
- Current behaviour (P4 to P6): `close()` and `with` blocks remove the container and volume; a killed process leaves the container running until the 30-minute `sleep` ends, after which it stays behind stopped, with its workspace volume (hundreds of MB for real repos).
- Parallel workers arrive in P50. The sweeper must therefore be safe to run while other worker processes hold live sandboxes.
- Docker creates the container's anonymous volume together with the container, and `auto_remove` (like `docker run --rm`) removes both when the container exits.
- Process ids can be reused by the operating system, so the owner label includes a process start token.

## Constraints

- The sweeper only ever touches objects carrying the Bugbite label; never other containers or volumes.
- It must never remove a sandbox whose owner process is alive and within its lifetime.
- A sweeper failure must never stop a job from starting.
- Signal handlers are never installed on import; only by an explicit call, from the main thread.
- Tests must clean up after themselves, including child processes they start.
- Default `uv run pytest` must pass with Docker unreachable.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Calling the sweeper at job-manager startup and exposing `bugbite cleanup` are left to P45 and P66.
- If Bugbite later runs on several machines against one shared Docker host, hostname alone may not identify an owner; revisit then.
- Orphaned unlabelled workspace volumes from before this phase must be removed by hand (`docker volume ls -f dangling=true`); the README says how.
- Output of a container that exits immediately is no longer available for the error message, because Docker removes it at once (AD-040).

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-040 to AD-044).

## Findings from the build (2026-11-01)

- A first by-hand `kill -9` test killed only the `uv run` wrapper, leaving the Python owner alive; the sweeper correctly kept the sandbox. Redone against the real Python process: the container stayed up after the kill (the problem), and `sweep_orphans()` removed the container and its volume.
- One P5 internet test (`test_optional_test_requirements_failure_is_a_warning`) failed once in a full run and passed in the five runs after it, so the cause is unknown. It does a real `pip install` from PyPI through Docker's network; a transient network problem is the likeliest cause but is not proven. The internet tests now print the failing step's output in their assertion messages so a recurrence can be diagnosed.
