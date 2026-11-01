# Requirements: Sandbox Clone and Install (Roadmap P5)

## Goal

Get a target repository into the sandbox and ready to test: clone it inside the container, create a virtual environment, install its dependencies and pytest, then cut the network so everything that runs afterwards (tests, the agent's edits) is offline. This delivers FR2.1 (clone into the container) and FR2.2 (install dependencies automatically), and prepares P6 (run the tests).

## Scope

**In:**
- Bugbite's own sandbox image (`python:3.11-slim` + git), built on first use
- Disk-backed workspace volume with a soft size cap (`workspace_full` error)
- Network on for setup only, then disconnected before anything else runs
- `git clone` inside the container: shallow, default branch or a pinned ref/commit
- Dependency installation with a heuristic and fallbacks: pyproject/setup.py/setup.cfg, test-like PEP 735 dependency groups, requirements files, optional test requirements, pytest if missing
- Every setup step recorded (command, exit code, time, output tail) in a `SetupResult` with a `failure_reason` that later phases can turn into failure labels
- Tests that run offline, with Docker, and with the internet, each skipping cleanly when unavailable

**Out (later phases):**
- Running the test suite and parsing results; rejecting repos with no tests (P6)
- Orphan sweeping and pruning leftover volumes after a crash (P7)
- Private repositories and any token inside the container (not in v1 of the sandbox)
- Installing OS packages or compilers; Python versions other than 3.11
- Caching downloads between jobs
- Hard disk quotas (Docker Desktop cannot provide them)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Network | On for clone and install only, then disconnected | Agent-run code never has internet; the owner's choice (AD-030) |
| Image | Own Dockerfile: `python:3.11-slim` + `git` | Real `git clone` and later `git diff`; the owner's choice (AD-031) |
| Install | Heuristic with fallbacks, every step recorded | More repos work; failures are explainable; the owner's choice (AD-032) |
| Workspace | Disk-backed volume with a soft size cap | Repo and venv must not eat the 2 GB memory limit; the owner's choice (AD-033) |
| Clone | `git` in the container, shallow, ref validated, no credentials | Safe argument handling and no secrets in the container (AD-034) |

See `specs/decisions.md` AD-030 to AD-035. AD-026 (hardened profile) is superseded in part: the workspace is no longer a tmpfs.

## Context

- README: FR2.1, FR2.2, FR2.3 (everything in the container), FR2.4 (limits, no host or secrets access), FR2.5 (clean up); risks table: "Environment setup fails on many repos" (start with repos that install cleanly and log setup failures as their own category), and FR11 label "environment or dependency setup failed".
- Mission principles: sandbox always; secrets never in the container; honest failure reporting; measured claims.
- Builds on P4 (`Sandbox`, `SandboxConfig`, errors) and P2/P3 (`RepoRef` is the validated source of the clone URL).
- The installed project's code runs during `pip install` (build backends, `setup.py`). That is untrusted code with internet access for the duration of setup. This is the accepted risk of the chosen network approach; it has no secrets to steal and runs as non-root with all capabilities dropped and the usual limits.
- Known gap: while the network is on, the container sits on Docker's default bridge and can reach services on the host machine (for example through `host.docker.internal`). Closing this needs a custom firewalled network and is left as a follow-up.
- Known gap: a volume has no hard size limit. The soft cap is checked after setup (and exposed for later phases); a command could write a lot of data before the next check, bounded only by the per-command timeout.

## Constraints

- No credentials, tokens, or host environment variables inside the container (unchanged from P4).
- Clone URLs are built only from validated `RepoRef` values; refs are validated before use; git runs with list-form arguments, never through a shell with user-controlled text.
- The network must be cut even when setup fails or raises.
- Default `uv run pytest` must pass with Docker unreachable and with no internet.
- Tests must not leave containers or volumes behind.
- No UI work, so the no-gradient rule does not apply.

## Open items

- How private repos get cloned without putting a token in the container (for example a short-lived credential helper, or cloning on the host) is deferred.
- Per-repo Python versions are deferred; setup on a repo that needs a different Python will fail with `install_failed`.
- Whether to add build tools (gcc) to the image depends on how many chosen benchmark repos need them; revisit when the SWE-bench subset is chosen (P48).
- Closing the host-reachability gap on the setup network.
- Requirements kept in subfolders (for example `requirements/tests.txt`) are not detected yet (AD-035).

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-030 to AD-035).
