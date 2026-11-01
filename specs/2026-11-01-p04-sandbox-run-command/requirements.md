# Requirements: Sandbox, Run a Command (Roadmap P4)

## Goal

Provide the safe place where all untrusted code will run: start a resource-limited, network-less Docker container, run commands inside it with timeouts and output caps, and remove it afterwards. This is the foundation for cloning (P5), running tests (P6), and everything the agent does (FR2.1, FR2.3, FR2.4, FR2.5).

## Scope

**In:**
- `Sandbox` class using the Docker SDK for Python: start, run commands, close
- Resource limits: CPU, memory (no swap), process count, per-command timeout, output cap, workspace size, container lifetime
- Hardening: no network by default, non-root user, all capabilities dropped, `no-new-privileges`, no host mounts, no Docker socket, no host environment variables
- `CommandResult` with exit code, stdout, stderr, timed-out and truncated flags, duration
- Cleanup on normal exit, on exception, and by self-expiry of a forgotten container
- Labels so Bugbite containers can be found
- `sandbox:` section in `config/app.yaml` and a validated loader
- `SandboxError` with stable codes
- Docker integration tests that skip cleanly when Docker is not running

**Out (later phases):**
- Cloning a repo into the container and the network step it needs (P5)
- Installing dependencies (P5)
- Running pytest and parsing results (P6)
- Orphan sweeping after a crash (P7; P4 only labels containers and self-expires them)
- Agent tools that call the sandbox (P14, P15)
- Parallel containers and worker limits (P50)
- Custom per-repo images

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Docker access | Docker SDK for Python | Structured errors and exact limit settings; it is in the tech stack (AD-022) |
| Network | None by default, opt-in per container | Untrusted code must not reach the internet or host network (AD-023) |
| Default limits | 1 CPU, 2 GB RAM, 256 processes, 120 s per command; all configurable | The owner's choice; enough for most small suites (AD-024) |
| Container model | One long-lived container per job, many `exec` calls | Clone, install, and test need shared state (AD-025) |
| Hardening | Non-root, no capabilities, no-new-privileges, no host mounts, no env passthrough | Required by FR2.4 and mission principle 4 (AD-026) |
| Timeouts | In-container `timeout` plus a host backstop | Kills whole process groups and cannot hang the host (AD-027) |
| Tests | Docker tests marked, skipped if no daemon | Default run works anywhere; CI runs them (AD-028) |

See `specs/decisions.md` AD-022 to AD-029.

## Context

- README: FR2.1 (isolated Docker container), FR2.3 (all agent code and tests only in the container), FR2.4 (CPU, memory, run time limits, no host or secrets access), FR2.5 (clean up after each job). NFR Safety, Reliability ("a crashed job must not leave orphan containers").
- Mission principles: sandbox always, enforce in code not prompts, secrets never reach the agent or container.
- Tech stack: Docker via the Docker SDK for Python.
- Environment: Docker Desktop on macOS (10 CPUs, about 8 GB available to the VM). Defaults must fit a laptop; parallel workers come much later.
- Known limit: Docker Desktop's overlay storage cannot cap disk per container, so the workspace is a size-limited tmpfs in P4. Tmpfs memory counts against the container memory limit. P5 may revisit this when real repos are cloned.
- The image `python:3.11-slim` is pulled on first use and needs network on the host once.

## Constraints

- Never mount host paths or the Docker socket into the container.
- Never copy host environment variables into the container.
- Never log secrets; the sandbox does not handle any in P4.
- Docker integration tests must not leave containers behind, even when they fail.
- The default `uv run pytest` must pass with Docker stopped (docker tests skipped, with a visible reason).
- No UI work, so the no-gradient rule does not apply.

## Open items

- Disk quota per container beyond tmpfs is deferred to P5/P7.
- Network opt-in is a constructor flag in P4; how P5 enables it just for the clone step (and then turns it off) is decided in P5.
- The exact base image per repo (Python versions other than 3.11) is deferred.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-022 to AD-029).
