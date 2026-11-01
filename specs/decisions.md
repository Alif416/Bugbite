# Architecture Decision Log

Every architectural decision is recorded here with the reason it was taken. Add a new entry whenever a decision is made; never delete old ones. If a decision changes, add a new entry and mark the old one **Superseded by AD-NNN**.

Entry format: ID, date, phase, status, decision, why, alternatives considered, consequences.

---

## AD-001: uv with `pyproject.toml` for packaging

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Manage Python and dependencies with uv; a single `pyproject.toml` and committed `uv.lock`.
- **Why:** Fast installs, one lockfile for reproducible runs (mission principle 7), and uv installs the required Python version itself, which mattered because the machine only had Python 3.9.
- **Alternatives:** pip + venv (no lockfile, manual Python management); Poetry (heavier, slower).
- **Consequences:** Contributors and CI need uv installed.

## AD-002: `src/` layout with Hatchling build backend

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Code lives in `src/bugbite/`, built with Hatchling.
- **Why:** The `src/` layout stops tests from accidentally importing from the repo root, so tests exercise the installed package. Hatchling is simple and works natively with uv.
- **Alternatives:** Flat layout (risk of accidental imports); setuptools (more config).
- **Consequences:** The package must be installed (uv does this) before tests run.

## AD-003: Pin Python 3.11 with `.python-version`

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Pin 3.11 locally and in CI. `requires-python` stays `>=3.11`.
- **Why:** `uv` first resolved Python 3.15, so local and CI would have tested different versions. Pinning the minimum supported version means we test what we promise (tech-stack.md says 3.11+).
- **Alternatives:** Leave unpinned (version drift between local and CI).
- **Consequences:** Newer-Python issues are not caught until we add a version matrix.

## AD-004: One package, one module per architecture component

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** A single `bugbite` package with 11 sub-packages (`sandbox`, `retrieval`, `agent`, `adapter`, `verifier`, `pr_writer`, `recorder`, `failure_classifier`, `evals`, `trace_store`, `github`), empty until their phase.
- **Why:** README NFR (Maintainability) asks for clear module boundaries with unit tests. Fixing the boundaries now stops later phases from tangling them. A single package keeps setup simple for a solo project.
- **Alternatives:** Separate packages per component or a monorepo (overhead with no benefit yet).
- **Consequences:** Boundaries are by convention; later phases must not import across modules carelessly.

## AD-005: YAML config files, secrets only from environment variables

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** App limits and per-model settings live in YAML (`config/app.yaml`, `config/models.yaml`). Secrets are read only through `get_secret()` from environment variables.
- **Why:** FR5.1 and FR14.3 require model and provider to be config values. YAML allows comments and is readable as a model table. Keeping secrets out of files meets the Security requirement and mission principle 4.
- **Alternatives:** TOML (fewer features for nested model tables); JSON (no comments).
- **Consequences:** YAML has quirks (e.g. `on` parses as `True`), so config is validated strictly on load.

## AD-006: Strict validation with a single `ConfigError`

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Config loading validates presence, type, and non-negativity of every field and raises `ConfigError` naming the file and field. Booleans are rejected for numeric fields. `default_model` must exist in the models config.
- **Why:** Cost and step caps are safety controls (mission principle 6). A silently wrong cap, such as `true` read as `1` or a negative price, would defeat them. Failing at load time is cheaper than failing mid-run.
- **Alternatives:** Pydantic (extra dependency, not needed yet); no validation (unsafe).
- **Consequences:** Hand-written validation must be kept in sync with the dataclasses. Reconsider Pydantic if config grows.

## AD-007: Frozen dataclasses for config objects

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** `AppConfig` and `ModelConfig` are frozen dataclasses.
- **Why:** Config must not change during a run. Immutability helps reproducibility (principle 7) and makes recorded runs trustworthy.
- **Alternatives:** Plain dicts (no typing, easy to mutate).
- **Consequences:** Overrides, such as per-experiment settings, must build new objects.

## AD-008: No model or provider names in code

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Names like Haiku or Ollama appear only in config files, tests, and docs. Checked by grep in the validation checklist.
- **Why:** FR5.1 and mission principle 5 (model-agnostic). It keeps model comparison fair, since swapping a model is purely a config change.
- **Alternatives:** Hard-coded defaults (couples agent to one model).
- **Consequences:** Adapter code in later phases switches on a provider *type* from config, not on a model name.

## AD-009: Minimal P1 scope (no lint, types, Docker Compose)

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** P1 includes only layout, config, tests, CI running pytest, and docs.
- **Why:** Roadmap asks for very small phases. Lint/type tooling and Compose stubs have no code to act on yet and can be added when they have a purpose (Postgres/Redis arrive with P21 and P46+).
- **Alternatives:** Add ruff/mypy now (churn before there is code); Compose stubs (unused services).
- **Consequences:** No automated style or type checks until added in a later phase.

## AD-010: Squash-free merge to `main` with feature branches named by date

- **Date:** 2026-11-01 · **Phase:** P1 · **Status:** Accepted
- **Decision:** Each feature lives on a branch named like its spec folder (`YYYY-MM-DD-feature-name`) and is merged into `main` with a merge commit (`--no-ff`).
- **Why:** Branch name matches `specs/<folder>` so spec and code are easy to connect. A merge commit keeps the small logical commits and shows where each phase landed.
- **Alternatives:** Squash (loses commit detail); fast-forward (no marker of the feature boundary).
- **Consequences:** `main` history has merge commits.

---

## AD-011: Defer the "Python-only" repo check from P2 to P3

- **Date:** 2026-11-01 · **Phase:** P2 · **Status:** Accepted
- **Decision:** P2 validates URL shape only. Rejecting non-Python repos (FR1.4) moves to P3 with the GitHub API access check.
- **Why:** Knowing a repo's language requires a network call and a token. Keeping P2 offline keeps it small, deterministic, and free of secrets (roadmap asks for very small phases). The owner chose this option.
- **Alternatives:** Do the language check in P2 (pulls network and token handling forward, mixes two concerns).
- **Consequences:** Until P3 lands, a non-Python repo passes P2 validation. Nothing runs against it yet, so this is safe.

## AD-012: Typed `InputError` with a stable code and message

- **Date:** 2026-11-01 · **Phase:** P2 · **Status:** Accepted
- **Decision:** Validation failures raise `InputError(code, message)`; codes are constants such as `INVALID_URL` and `REPO_MISMATCH`.
- **Why:** The CLI, API, and dashboard each need to present errors differently. A stable code lets each map its own output (HTTP 422, CLI exit code, UI text) without parsing message strings. Separate from `ConfigError` because one is bad user input and the other is bad system setup. The owner chose this option.
- **Alternatives:** Result objects without exceptions (more verbose at every call site); reusing `ConfigError` (mixes user and operator errors).
- **Consequences:** Callers must catch `InputError`. New failure kinds need a new code.

## AD-013: Offline, stdlib-only URL parsing with strict allow-listing

- **Date:** 2026-11-01 · **Phase:** P2 · **Status:** Accepted
- **Decision:** Parse with `urllib.parse` and `re`; accept only `github.com` and `www.github.com`; validate owner and repo names against GitHub's allowed characters; no network, no new dependencies.
- **Why:** The parsed values later feed `git clone` and API calls inside jobs, so loose parsing is a security risk (path traversal, argument injection, look-alike hosts such as `github.com.evil.io`). Strict allow-listing in one place protects every later phase (mission principle 4). Stdlib keeps the dependency list unchanged.
- **Alternatives:** Third-party URL libraries (extra dependency, no benefit); permissive parsing with later sanitising (risk spreads across modules).
- **Consequences:** GitHub Enterprise and other hosts are unsupported until a decision to add them.

## AD-014: Issue URL plus repo URL as the only input form in v1 of the parser

- **Date:** 2026-11-01 · **Phase:** P2 · **Status:** Accepted
- **Decision:** `parse_job_input(issue_url, repo_url)` requires both and checks they refer to the same repo. "Issue URL only" and "issue text + repo URL" are not supported yet.
- **Why:** One clear form matches the README's primary input and the owner's choice. The mismatch check stops a job from fetching an issue from one repo and fixing another.
- **Alternatives:** Derive the repo from the issue URL (simpler to use, but a second form to test); free-text issues (needs a separate input path).
- **Consequences:** Other forms can be added later as separate functions without changing `parse_job_input`.

---

## AD-015: Include the phase number in feature folder and branch names

- **Date:** 2026-11-01 · **Phase:** process · **Status:** Accepted
- **Decision:** Feature folders and branches are named `YYYY-MM-DD-pNN-feature-name` (for example `2026-11-01-p03-issue-fetch`). P1 and P2 were renamed to match: `2026-11-01-p01-project-skeleton` and `2026-11-01-p02-input-validation`.
- **Why:** The date segment ends in the day of the month, so `2026-11-01-input-validation` looked like "phase 01" and the order was unclear when several phases land on one day. Putting the roadmap phase number in the name makes order and the link to `specs/roadmap.md` obvious. The owner chose this option and asked for P1 and P2 to be renamed too.
- **Alternatives:** Date only (ambiguous on same-day phases); leaving P1 and P2 unrenamed (inconsistent names).
- **Consequences:** Names are slightly longer. Merge commit messages for P1 and P2 (`a165f6e`, `aa94a03`) still show the old branch names because history is not rewritten. AD-010 describes the older pattern; this entry supersedes its naming part only (merge strategy is unchanged).

---

## AD-016: `httpx` with direct REST calls for the GitHub client

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** Talk to GitHub with `httpx` and the REST API directly, in our own small `GitHubClient`.
- **Why:** The client must be easy to test offline (httpx has a mock transport), give full control over timeouts, pagination, headers and error mapping, and stay small. Rate-limit and error details matter for this project (budget and resume logic come later) and a wrapper library would hide them. The owner chose this option. It adds one dependency.
- **Alternatives:** PyGithub (heavier, harder to mock, hides rate-limit details); stdlib `urllib` (no dependency, but more hand-written code for pagination, errors and timeouts).
- **Consequences:** We own pagination and error mapping. The same client will grow in P41 onward (branches, PRs, comments).

## AD-017: GitHub token is optional and always passed in by the caller

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** `GitHubClient` accepts an optional token and never reads the environment. Without a token it makes anonymous requests. A private repo with no token gives a clear message.
- **Why:** Public repos work anonymously, so quick tries do not need a token. A token raises rate limits and allows private repos. Having the caller pass the token keeps secret handling at the edges (mission principle 4) and stops tests from picking up a real token by accident. The owner chose this option.
- **Alternatives:** Token required (blocks easy public use); client reading `GITHUB_TOKEN` itself (hidden dependency on environment, risk in tests).
- **Consequences:** Entry points (CLI, API) must read `GITHUB_TOKEN` via `get_secret` and pass it in. Anonymous use is limited to 60 requests per hour.

## AD-018: Decide "is Python" from GitHub's primary language

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** A repo is accepted when GitHub's `language` field equals `Python`. Any other value, or none, raises `NOT_PYTHON` and names what was detected.
- **Why:** One call we already make, no extra requests, simple to explain (FR1.4). The owner chose this option.
- **Alternatives:** Language share threshold (one more call, more accurate on mixed repos); checking for `pyproject.toml`, `setup.py`, or `requirements.txt` (closer to what the sandbox needs, more calls).
- **Consequences:** Mixed-language repos where Python is not the largest share are rejected, and repos mislabelled by GitHub can pass. Such cases will show up in failure analysis. Revisit if it causes real misses.

## AD-019: Test-suite detection moves to the sandbox phases

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** P3 does not check that the repo has tests. Rejecting repos with no tests is added to P6, when pytest is actually run in the container.
- **Why:** Guessing from file names through the API is slow and can be wrong. Running the real test command after cloning is the reliable signal. Keeps P3 small. The owner chose this option.
- **Alternatives:** Light API check for a `tests/` directory or `test_*.py` files (extra calls, false positives and negatives).
- **Consequences:** A Python repo with no tests passes P3 and is rejected later. Nothing expensive happens before P6, so this is cheap.

## AD-020: Split user-fixable errors from provider errors; no retries yet

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** User-fixable problems (repo not found, not Python, issue not found, pull request given as issue) are `InputError` with new codes. Provider or network problems (rate limit, auth failure, server error, timeout, bad response) are a separate `GitHubAPIError` with its own stable codes. P3 raises immediately and does not retry or sleep.
- **Why:** The CLI and dashboard need to tell "fix your input" from "try again later" and show different messages. Retrying and backoff belong with the queue and resume work (README FR14.5, roadmap P51), where they can be designed once for all providers. Keeping them out keeps P3 small.
- **Alternatives:** One error type for everything (callers parse messages); adding retries now (duplicates later work and complicates tests).
- **Consequences:** A transient 5xx fails the job until retries exist. Acceptable while jobs are run by hand.

## AD-021: Cap comments and text size, and flag truncation

- **Date:** 2026-11-01 · **Phase:** P3 · **Status:** Accepted
- **Decision:** Fetch at most 50 comments (default, configurable) and cut each text field to 20,000 characters. Truncation is recorded with a flag on the data.
- **Why:** Context sent to the model must stay small (FR3.4) and cost is capped (mission principle 6). Long threads and huge bodies are also a vector for untrusted text. Flags keep the cut visible, so the agent and PR evidence can say "input was truncated" instead of hiding it.
- **Alternatives:** Fetch everything and trim later (wasted calls and memory); silent truncation (hides information, breaks honesty).
- **Consequences:** Very long threads lose later comments. The cap can be tuned per run from config later.

---

## AD-022: Docker SDK for Python as the sandbox interface

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** Control Docker through the `docker` Python package, not by shelling out to the `docker` CLI.
- **Why:** It gives structured errors, exact numeric limits, and no shell quoting of untrusted strings (a quoting bug in a command that launches untrusted code would be a security bug). It is the choice named in the tech stack, and the owner chose it.
- **Alternatives:** Shelling out to the CLI (no new dependency, but output parsing and argument quoting risks).
- **Consequences:** One more dependency. The SDK talks to the Docker socket on the host, so the host user running Bugbite must be able to reach Docker.

## AD-023: No network by default; opt-in per container

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** Containers start with `network_mode="none"`. A `network=True` flag turns networking on for a container.
- **Why:** The agent runs untrusted code (the repo's code and its own edits). Without a network it cannot exfiltrate data, call out to other services, or reach the host network (FR2.4, mission principle 4). The owner chose this. Cloning and `pip install` need a network, so later phases must enable it deliberately and only for those steps.
- **Alternatives:** Always on (simple, but weakens isolation).
- **Consequences:** P5 has to decide how to do the network step safely (for example a short-lived networked container for clone and install, or a restricted network). Until then, nothing in the container can download anything.

## AD-024: Default limits, all configurable under `sandbox:` in app.yaml

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** Defaults are 1 CPU, 2048 MB memory with no swap, 256 processes, 120 s per command, 1 MiB output cap per stream, 1024 MB workspace, 1800 s container lifetime. All are overridable in `config/app.yaml` and validated on load; unknown keys are rejected.
- **Why:** The owner chose these defaults as enough for most small Python suites on a laptop. The process cap stops fork bombs, no swap makes the memory limit real, and the output cap protects host memory and the model context (FR3.4). Config-driven values keep experiments reproducible (mission principle 7) and strict validation follows AD-006.
- **Alternatives:** Tighter limits (many installs and suites would fail); larger limits (slow failure, hard on a laptop with parallel workers later).
- **Consequences:** Some heavy repos will hit the limits; those runs get a clear failure label later. Limits can be tuned per run from config.

## AD-025: One long-lived container per job, with many `exec` calls

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** A job gets one container that stays up (kept alive by `sleep <max_lifetime_s>`), and each command runs as an `exec` inside it.
- **Why:** Clone, install, baseline test run, edits, and verification all depend on state from earlier steps. One container per command would lose that state and re-do slow setup. Using `sleep` with a lifetime means a container whose job crashed still expires on its own, which supports "a crashed job must not leave orphan containers" before P7 adds sweeping.
- **Alternatives:** A fresh container per command (clean, but stateless and slow); a container with a mounted host directory (breaks isolation, see AD-026).
- **Consequences:** State from one command can affect the next, so cheating guards and the verifier must not trust sandbox state blindly (P33). Containers have a hard maximum age.

## AD-026: Hardened container profile

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted (tmpfs workspace superseded in part by AD-033)
- **Decision:** Run as non-root `1000:1000`, drop all Linux capabilities, set `no-new-privileges`, mount no host paths and no Docker socket, pass no host environment variables, and use a size-limited tmpfs at `/workspace`.
- **Why:** FR2.4 requires no access to the host or to secrets, and mission principle 4 says untrusted code never runs outside the sandbox. Each setting removes a known escape or leak path at no cost to the work we need. A tmpfs workspace gives a writable, bounded, disposable area without touching the host disk.
- **Alternatives:** Bind-mounting a host workspace (easy to inspect, but exposes the host and file ownership issues); read-only root filesystem (blocks installs in P5).
- **Consequences:** Anything needing root (system packages) will not work inside the sandbox. Tmpfs counts against the memory limit, so large clones use memory; revisit in P5. Docker Desktop cannot cap disk per container, so disk limits remain open.

## AD-027: In-container timeout with a host-side backstop; capped output

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** Wrap each command in `timeout --kill-after=2 N`, which signals the command's whole process group. As a backstop, if the exec has not returned `timeout + 15` seconds after starting, kill the container and raise `backstop_timeout`. Keep only `max_output_bytes` of each stream and flag truncation.
- **Why:** The SDK's exec call has no timeout of its own, and killing only the top shell would leave child processes running. A hung exec must never hang the host job (FR5.4 wall-clock caps depend on this). Capping output protects host memory from a command that prints without end.
- **Alternatives:** Host-side timeout only (cannot kill process groups inside the container); killing the container on every timeout (loses job state).
- **Consequences:** Commands without `timeout` on the image path would fail; the default image has it. A backstop timeout is destructive: it ends the sandbox.

## AD-028: Docker tests are marked and skip when Docker is unavailable

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** Tests that need a daemon carry `@pytest.mark.docker` and skip with a clear reason when none is reachable. Everything else runs offline. CI (ubuntu, which has Docker) runs them all.
- **Why:** Contributors without Docker running can still run the suite, and a skipped test is visible rather than silently passing. Real isolation claims (non-root, no network, limits) can only be proven against a real container, so mocking them would prove nothing.
- **Alternatives:** Mock Docker entirely (does not prove isolation); require Docker for all tests (breaks quick local runs).
- **Consequences:** A green local run without Docker does not prove isolation; validation requires a run with Docker up, which this phase's checklist demands.

---

## AD-029: Verify the container is usable before `start()` returns

- **Date:** 2026-11-01 · **Phase:** P4 · **Status:** Accepted
- **Decision:** After the container starts, `start()` waits a moment, confirms the container is still running, and runs a trivial command (`true`) through the same `timeout` wrapper used for real commands. If any of this fails, the container is removed and `start()` raises `start_failed` with a short explanation.
- **Why:** Found while testing: with `init=True`, a container whose keep-alive command cannot run (for example an image with no `sleep`) is reported as started and then exits immediately. Without a check, `start()` would succeed, leak an exited container, and the first real command would fail with a confusing error. The probe also proves that `sh` and `timeout`, which every later command depends on, exist in the image (AD-027).
- **Alternatives:** Trust `container.start()` (leaks containers, confusing failures); only check the status without a probe (does not prove `timeout` and `sh` work).
- **Consequences:** `start()` takes about 0.2 s longer. Images without `sleep`, `sh`, or `timeout` are rejected up front, which is the intended behaviour.

---

## AD-030: Network on for setup only, then disconnected

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted
- **Decision:** The container starts with network access, runs `git clone` and `pip install`, and is then disconnected from every network (in a `finally`, so it happens even when setup fails). Tests and agent commands only ever run with no network.
- **Why:** Cloning and installing require the internet (FR2.1, FR2.2), but the agent runs code it wrote and the repo's code, and must not reach the internet (FR2.4, mission principle 4). Cutting the network after setup keeps the strong guarantee for everything that matters. The owner chose this option.
- **Alternatives:** Always on (weakens isolation); two containers, one for setup and one for running (strongest separation, but needs a shared disk volume and more moving parts).
- **Consequences:** `pip install` runs the repo's build scripts with internet access. This is an accepted risk: the container holds no secrets, runs as non-root without capabilities, and is resource limited. While online it can also reach host services through Docker's bridge; closing that needs a custom firewalled network and is a recorded follow-up. Any later step that needs the network (such as installing something the agent decides it needs) is not possible.

## AD-031: Bugbite's own sandbox image (python:3.11-slim + git), built on demand

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted
- **Decision:** Add `docker/sandbox.Dockerfile` based on `python:3.11-slim` with `git` and `ca-certificates`. The image is built locally the first time it is needed and tagged with a version suffix (`bugbite-sandbox:py3.11-1`) that is bumped when the Dockerfile changes. It becomes the default image.
- **Why:** The stock image has no `git`, and the verifier will need real `git diff` for patch size and changed-file checks (FR6.5). Cloning inside the container also matches FR2.1. The owner chose this option over a tarball download (no history, no `git diff`) and over a larger image with compilers.
- **Alternatives:** Stock image plus GitHub tarball (no git history); image with `build-essential` (about 200 MB larger, fewer setup failures on older repos, revisit at P48).
- **Consequences:** First use needs network and a few minutes to build. Packages that must compile from source will fail setup until build tools are added. Changing the Dockerfile means bumping the tag.

## AD-032: Heuristic dependency install with fallbacks; every step recorded; setup failures are results

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted
- **Decision:** Create a venv in `/workspace/.venv`, then install by a fixed plan: `pip install -e ".[test,tests,testing]"` falling back to `pip install -e .` for repos with a packaging file; `-r requirements.txt` for repos without one; optional test-requirements files best effort; `pytest` only if not already installed. Each step's command, exit code, duration, and last 2,000 characters of output are recorded in a `SetupResult` with a `failure_reason`. A failed setup is returned as a result, not raised.
- **Why:** The README lists "environment setup fails on many repos" as a risk and wants setup failures logged as their own failure category (FR11). A fixed plan is predictable and testable offline (`plan_install` is a pure function), and recording each step makes failures explainable and labellable. Installing pytest only when missing avoids overriding versions a repo pins. Requesting several extras at once works because pip only warns about extras that do not exist. The owner chose this option over a minimal install.
- **Alternatives:** Minimal install (more repos fail); asking the model to work out installation (costly and non-deterministic, and far outside P5); returning exceptions for setup failures (loses the structured detail the failure classifier needs).
- **Consequences:** Repos needing unusual setup (system packages, other Python versions, custom install scripts) will fail with `install_failed`. The heuristic can be extended later without changing the result type.

## AD-033: Disk-backed workspace volume with a soft size cap

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted (supersedes the tmpfs part of AD-026 and redefines `workspace_mb` from AD-024)
- **Decision:** `/workspace` becomes an anonymous Docker volume that is removed with the container. `workspace_mb` (default raised to 2048) is now a soft cap enforced by measuring usage with `du` after setup, with `check_workspace()` available to later phases. Exceeding it raises `workspace_full`.
- **Why:** With a tmpfs, a cloned repo plus a venv counts against the 2 GB memory limit, so installs would cause out-of-memory kills (AD-026 flagged this for P5). A volume keeps the workspace on disk. Docker Desktop cannot enforce a hard quota on a volume, so a measured soft cap is the best available control. The owner chose this option.
- **Alternatives:** Keep the tmpfs and raise memory (installs eat RAM, risk of OOM during pip); a host bind mount (breaks the no-host-mount rule).
- **Consequences:** A runaway command can fill disk until the next check; the per-command timeout bounds this. Crashed jobs can leave volumes behind; pruning them is added to P7. Files written to the volume survive container restarts but not removal.

## AD-034: Clone with git inside the container, shallow, validated ref, no credentials

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted
- **Decision:** Run `git clone --depth 1` inside the container using list-form arguments, with the URL built only from a validated `RepoRef`. A pinned `ref` is validated against a strict pattern and fetched with `git fetch --depth 1 origin <ref>` then checked out. Submodule recursion and the `ext` protocol are disabled. No token or credential enters the container, so private repos are not supported in P5.
- **Why:** Shallow clones are fast and small, which suits the time and disk budget. Benchmark runs (P48) need an exact base commit, hence the ref path. List-form arguments and ref validation prevent argument injection (a ref beginning with `-` could be read as a git option). Keeping credentials out follows mission principle 4 and the README rule that keys are never exposed to the agent or container.
- **Alternatives:** Full clones (slower, larger, rarely needed); cloning on the host and copying in (host runs git on untrusted data and needs file transfer); passing the token into the container for private repos (breaks the no-secrets rule).
- **Consequences:** No history beyond the checked-out commit. Private repos need a separate design later.

---

## AD-035: Install test-like PEP 735 dependency groups (found on a real repo)

- **Date:** 2026-11-01 · **Phase:** P5 · **Status:** Accepted (extends AD-032)
- **Decision:** If `pyproject.toml` has a `[dependency-groups]` table, install the groups named `test`, `tests`, or `testing` (or `dev` only when no test-like group exists) with `pip install --group <name>`, as optional steps. Because `--group` needs pip 25.1 or newer and the base image ships an older pip, an optional `pip-upgrade` step runs first, only when there are groups to install. Group names are read inside the container with `tomllib` and filtered through a fixed whitelist before they reach any command line.
- **Why:** The first manual run on a real public repo (`pallets/itsdangerous`) "succeeded" at setup but its tests could not import `freezegun`, because the test dependencies live in a dependency group that the original heuristic ignored. The README names "environment setup fails on many repos" as a main risk, and this style is increasingly common with uv-based projects. After the change the same repo sets up in about 11 seconds and its own 297 tests pass offline. Whitelisting names stops a hostile `pyproject.toml` from injecting pip options.
- **Alternatives:** Ignore groups and let such repos fail with import errors in P6 (a mislabelled failure: it would look like a test failure, not a setup gap); install every group (pulls in docs and lint tools, slower and more likely to conflict).
- **Consequences:** An extra pip upgrade step (about 2 seconds) for repos with groups. Requirements kept in subfolders such as `requirements/tests.txt` are still not detected; add them when a chosen benchmark repo needs it. Group install failures are warnings, so a repo can still report `ok` with missing test dependencies; P6 test collection errors will surface that.

---

## AD-036: Capture test results with a small pytest plugin kept outside the repo

- **Date:** 2026-11-01 · **Phase:** P6 · **Status:** Accepted
- **Decision:** Ship a single-file pytest plugin (`bugbite_report.py`) inside the Bugbite package. Before each run it is copied to `/workspace/.bugbite/`, loaded with `-p bugbite_report` through `PYTHONPATH`, and appends one JSON line per event (`collected`, `test`, `collect_error`, `session`) to a report file, flushing after each line. The runner parses that file. Two small sandbox features support it: `Sandbox.write_file` and a per-command `env`.
- **Why:** Later phases compare tests before and after a fix by exact node ID (FR6.2, FR6.3), so IDs must be exact. JUnit XML would force us to rebuild IDs from class and name, which is lossy for parametrized tests, and it cannot tell an expected failure from a skip. Parsing text output is fragile across pytest versions and plugins. Writing lines as tests finish means a timeout or crash still leaves usable partial results. Keeping the plugin outside the repo means it never shows up in `git diff` and the repo needs no changes. The owner chose this option.
- **Alternatives:** JUnit XML (built in, but lossy IDs); `pytest-json-report` (a dependency installed into the repo's environment that could conflict with pins); text parsing (fragile).
- **Consequences:** We maintain a small plugin that must stay compatible with old pytest versions (plain syntax, standard library only). Under `xdist` several processes write to the file, so each line carries the worker name and the parser takes the controller's session line.

## AD-037: Run statuses, and what counts as "no tests"

- **Date:** 2026-11-01 · **Phase:** P6 · **Status:** Accepted
- **Decision:** A run has one status: `ok` (pytest ran; tests passed or failed), `no_tests` (collection succeeded and found nothing, pytest exit 5), `collection_error` (import errors during collection, or a pytest usage error such as `addopts` naming a plugin that is not installed), `timeout` (partial results kept), or `crashed` (internal error, plugin failed to load, report missing, or an unexpected exit code). Only `no_tests` leads to rejection, through `ensure_has_tests`, which raises `InputError("no_tests")`. Everything else is returned as a result with a reason.
- **Why:** The README scopes v1 to Python repos with an existing test suite, so a repo with none should be refused up front. But zero collected tests caused by a missing dependency is an environment problem, not an absence of tests, and the README wants those logged as their own failure category (FR11: "environment or dependency setup failed"). Treating both as "no tests" would wrongly reject repos that only need a better install. The owner chose this option. Exit codes are mapped explicitly so a wrong result can never be reported as `ok`.
- **Alternatives:** Reject both cases as "no tests" (wrongly rejects fixable repos); a single generic failure status (loses the information the failure classifier needs).
- **Consequences:** A `usage error` is reported as `collection_error`, so that status covers "pytest could not start collecting" in general; the `reason` text says which kind. The meaning of each status is documented in the README.

## AD-038: Respect the repo's pytest configuration; add only our own flags; 300 s limit

- **Date:** 2026-11-01 · **Phase:** P6 · **Status:** Accepted
- **Decision:** Run `python -m pytest` from the venv in the repo root, adding only `-p bugbite_report`, `-p no:cacheprovider`, `--tb=short`, and `--color=no`. The repo's own `addopts`, markers, and ini options apply unchanged. A full run is limited by `test_timeout_s` (default 300 s, configurable), separate from the 120 s limit for ordinary commands.
- **Why:** Running the suite the way the project does keeps results meaningful: overriding `addopts` could drop flags the suite needs and silently change which tests run. `-p no:cacheprovider` avoids writing `.pytest_cache` into the repo, and `PYTHONDONTWRITEBYTECODE=1` stops `__pycache__` folders appearing in it (found in testing), so the repo's working tree stays as clean as possible for the patch checks in later phases; `--tb=short` and no colour keep the saved output compact and readable in PR evidence. 300 s fits the 10-minute median-job target when a baseline, a fix, and a verification run all happen. The owner chose both defaults.
- **Alternatives:** Empty `addopts` (changes which tests run); a longer limit (a single run could use the whole job budget); a shorter one (many real suites would time out).
- **Consequences:** Repos whose `addopts` need missing plugins fail clearly as `collection_error`. Tests that need the internet fail because the network is cut after setup; baseline comparison (P31, P32) must treat tests failing both before and after as pre-existing.

## AD-039: What P6 guarantees about result integrity

- **Date:** 2026-11-01 · **Phase:** P6 · **Status:** Accepted
- **Decision:** Before every run the plugin file is rewritten and the report file is deleted, so stale or edited artifacts are never reused. P6 does not defend against code running inside pytest that deliberately forges the report (for example a malicious `conftest.py`). That defence is left to the verifier in P33, which will re-run tests in a clean container built from the patch.
- **Why:** README FR6.5 requires the pass check to be done by the verifier, not by the agent. Trying to make an in-container run tamper-proof would add complexity without a real guarantee, because the code under test and the report writer share one process. Stating the limit plainly keeps later claims honest (mission principle 8).
- **Alternatives:** Hashing or signing the report from inside the container (the forger has the same access); running the plugin on the host (not possible, tests run in the container).
- **Consequences:** Until P33, a result is only as trustworthy as the repo code and the agent's edits. Test results from agent runs must not be reported as final verification.

---

## AD-040: Docker removes sandboxes itself when they exit (`auto_remove`)

- **Date:** 2026-11-01 · **Phase:** P7 · **Status:** Accepted
- **Decision:** Create every sandbox container with `auto_remove=True` (like `docker run --rm`). Docker then deletes the container, and its anonymous workspace volume, as soon as it exits: at the end of its `max_lifetime_s`, when it is killed, or when its keep-alive process dies. `run()` turns a "no such container" error into a clear `sandbox_closed` error, and `start()` treats a container that vanished right after starting as "exited immediately".
- **Why:** This is the strongest layer because it works even when Bugbite itself is dead or never runs again; no code of ours has to be alive to clean up (README reliability rule: a crashed job must not leave orphan containers). Before P7 an expired container stayed behind stopped, holding its workspace volume (hundreds of MB for real repos). The owner chose the three-layer approach.
- **Alternatives:** A sweeper only (nothing is cleaned until some later Bugbite run sweeps); leaving exited containers for inspection (useful for debugging, but they pile up and hold disk).
- **Consequences:** The output of a container that exits immediately (for example an image missing `sleep`) can no longer be read for the error message, because Docker has already removed it; the message says so. A running container is still only stopped by its lifetime, a kill, or our cleanup, so layers two and three cover the time before expiry.

## AD-041: Ownership labels and the orphan rule

- **Date:** 2026-11-01 · **Phase:** P7 · **Status:** Accepted
- **Decision:** Label every container and workspace volume with the owner's host name, process id, and a process start token, plus a creation time and the container's `max_lifetime`. A container is an orphan if its owner is on this host and the process is gone (or its start token differs), or if it is older than `max_lifetime + 60 s` whatever the owner. Owners on other hosts are judged by age only. Containers without labels (made before P7) are judged by Docker's creation time and the default lifetime. The decision is a pure function so every case is unit-tested.
- **Why:** The sweeper must be safe while other worker processes (P50) hold live sandboxes: a live owner within its lifetime must never be touched. A process id alone can be reused by the operating system, so a start token (from `ps -o lstart=`, available on macOS and Linux) guards against mistaking a new process for the dead owner. Age is the fallback for owners we cannot inspect. The owner chose this rule over age only, which would leave a crashed job's container for at least half an hour.
- **Alternatives:** Age only (slow to clean, no protection against long jobs with raised lifetimes); heartbeat files or a lock service (more moving parts for a single-machine tool); pidfiles (stale after crashes).
- **Consequences:** If `ps` is unavailable the start token is empty and only the process id is compared. A shared Docker host used from several machines needs a better owner identity; recorded as an open item.

## AD-042: Sweep before each sandbox start, and on demand; never block a start

- **Date:** 2026-11-01 · **Phase:** P7 · **Status:** Accepted
- **Decision:** `Sandbox.start()` runs `sweep_orphans()` first (one label-filtered Docker list call plus removals). `sweep_orphans()` is also public for the future `bugbite cleanup` command and the job manager. A failure in the sweeper is logged as a warning and the start continues.
- **Why:** Crashes then heal themselves the next time anything starts, without a human or a scheduler. Cleanup is housekeeping, so it must never be the reason a job cannot start. The owner chose automatic plus on-demand.
- **Alternatives:** Explicit calls only (nothing cleans unless every entry point remembers); a background thread or cron (more machinery, and it needs its own supervision).
- **Consequences:** Each start pays a small extra Docker call. The sweeper only touches objects carrying the Bugbite label, so unrelated containers and volumes are safe.

## AD-043: Label volumes at creation; remove by label and age, never by blanket prune

- **Date:** 2026-11-01 · **Phase:** P7 · **Status:** Accepted
- **Decision:** The anonymous workspace volume gets the Bugbite labels when it is created. The sweeper lists volumes with the Bugbite label, skips those younger than the grace period, and tries to remove each; Docker refuses volumes still in use, which are skipped. No `docker volume prune` or similar blanket command is used.
- **Why:** A blanket prune would delete any unused volume on the machine, including other projects' data. Labels make "ours" provable, and the age check avoids racing a container that is being created. Trying to remove a volume and letting Docker refuse in-use ones is safer than guessing usage. This completes the AD-033 note to prune leftover workspace volumes.
- **Alternatives:** `volume prune` filtered by label (works, but races container creation and depends on Docker version behaviour for anonymous volumes); naming volumes and tracking them in a file (state to keep consistent).
- **Consequences:** Workspace volumes created before P7 carry no label and cannot be recognised as Bugbite's; the README tells the user how to list and remove dangling volumes by hand once.

## AD-044: Close live sandboxes on exit; signal handling is opt-in

- **Date:** 2026-11-01 · **Phase:** P7 · **Status:** Accepted
- **Decision:** Keep a registry of live sandboxes (weak references, with a lock). An `atexit` hook, registered once, closes them all. `install_signal_cleanup()` is an explicit function for entry points: it must run in the main thread, skips signals that are currently ignored, closes all sandboxes on `SIGTERM` or `SIGINT`, then restores the previous handler and lets it run, so `SIGINT` still raises `KeyboardInterrupt` and `SIGTERM` still ends the process. It returns a function that removes the handlers.
- **Why:** Normal exits and Ctrl-C are the common ways a job ends early, and cleaning promptly is better than waiting for the lifetime. A library must not take over process-wide signal behaviour just by being imported, because that can clash with web servers, test runners, and other libraries; so installing handlers is a deliberate call by CLI and API entry points. The owner chose this option.
- **Alternatives:** Install handlers automatically on import (surprising global side effect); no exit hooks (rely on auto-remove and the sweeper, so a Ctrl-C leaves a container for up to half an hour).
- **Consequences:** `SIGKILL` and power loss cannot be caught; they are covered by auto-remove at expiry and by the next sweep. Entry points added in later phases must call `install_signal_cleanup()`.

---

## AD-045: The model interface is synchronous

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** `adapter.generate(request)` is an ordinary blocking call that returns a response.
- **Why:** The agent loop is a step-by-step sequence (think, call a tool, read the result), the sandbox API is synchronous, and replay must be deterministic, so blocking calls keep every layer and every test simple. Parallelism is planned as worker processes fed by a queue (P50), not many calls in one event loop. The owner chose this option.
- **Alternatives:** An async interface (suits FastAPI and many concurrent calls in one process, but spreads async through the loop, the synchronous sandbox calls, and every test).
- **Consequences:** The API server must run jobs in workers or threads rather than awaiting them. An async wrapper can be added later without changing adapters.

## AD-046: Bugbite's own neutral message format with content blocks

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** Requests and responses use immutable dataclasses: messages made of typed content blocks (text, tool call, tool result), a separate system prompt, and a cache marker on text blocks. Each adapter translates to and from its provider's format. Requests and responses convert to and from JSON exactly, with a `schema_version`.
- **Why:** Recordings for replay (FR10, FR14.7) must not depend on any provider. A neutral format means one recording can be read, compared, and replayed without any provider SDK, and swapping a model never changes what is stored. Blocks make tool results and cache markers first-class, which the OpenAI-style flat dicts handle awkwardly and the Anthropic shape ties to one vendor. The owner chose this option.
- **Alternatives:** Anthropic-style blocks as the internal format (every other adapter translates from Claude's shape, recordings tied to one provider); OpenAI-style dicts (cache markers and tool results fit poorly, Claude adapter translates from it).
- **Consequences:** Every adapter owns a translation layer that needs its own tests. The schema version lets recordings be migrated when the format changes.

## AD-046 note: token counts in `Usage`

- **Added during the build (2026-11-01):** `Usage.input_tokens` counts prompt tokens charged at the normal input rate and excludes tokens read from or written to the provider's cache; `cache_read_tokens` and `cache_write_tokens` are separate. `prompt_tokens` is the sum of the three prompt counts and `total` adds the output tokens. Adapters whose provider reports cached tokens inside its prompt count (as OpenAI-style APIs do) must subtract them, so that cost in P11 is never counted twice.

## AD-047: Whole responses only; no streaming

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** One request returns one complete response with text, tool calls, usage, and stop reason. There is no token streaming.
- **Why:** Recording, replay, retries, and cost accounting are all simpler and exact with whole responses. The dashboard's live progress (FR8.4) comes from agent-loop events such as each model call and tool call, not from tokens. The owner chose this option.
- **Alternatives:** Optional streaming (nicer chat-like view, but doubles the adapter surface and complicates recording and retries).
- **Consequences:** Long generations show nothing until they finish. Streaming can be added later as a separate method without breaking callers.

## AD-048: Parsed tool arguments with an error field, and strict conversation validation before any call

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** A tool call carries its arguments as a parsed dictionary plus an optional `error` string. If a model emits arguments that cannot be parsed, the call is still returned, with empty arguments and the error set, so the agent can report it back instead of crashing. A shared `validate_request` runs before any network call and rejects malformed conversations: empty messages, a first or last message that is not from the user, non-alternating roles, tool calls or results in the wrong role, tool results with no matching call, unanswered tool calls, duplicate call ids or tool names, an out-of-range temperature, and a non-positive output cap.
- **Why:** Weaker and free models often produce broken tool JSON (README risk and FR14.4), and the loop must treat that as a recoverable step, not an exception. Providers reject malformed conversations with an error after the request is already sent, and paid providers can bill for it; checking locally first costs nothing and gives one clear message for every provider (mission principle 6: budget is a hard limit).
- **Alternatives:** Raw argument strings (every caller parses and handles errors); letting each provider report invalid conversations (different messages, possible cost).
- **Consequences:** The validator encodes our conversation rules, so it must be updated if the loop ever needs something the rules forbid (for example consecutive user messages).

## AD-049: One normalised `AdapterError`; adapters do not retry

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** Adapters raise `AdapterError` with a stable code (`rate_limited`, `auth_failed`, `context_too_long`, `invalid_request`, `server_error`, `network_error`, `timeout`, `bad_response`), an optional `retry_after_s`, and an optional `status_code`. Adapters raise immediately and never retry or sleep.
- **Why:** The loop, the queue, and the failure classifier need to react to the cause (back off, shrink the context, give up) without knowing which provider failed. Retry, backoff, and resume (FR14.5) are policy that should be designed once for all providers in the batch phases, not duplicated in each adapter. This follows the same split as AD-020 for GitHub errors.
- **Alternatives:** Provider-specific exceptions (callers must know every provider); retries inside each adapter (duplicated, hard to test, hides cost).
- **Consequences:** A transient failure ends the call until retry policy exists. Error messages must not contain API keys or request bodies.

## AD-050: Model config additions; the caller passes the key; providers are validated

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** `ModelConfig` gains `api_key_env` (the name of the environment variable that holds the key, or none for local models) and `max_output_tokens` (default 4096), plus a read-only `integration` (`native` or `text_action`). Loading rejects an unknown provider, a non-http base URL, non-positive sizes, an output cap not smaller than the context window, and a malformed variable name. `create_adapter(model_config, api_key=...)` takes the key from the caller; adapters never read the environment.
- **Why:** FR14.3 and FR13.8 need the integration method and the key source to be configuration, not code. Keeping environment reads at the edges follows the rule set for the GitHub client (AD-017) and mission principle 4, and stops tests from picking up real keys. Validating at load time follows AD-006: a wrong provider name should fail when the config loads, not in the middle of a paid run.
- **Alternatives:** Adapters reading the variable themselves (hidden environment dependency); no provider validation (typos fail late).
- **Consequences:** Entry points must read the variable named by `api_key_env` and pass the key in. Adding a provider means adding it to the supported list and registering an adapter.

## AD-051: Text-action fallback as a wrapper; a scripted adapter and contract tests

- **Date:** 2026-11-01 · **Phase:** P8 · **Status:** Accepted
- **Decision:** The text-action fallback (P12) will be a wrapper adapter that exposes the same interface over any other adapter, so the agent sees no difference. This phase ships `ScriptedAdapter` (canned responses and errors, records requests, validates like a real adapter) and a reusable adapter contract test class that every real adapter must pass.
- **Why:** One interface for all models (FR14.1) means a model without native tool calling should not need special handling in the loop; a wrapper keeps that logic in one place and testable. A scripted adapter lets the agent loop, recorder, and replayer be built and tested with no provider and no cost (mission principle 6). A shared contract test makes "works like every other adapter" checkable instead of assumed.
- **Alternatives:** A flag inside each adapter (duplicated logic); testing the loop only against live models (costly, non-deterministic).
- **Consequences:** The wrapper (P12) must produce the same response shape, including normalised stop reasons and usage. The contract tests grow as real adapters reveal differences.

---

## AD-052: `httpx` and the Chat Completions API, no vendor SDK

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** The OpenAI-compatible adapter calls `POST {base_url}/chat/completions` with `httpx`. It uses neither the `openai` package nor the newer Responses API.
- **Why:** The Chat Completions shape is the common denominator that Ollama, Groq, OpenRouter, vLLM, and similar servers implement, which is what FR14.2 asks for. A direct client keeps one small dependency we already use (AD-016), makes the adapter easy to test with a mock transport and a loopback server, and gives full control over error mapping, redirects (the key must not follow a redirect), and timeouts. Vendor SDKs add their own retry and error behaviour, which would conflict with AD-049 (adapters do not retry).
- **Alternatives:** The `openai` SDK (hides retries and errors, more dependencies, assumes OpenAI-specific behaviour); the Responses API (not implemented by most compatible servers).
- **Consequences:** We own the translation and its tests. Servers that deviate from the common shape need tolerance in parsing (AD-053).

## AD-053: Translate strictly, parse tolerantly

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** Outgoing requests follow the standard shape exactly (system message, `tool` role messages for tool results, JSON-string tool arguments, `max_tokens`). Incoming responses are parsed tolerantly: `content` may be a string, `null`, or a list of text parts; reasoning fields are ignored; tool arguments may be a string or an object; missing or duplicate tool call ids are replaced with unique ones; `stop` with tool calls means `tool_use`; cached prompt tokens are subtracted from the input count. Anything that cannot be understood (no choices, a tool call without a name, non-JSON) is a `bad_response`, and unparseable tool arguments become an empty dictionary plus an `error` on that call, never an exception.
- **Why:** Free and local servers differ in details, and the README lists weak tool calling as a known risk (FR14.4). A strict parser would turn harmless differences into failed runs, while a sloppy sender would risk rejections. Keeping unparseable arguments as data lets the agent tell the model what it got wrong (AD-048). Ignoring reasoning fields keeps hidden chain-of-thought out of the text the agent acts on.
- **Alternatives:** Strict parsing (fails on common server variations); passing reasoning text through (pollutes the answer, costs context).
- **Consequences:** Each tolerated variation needs a test; new quirks found with real models are added the same way.

## AD-054: Never drop tools silently; models without native tool calling are refused

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** If a request has tools and the model is configured with `native_tool_calling: false`, the adapter raises `invalid_request` before any network call and says to use the text-action wrapper. The wrapper itself is P12.
- **Why:** A model that ignores tools but is asked to use them produces confusing, expensive runs; hiding that by silently sending the request without tools would look like the model "chose" not to call tools. FR13.8 requires the integration method to be reported, which only works if the method is explicit. The wrapper design (AD-051) keeps the fallback in one place.
- **Alternatives:** Implementing the JSON-action fallback inside this adapter (duplicates P12 and mixes two concerns); sending tools anyway (unreliable).
- **Consequences:** Until P12, the `local-free` placeholder (`native_tool_calling: false`) cannot run tool conversations. That is intended.

## AD-055: Error mapping, and what error messages may contain

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** HTTP and transport failures map to the stable adapter codes: context overflow (400 with context wording, 413) to `context_too_long`; 401, 402, 403 to `auth_failed`; 429 to `rate_limited` carrying `retry_after_s` from `Retry-After` (seconds or HTTP date); 408 and timeouts to `timeout`; 5xx to `server_error`; connection, DNS, TLS and dropped connections to `network_error`; other 4xx, including an unknown model (404) and 422, to `invalid_request`; redirects, non-JSON, wrong shapes, and errors embedded in a 200 response to `bad_response` or the code the embedded error maps to. Messages include the provider's own message shortened to 300 characters, and never the request body, headers, or key. Redirects are not followed.
- **Why:** The loop, queue, and failure classifier react to codes, not provider text (AD-049). The provider's message is the most useful detail ("model not found, try pulling it first"), but request content may be private and the key must never leak, so bodies and headers stay out. Not following redirects stops the Authorization header from travelling to another host. 402 is treated as an authentication/account problem because retrying cannot help.
- **Alternatives:** Passing the whole response body through (may echo private code); following redirects (key leak risk); mapping 402 to rate limiting (would retry forever).
- **Consequences:** Providers that signal context overflow in unusual wording may be reported as `invalid_request`; the wording list grows as real providers are met.
- **Added during the build (2026-11-01):** providers sometimes quote the credentials they were sent inside their own error text (OpenAI-style 401 messages do), and the provider's message is passed on, so the adapter redacts the API key and any `Bearer ...` token from provider text before it goes into an error. A base URL without a host is rejected when the adapter is built. Groq reports an over-large request (too many tokens per minute) as HTTP 413, which maps to `context_too_long`; the right response is to send less context, which is also what that code tells the loop.

## AD-056: Estimate and flag token usage when a server reports none

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** When a response has no usable `usage`, the adapter fills it from its own estimate (prompt estimate for input, response length for output) and sets a new optional field `usage_estimated: true` on `GenerationResponse`. The field is included in the JSON form. `SCHEMA_VERSION` stays 1 because nothing has been recorded yet, so there is nothing to migrate.
- **Why:** Reports must say which numbers were measured and which were estimated (README: report real numbers, measured claims only), and token statistics for free models would otherwise read as zero (FR14.6). The owner chose this option.
- **Alternatives:** Reporting zeros (silently wrong statistics); raising an error (a free local server that omits usage would be unusable).
- **Consequences:** Cost tracking (P11) and reports must carry the flag through. If recordings existed already, adding a field would need a version bump; this is the last cheap moment to extend the format.

## AD-057: Groq as the first free hosted model; unverified until its own pages are read; public repos only

- **Date:** 2026-11-01 · **Phase:** P9 · **Status:** Accepted
- **Decision:** Add a `groq-free` model entry (OpenAI-compatible base URL, `api_key_env: GROQ_API_KEY`, prices 0, `allow_private_code: false`) with every model-specific value marked `confirm`. The live check runs when the owner supplies a key, and is opt-in. P9 can merge before that, with the live check stated as not run if so. The owner chose Groq over OpenRouter and local Ollama.
- **Why:** The adapter is generic, so merging does not depend on the provider, and the owner has no key yet. The only information found about free tiers came from third-party pages and showed tight limits that matter for an agent (reportedly about 8,000 tokens per minute and 200,000 per day on one Groq model; 50 requests per day on OpenRouter free models until about $10 of credits are bought), so nothing about model names, limits, or data terms is claimed as verified. FR14.9 says free hosted tiers may use prompts for training, so they only receive public repos and sandbox issues until their terms are confirmed.
- **Alternatives:** Waiting for a key before building (blocks the plan for no code reason); OpenRouter (daily cap too small without a top-up); local Ollama (needs a large download and gives weaker tool calls; remains an option later).
- **Consequences:** Whether Groq's free tier can finish benchmark issues depends on the confirmed limits and on rate-limit handling in P51. The first real run must record the date and terms read from Groq's own pages.

---

## AD-058: The Claude adapter uses the official `anthropic` SDK with its retries off

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** `ClaudeAdapter` calls Claude through the official `anthropic` Python SDK, created with `max_retries=0`, the base URL from the model config, and the key passed in by the caller. SDK exceptions are mapped to the stable adapter codes; the API's own message, shortened and with credentials redacted, goes into the error.
- **Why:** The project's Claude API reference requires the official SDK for Python projects and says not to hand-roll HTTP. The SDK also tracks API-version headers and request shapes, which have changed several times (this very phase met the removal of sampling parameters). That differs from the OpenAI-compatible adapter (AD-052), where many unrelated servers share only a loose protocol and a small direct client is the better fit. The SDK retries 408, 409, 429, and 5xx by default; switching that off keeps AD-049 true (adapters raise immediately, retry policy lives in one place later, P51) and keeps every call visible in cost accounting.
- **Alternatives:** Raw `httpx` calls (we would own version and shape drift); leaving SDK retries on (hidden repeated paid calls and an unclear rate-limit story).
- **Consequences:** One more dependency, with its own HTTP stack. Tests must mock at the SDK's HTTP layer. The SDK's error types and attributes are part of what the adapter relies on and are covered by tests.
- **Added during the build (2026-11-01), SDK 2.3.0:**
  - It authenticates with an `Authorization: Bearer` header, not `x-api-key`, and sends API version `2026-10-21`. `messages.create` has no `temperature`, `top_p`, or `top_k` argument at all.
  - Given no key it silently uses `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or a saved profile from the environment, so `ClaudeAdapter` refuses to be built without an explicit key (nothing is read from the environment). With an explicit key and base URL, ambient credentials are ignored; tests prove it.
  - Its default HTTP client follows redirects, which could carry the key elsewhere, so the adapter supplies a client with redirects off.
  - The SDK's error `message` repeats the whole response body, so error text is built from the parsed `error.message` field instead.
  - For a malformed 200 response it returns odd objects instead of raising (a `str`, a `list`, a `Message` with `content=None`, even an error body parsed as a `Message`). Without a check these would have passed as an empty success, so the adapter validates every result and maps an error body inside a 200 by its error type.

## AD-059: Temperature is optional in the interface; Claude accepts only its default (amends AD-046)

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** `GenerationRequest.temperature` is `None` by default, meaning "the provider's own default"; numbers from 0 to 2 are still allowed. The Claude adapter never sends a sampling parameter. It accepts `None` or exactly `1.0` (Claude's default) and rejects any other value with `invalid_request` before the network call. The OpenAI-compatible adapter sends temperature only when one is given. Model comparisons (FR13.2) therefore run every model at the provider default or at 1.0, and say so in the report.
- **Why:** Claude Haiku 5.5 rejects any other value (a 400 on the current API version rules), so the old default of 0.0 could not be honoured. Silently ignoring a requested value would give Claude a different temperature from the other models without anyone noticing, which breaks the like-for-like rule of FR13.2 and mission principle 8 (measured claims only). An explicit error plus a shared default keeps the comparison honest. The owner chose this option.
- **Alternatives:** Keep 0.0 as the default and let Claude ignore it (hidden confounder); pin an older API version (still limited to 1, and a version we would have to maintain).
- **Consequences:** Runs are no longer near-deterministic by default; replay (P23) removes that problem for repeated experiments, because recorded responses are reused. Free models may behave less consistently at temperature 1.0 than at 0. Whether to compare at 1.0 for all models is decided at the comparison phase.

## AD-060: Thinking is turned off in P10; pass-through comes in a separate phase

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** Every request sets `thinking: {"type": "disabled"}`, which Haiku 5.5 accepts at its default effort. Thinking blocks never enter the conversation. Keeping provider-specific thinking blocks in the history (so thinking can be on during tool loops) is a new roadmap phase, P10b, and thinking on versus off becomes one of the measured experiments.
- **Why:** With thinking on, the API requires the thinking blocks to be passed back unchanged between tool calls, which the neutral message format has no block for, and editing any earlier turn afterwards (for example trimming old tool output to save context, FR14.8) makes the API return a 400 on newer accounts. Adding all that would turn P10 from a small adapter into a format change across recordings, replay, and context handling. The roadmap asks for very small phases, and the README plans before-and-after experiments, which this fits. The owner chose this option.
- **Alternatives:** Thinking on with an opaque pass-through block now (better reasoning from the start, a much larger phase and a trimming hazard).
- **Consequences:** Haiku's reasoning is weaker than it could be until P10b, so the first baseline numbers understate it; reports must say thinking was off. Claude models that cannot run with thinking disabled (Opus 5.5, Fable) fail with the API's own error until P10b.

## AD-061: Prompt caching modes: `auto`, `explicit`, `off`

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** A `prompt_caching` model setting (default `auto`) controls caching. `auto` sets the API's top-level cache control, so the growing conversation prefix is cached on each call, and also honours the `cache` flags callers put on text blocks. `explicit` honours only those flags. `off` sends no markers, even where flagged. No more than four markers are sent per request; if more are flagged the last ones are kept, because a later marker covers everything before it. Cache effectiveness is read from the cache-read and cache-write token counts in `Usage`.
- **Why:** README cost rules put caching on from day one, and a cache hit costs a tenth of normal input on Haiku 5.5, which matters in an agent loop that resends a long, mostly unchanged prefix 10 to 30 times per issue. `auto` removes the risk that the loop forgets to place markers, which would lose money silently. `off` and `explicit` exist because README experiment 3 (caching on or off, measured on cost) needs a switch, and because debugging is easier with caching removed. The owner chose `auto`.
- **Alternatives:** Explicit markers only (control, but silent waste when forgotten); always on with no switch (no experiment possible).
- **Consequences:** Cache writes cost 1.25 times the input rate, so very short or one-off calls can cost slightly more with caching on; the minimum cacheable prefix is about 512 tokens and shorter prompts simply do not cache. The setting is ignored by providers without prompt caching.

## AD-062: `refusal` is a normalised stop reason

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** Add `refusal` to the normalised stop reasons. The Claude adapter maps a safety decline to it and keeps the category in the raw value (for example `refusal:cyber`). The OpenAI-compatible mapping of `content_filter` stays `other`.
- **Why:** Haiku 5.5 runs safety classifiers that can decline a request with a normal HTTP 200 and no server-side fallback, so the loop must be able to tell "the model declined" from "the model finished" or "something else happened", for the stop condition and for failure analysis (FR11). Hiding it under `other` would make that distinction depend on parsing a raw string.
- **Alternatives:** Mapping to `other` (loses the signal); an exception (a decline is a valid response, and the partial text may matter).
- **Consequences:** The agent loop (P16) must decide what to do on a refusal (stop and record it, per the README's honesty rules). The set of stop reasons is part of the recorded format, so this is added before any recording exists.

## AD-063: Haiku 5.5 values verified from the official pages; tier modelling deferred; placeholder error corrected

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** `config/models.yaml` now records the official Haiku 5.5 figures with their source and the date read: model ID `claude-haiku-5-5`, 1M context, $0.10 per million input tokens and $0.50 per million output tokens (for prompts up to 100,000 tokens). The higher rates for prompts over 100,000 tokens ($0.50 and $2.50), and the cache read and write prices, are written in comments and modelled in P11. The earlier placeholder values ($1 and $5) were Claude Haiku 4.5's.
- **Why:** The README budget (5 USD) and the per-issue cap depend on correct prices, and the owner asked for them to be confirmed. The earlier values came from memory and were ten times too high for ordinary prompts; the error is recorded here so no earlier note is trusted. A single price field cannot express a price that changes with prompt length, and cost tracking is the phase that owns that.
- **Alternatives:** Using the higher over-100K prices as a conservative single price (overstates cost five times for normal runs and hides the real budget room); modelling tiers inside P10 (belongs to P11).
- **Consequences:** Until P11, a prompt over 100K tokens is underestimated by about five times, so agents must keep prompts small (FR3.4), and any run that exceeds 100K must be treated as unreliable on cost. Prices must be re-checked before each paid benchmark run, with the date recorded.

## AD-064: One shared module for HTTP-adjacent safety helpers

- **Date:** 2026-11-01 · **Phase:** P10 · **Status:** Accepted
- **Decision:** The Retry-After parser, the provider-message shortener, and the credential redaction move from the OpenAI-compatible adapter into `bugbite/adapter/_http.py`, used by both real adapters. The old import path keeps working.
- **Why:** Redaction and length limits are safety code; two slightly different copies would drift. The Claude adapter needs exactly the same behaviour, and the second user is the moment to share.
- **Alternatives:** Copying the code (drift); importing from the OpenAI-compatible module (couples two unrelated adapters).
- **Consequences:** One place to change and test. Both adapters' tests keep covering the helpers through their own error paths.

---

## AD-065: Prices live in a nested `pricing` block, in dollars per million tokens (replaces the flat per-token fields)

- **Date:** 2026-11-01 · **Phase:** P11 · **Status:** Accepted (supersedes the flat price fields of AD-050's `ModelConfig`; refines FR14.3)
- **Decision:** Each model has a required `pricing` block holding input, output, cache-read, and cache-write rates in US dollars per million tokens, an optional `long_prompt` rate card (a threshold in tokens plus its own four rates), and provenance: `as_of` (a date) and `source`. Free models write explicit zeros. Rates are read as exact decimals. A paid model must state `as_of`; a `claude` model must state both cache rates. The old fields `price_per_input_token` and `price_per_output_token` are removed from the file format, and read-only helpers with those names stay on `ModelConfig` (dollars per single token) for any code that only reads them.
- **Why:** Providers publish prices per million tokens, so numbers like `0.125` can be checked against their pages by eye, where `0.000000125` hides a misplaced zero. Cache prices and the over-100,000-token tier (found in P10 to make the earlier single-price config wrong by a factor of up to five) need more than two fields. Recording `as_of` and `source` supports the README rule to note the date and terms used for each run and makes stale prices detectable. Requiring cache rates for Claude stops a silent fall-back to the input price, which would under-bill every cache write. The owner chose this option.
- **Alternatives:** Keeping flat per-token fields and adding four to six more of them (hard to read and check).
- **Consequences:** Every place that built a `ModelConfig` or read the old fields changed in this phase. A forgotten `as_of` on a paid model is a load-time error rather than a silent guess. Prices still have to be re-read from the provider before each paid run; the config cannot know when they change.

## AD-066: A call's rate card is chosen by its prompt length, counting cache tokens

- **Date:** 2026-11-01 · **Phase:** P11 · **Status:** Accepted
- **Decision:** For each call, the prompt length is the sum of input, cache-read, and cache-write tokens. If a `long_prompt` card exists and the prompt length is greater than its threshold (not equal to it), the whole call, including output and cache tokens, is priced on that card; otherwise on the standard card. Each component costs its tokens times its rate divided by one million. Every call is priced on its own.
- **Why:** This is how the provider states it bills Haiku 5.5: "a request's prompt length counts all of its input tokens, including cache reads and cache writes. Each request is priced on its own: a request over the threshold pays the higher prices even when part of its prompt is a cache hit." Pricing by the same rule is the only way the ledger can match the invoice. The strict "greater than" follows the page's wording "over 100,000 tokens".
- **Alternatives:** Pricing by input tokens only (undercounts when most of a long prompt is cached); a single blended rate (wrong in both tiers).
- **Consequences:** A single long prompt in an otherwise cheap run is visibly expensive in the ledger (the tier is recorded per call). Context handling (FR3.4, FR14.8) matters for cost as well as for fit.

## AD-067: Cost is attached by a metering wrapper and a ledger, not by changing responses

- **Date:** 2026-11-01 · **Phase:** P11 · **Status:** Accepted
- **Decision:** `MeteredAdapter(inner, ledger)` is itself a model adapter. It records every call to a `CostLedger` (tokens, tier, cost, latency, request id, stop reason; a failed call is recorded with its error code and no cost) and returns the inner adapter's response object unchanged. `create_adapter(..., ledger=...)` builds the wrapped form. The ledger is in memory and thread-safe, and offers a JSON-safe snapshot for the trace store to save later.
- **Why:** One wrapper covers every adapter now and in the future (including the text-action wrapper in P12), so cost accounting cannot be forgotten or implemented twice. Leaving the response type alone keeps recordings provider-neutral and free of price data that may later turn out stale: cost can be recomputed from recorded usage with the prices of the time, which is what re-scoring old runs (FR10.3) needs. A shared ledger gives totals across models for the budget counter (FR13.6). The owner chose this option.
- **Alternatives:** A `cost` field on every response (each adapter computes it, recordings carry a price that can be wrong, repricing means rewriting recordings).
- **Consequences:** The loop must be given the metered adapter, which entry points do through `create_adapter`. Persisting the ledger waits for the trace store (P21).
- **Added during the build (2026-11-01):** a request the adapter refuses *locally* (a malformed conversation, a temperature the model does not accept, tools for a model without native tool calling) never reaches the provider, so it is not a model call and is not recorded as a failed one; recording it would inflate failure counts. The wrapper tells the two apart by the error: `invalid_request` without an HTTP status is a local refusal, while a provider's own 400 carries its status and is recorded. Timeouts, network errors, rate limits, and server errors are recorded. Stored money is written in one canonical plain-text form (no exponent, no trailing zeros), because the same amount summed in a different order printed as `0.00030` instead of `0.0003`.

## AD-068: P11 measures; it offers a worst-case projection and enforces nothing

- **Date:** 2026-11-01 · **Phase:** P11 · **Status:** Accepted
- **Decision:** The ledger enforces no cap. `worst_case_cost(pricing, prompt_tokens, max_output_tokens, margin=1)` returns the most a call could cost: every prompt token at the larger of the input and cache-write rates, every allowed output token at the output rate, on the rate card the projected prompt size selects. Per-issue, per-batch, and per-model caps stay with the agent loop (P17) and the spend-control phase (P46).
- **Why:** The roadmap assigns enforcement to those phases, and enforcement drags in questions that do not belong here (what happens to the job, how it is labelled, how batches share a budget). A hard cap that stops before the call that would break it needs a conservative projection, so the primitive is provided now while the policy waits. The `margin` argument exists because the four-characters-per-token estimate is known to undercount on newer tokenizers; the right value should come from real usage data (P47), not a guess today. The owner chose this option.
- **Alternatives:** Enforcing a per-issue cap in the ledger now (an early safety net, but it pulls loop and batch design into a small phase).
- **Consequences:** Until P17 and P46 exist, nothing stops a run from spending beyond 0.10 USD; no paid run is made before then (the first is the Haiku spike, P47).

## AD-069: Money is `Decimal` end to end

- **Date:** 2026-11-01 · **Phase:** P11 · **Status:** Accepted
- **Decision:** Rates, component costs, totals, and projections are `Decimal`. YAML numbers are converted through their text form, so `0.10` is exactly one tenth. Snapshots store money as strings.
- **Why:** Individual call costs are fractions of a micro-dollar and totals will be compared against hard caps and a 5 USD budget; binary floats make sums depend on order and can land a hair on the wrong side of a cap. Exact decimals make "stop when the cap is reached" a plain comparison and make totals identical however they are summed. Strings in snapshots avoid precision loss in JSON.
- **Alternatives:** Floats (small errors accumulate and comparisons surprise); integer micro-dollars (cannot represent a single token at $0.10 per million without rounding).
- **Consequences:** Code that wants a float for display converts explicitly. Slightly more verbose arithmetic.

---

## AD-070: The text-action fallback is a wrapper adapter, applied automatically to non-native models

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted (realises AD-051)
- **Decision:** `TextActionAdapter(inner)` is itself a model adapter. It takes a request with tools, sends the inner adapter a text-only version, and turns the reply into the tool call (or final answer) the caller expected. `create_adapter` builds it for any model with `native_tool_calling: false`; native models are untouched. A request without tools passes through unchanged.
- **Why:** The agent loop and every other caller must not know which kind of model they talk to (FR14.1, FR5.3); a wrapper keeps all text-action logic in one place and works over any adapter, present or future. P9 deliberately refuses tools for non-native models (AD-054) so that this conversion is explicit rather than silent. Wiring it in `create_adapter` means entry points cannot forget it.
- **Alternatives:** A flag inside each adapter (duplicated logic); having the loop handle both styles (leaks the difference everywhere).
- **Consequences:** The integration method (native or text action) is still reported per model from the config (FR13.8). Callers who build adapters by hand must wrap non-native models themselves.

## AD-071: One JSON action per reply; tolerant extraction; prose-only replies are invalid

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted
- **Decision:** A reply must contain exactly one action, written as `{"tool": "<name>", "arguments": {...}}` or `{"final": "<text>"}`. The parser finds the JSON object in the reply wherever it is: prose around it and code fences are ignored (the prose is kept as text). Several different actions, an object with both keys, no action at all, or prose only are invalid and go to the repair step. Other keys in the object are ignored. The instruction prompt carries a version number.
- **Why:** FR14.4 asks for one action per turn. Small models routinely add commentary, wrap output in fences, or forget the format; rejecting all of that would waste steps, while accepting a chatty reply as "the final answer" would let a model that simply forgot the format end the job early and hide the failure. Extracting the action and treating anything without one as invalid avoids both. The owner chose this option over strict-only and over prose-as-final. Recording the prompt version supports FR10.4.
- **Alternatives:** Strict JSON-only (more failed steps); prose counts as the final answer (premature endings).
- **Consequences:** Models that put the action somewhere unexpected (a reasoning field, tool-call markup) appear as having no action until a real model shows what is needed. Any change to the prompt must bump the version, since it changes behaviour.
- **Added during the build (2026-11-01):** the first scanner reported "the JSON has no action" for a reply with a trailing comma or a missing comma, because after the outer object failed to parse it decoded the inner `arguments` object on its own and called that "JSON without an action". That hid the real problem and would have sent the model a useless repair hint. When a fragment that fails to parse looks like an attempted action (it contains a `tool` or `final` key, in any quoting), the parser now reports the JSON error with its line and column instead. Prompt text was tightened before any use, so the version stays 1.

## AD-072: One repair attempt, then a recoverable failed step

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted
- **Decision:** An invalid reply gets exactly one repair attempt: the same request, plus the bad reply and a short message saying what was wrong and how to answer. If the repaired reply is also invalid, the step has failed and the response contains a tool call named `invalid_action` with empty arguments and an `error` describing the problem, plus the model's last reply as text, with stop reason `tool_use`. Nothing is raised. Adapter errors and refusals are never repaired. The wrapper counts steps, repaired steps, and failed steps.
- **Why:** This is exactly what FR14.4 specifies, and the shape follows the recoverable-step design of AD-048: the loop answers the call with an error result, counts a failed step against its cap, and the model sees its mistake on the next turn, whereas raising an error would blur a model mistake with a provider fault and give the model no chance to correct itself. A second repair would spend more money on a model that is unlikely to fix it. Repairing a provider failure or a refusal would be pointless. The counters make the model comparison able to report how often each model needed help (FR13.5). The owner chose this option.
- **Alternatives:** Raising `bad_response` (conflates failure kinds); unlimited or two repairs (cost, with diminishing returns).
- **Consequences:** The loop (P16 to P18) must answer `invalid_action` calls with the call's `error` as the tool result. The step cap and loop detection decide how many failed steps are tolerated.

## AD-073: Arguments are checked with the `jsonschema` library

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted
- **Decision:** Tool-call arguments are validated against the tool's parameter schema with the `jsonschema` package (Draft 2020-12), and the best-matching error, with its path, goes into the repair message. A tool whose own schema is invalid is refused locally before any model call.
- **Why:** A model can only fix an argument mistake if told precisely what is wrong ("`arguments.path`: 'x' is not of type 'integer'"). The library implements the whole schema language correctly, so any tool added later is checked properly without further code, and its error messages are well tested. A hand-written checker would cover only today's six simple tools and silently skip anything fancier. The owner chose this option over a small built-in checker and over name-only checks.
- **Alternatives:** A built-in subset checker (no dependency, silent gaps); name-only (mistakes surface as tool errors without repair).
- **Consequences:** One new pure-Python dependency. The same check could later validate native tool calls too, which is a separate decision.

## AD-074: Each model call is its own ledger entry; the step's response carries the sum

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted
- **Decision:** Metering sits inside the wrapper: `create_adapter` builds `TextActionAdapter(MeteredAdapter(raw))`. The original call and a repair are therefore two ledger entries. The response handed to the caller reports the summed tokens, latency, and estimated flag of the whole step, with the model and request id of the last call. Metering outside the wrapper is not supported (it would count the step once and hide repairs).
- **Why:** Cost must be exact: a repair is a real paid call. Separate entries let reports count repairs and cost them on their own, which the comparison of models (FR13.5) needs, while the summed response lets the loop and per-step statistics see what one step cost. The owner chose this option over one combined entry.
- **Alternatives:** One entry per step (tidier, but repairs become invisible).
- **Consequences:** The ledger's call count for a non-native model is higher than the loop's step count by the number of repairs; the wrapper's counters explain the difference.

## AD-075: How tool conversations are shown to a text-only model

- **Date:** 2026-11-01 · **Phase:** P12 · **Status:** Accepted
- **Decision:** In the text version of the history, a tool call is shown as its JSON action; an assistant message with no call is shown as a `{"final": ...}` action; a tool result is shown as text naming the tool and the call id, with errors marked. A failed step is shown as the model's own failed reply followed by a user message saying the reply was not a valid action, and the `invalid_action` call itself is never shown as an action. Call ids are `ta_<n>` with n one more than the number of tool calls already in the conversation, so they are unique and identical histories give identical ids.
- **Why:** Showing history in the same format the model must produce keeps it on format. Hiding `invalid_action` stops the model learning that name as a valid thing to write. Deterministic ids keep recordings reproducible and replay exact (FR10.5), and numbering from the history avoids any hidden counter state in the wrapper.
- **Alternatives:** Describing history in prose (the model drifts from the format); random ids (breaks replay).
- **Consequences:** The text history is longer than a native one, which costs tokens on every call; this is part of the price of the text-action method and shows up in the comparison.

---

## AD-076: Two independent locks: a check at job start and a guard at the model boundary

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** The rule is enforced in two places. `check_job_privacy` runs when a job starts and refuses a job whose data the chosen model may not receive, with a clear message and before any work or cost. `PrivacyGuardAdapter` wraps the raw model adapter as the innermost layer and refuses every individual call that is not allowed. `create_adapter` takes the data's `Sensitivity` and defaults to `PRIVATE`, so forgetting to say what the data is makes a model that cannot take private code refuse rather than leak.
- **Why:** The acceptance criterion is absolute ("private code is never sent to a provider that is not marked as allowed"). A start-time check alone can be skipped by a code path nobody remembered to wire; a call-time check alone makes the job fail only after setup and sandbox time were spent, with a less helpful message. Together they give an early explanation and a lock that cannot be bypassed. Innermost placement means the metering and text-action layers, including repair calls, can only reach the network through the guard. The owner chose this option.
- **Alternatives:** Job-start only (a missed code path leaks); boundary only (late and unfriendly failure).
- **Consequences:** Every adapter built for a job must be told the data's sensitivity. A job that is refused at the boundary rather than at start indicates a missing start check.

## AD-077: Public repos and the owner's sandbox list may go to any model; everything else is private

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** A job's data is `PUBLIC` when GitHub reports the repo as public, `SANDBOX` when its name is on the owner's `sandbox_repos` list in `config/app.yaml` (private or public), and `PRIVATE` otherwise. Unknown or missing visibility is `PRIVATE`. The name compared is the canonical one returned by the GitHub API (`RepoInfo.full_name`), case-insensitively and exactly, never the text the user typed. The list starts empty.
- **Why:** This is FR14.9's own wording ("public repos and sandbox issues"). Failing closed on anything uncertain is the only safe direction for a rule about leaking code. Using the API's canonical name matters because the user-typed name can differ in case or point at a redirect, and P3 already refuses jobs where the API name differs from the requested one. The owner chose public plus an owner-set list over public only, because their own demo and test repos should be usable with the free tier even if private. The key is called `sandbox_repos` (matching the README's term for demo repos) with a comment saying it is unrelated to the Docker sandbox.
- **Alternatives:** Public only (stricter, but private demo repos could not use free tiers); letting each job declare its own sensitivity (a user mistake could leak).
- **Consequences:** Entries in `sandbox_repos` are trusted completely: anyone who can edit the file can widen what free tiers see. It lives in version-controlled config on purpose.

## AD-078: A blocked job is refused with a clear message; no switching and no override

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** When a model may not receive the job's data, the job is refused with a `PrivacyError` whose message names the model and the repository and lists the configured models that would be allowed (or says that none is). The system never switches models by itself, and no flag, environment variable, or argument turns the rule off. The only way to change who may receive private code is editing `allow_private_code` in `config/models.yaml`.
- **Why:** A silent switch would run the job on a model the user did not choose, distorting benchmark comparisons (FR13.2) and possibly spending money unexpectedly. An override flag would turn an enforced rule into a convention, and the acceptance criterion says "never". Editing the config is deliberate, reviewable, and recorded in version control. The owner chose refusal.
- **Alternatives:** Automatic fallback to an allowed model; a `--force` style override.
- **Consequences:** A user with a private repo and only non-allowed models configured must change configuration or pick another model. The message states this plainly.

## AD-079: `PrivacyError` is its own error family

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** Privacy refusals raise `PrivacyError` (code `private_code_blocked`), which is not an `InputError` and not an `AdapterError`. The metering wrapper does not record it as a model call (nothing was sent), and the text-action wrapper does not try to repair it.
- **Why:** Code that catches `AdapterError` to retry or fall back, or `InputError` to show a friendly message, must not treat a policy refusal like a provider hiccup or a typo. Keeping it separate means such handlers cannot swallow it by accident, and the agent loop can recognise it and stop the job as aborted for a stated reason (FR8.3).
- **Alternatives:** Reusing `InputError` (a user can fix it, but mid-job retry logic might catch it); a new `AdapterError` code (retry policies key on adapter errors).
- **Consequences:** The loop and job manager must handle `PrivacyError` explicitly (abort with a reason).

## AD-080: Haiku stays `allow_private_code: false`

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** `haiku` keeps `allow_private_code: false`; `groq-free` is `false`; `local-free`, which runs on the owner's machine, is `true`. A comment in the model config records that changing a model's value is the owner's decision after reading the provider's current data terms.
- **Why:** Whether Anthropic's API terms suit the owner's private code is a legal and trust decision that is theirs, not an engineering default, and the cautious value costs little: benchmarks and demos use public and sandbox repos. The README also asks for the date and terms to be recorded. The owner chose to keep it `false` for now.
- **Alternatives:** Setting `true` now (a policy choice that was not made).
- **Consequences:** Private repos can currently only be worked on with the local model, which cannot do tool calls well until it is real (P12 fallback) and has not been chosen yet (README question 4).

## AD-081: Concrete adapters are only built through `create_adapter`, enforced by a test

- **Date:** 2026-11-01 · **Phase:** P13 · **Status:** Accepted
- **Decision:** Outside `src/bugbite/adapter/`, no module may import the concrete adapter classes or modules. A test reads the source tree and fails if one does, and a second test proves the checker would catch a violation.
- **Why:** The guard only protects adapters that are wrapped in it. Anyone constructing a `ClaudeAdapter` or `OpenAICompatibleAdapter` directly would get an unguarded path to the network, and a rule that depends on every future author remembering is not a rule. A test makes the shortcut fail immediately in CI.
- **Alternatives:** Documentation only (forgotten under time pressure); making the concrete classes private (Python offers no real privacy, and tests need them).
- **Consequences:** Tests inside the adapter package and the `tests/` folder may still build concrete adapters; new production code cannot.

## AD-082: Agent tools run inside the sandbox

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted
- **Decision:** `read_file`, `list_directory` and `search_code` operate on the repo in the Docker sandbox using `Sandbox.run` and `Sandbox.read_file`. Host code never opens the repo's files for the agent.
- **Why:** Repo content and file names are untrusted. Keeping every read inside the hardened container (no host mounts, no credentials) keeps the existing isolation story simple, and matches FR5.2.
- **Alternatives:** Reading a host checkout (faster, easier tests, but a second copy of the repo outside the sandbox and a new path for hostile content).
- **Consequences:** Each call costs a container exec; unit tests use a fake sandbox and real behaviour is checked in opt-in Docker tests.

## AD-083: Tool output is capped, with a truncation notice

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted
- **Decision:** `read_file` returns at most 200 lines / 20,000 characters, `list_directory` 200 entries, `search_code` 50 matches of at most 200 characters each. When cut, the output says what was shown and how to ask for the rest.
- **Why:** FR3.4 forbids dumping the repo into the prompt, and every token is paid for on every later turn. A notice lets a model recover instead of silently acting on partial data.
- **Alternatives:** No caps (cost and context blow-ups); silent truncation (the model believes it saw everything).
- **Consequences:** The numbers are starting values; P17/P19 measurements may change them.

## AD-084: `search_code` uses grep in the sandbox, fixed-string by default

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted
- **Decision:** Search runs `grep -rnI` (with `-F` unless `regex` is true), excluded junk directories, and `--` before model-supplied text.
- **Why:** No new dependency, runs next to the files, skips binaries. Fixed-string avoids models tripping on regex escaping and avoids pathological patterns by default.
- **Alternatives:** A Python-side scan (reads far more through the sandbox); ripgrep (not in the image, would need installing).
- **Consequences:** Slower than an index on huge repos; indexed search arrives with the retrieval phases.

## AD-085: Tools are `Tool` objects returning `ToolOutput`, never raising into the loop

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted
- **Decision:** Each tool has a `ToolDefinition` and `run(arguments) -> ToolOutput(text, is_error)`. A registry validates arguments against the schema and turns unknown tools, bad arguments and unexpected exceptions into error results.
- **Why:** Models make bad calls routinely; the useful response is an error message they can act on, and the loop (P16) should not need try/except around every tool. One schema layer serves native and text-action adapters.
- **Alternatives:** Plain functions with schemas added in P16 (pushes the design to a later phase and risks two layers).
- **Consequences:** The loop converts `ToolOutput` into `ToolResultBlock`.

## AD-086: Tool paths are repo-relative, validated, and hide `.git`

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted
- **Decision:** Models pass paths relative to the repo root. Absolute paths, `..`, control characters and anything touching `.git` are rejected before reaching the sandbox.
- **Why:** The container is already isolated, but a model must not wander to `/workspace/.venv`, other workspace files, or git internals (which hold remote URLs and history noise), and clear rejection teaches it the right form.
- **Alternatives:** Trust the container only (less clear errors, more noise in context).
- **Consequences:** Symlinks inside the repo that point outside are tested in Docker; reads go through the same checks.

## AD-087: Paths are resolved and listed by a small Python script run inside the sandbox, not by `find`

- **Date:** 2026-11-01 · **Phase:** P14 · **Status:** Accepted (changes the plan, which said `find`)
- **Decision:** `list_directory` and the path check of all three tools call one fixed Python script in the container (`python -c SCRIPT root relative mode limit`) that resolves the path with symlinks followed, refuses anything outside the repo or inside `.git`, and returns JSON. `search_code` still runs `grep`.
- **Why:** A host-side check cannot see symlinks, and a repo can contain a symlink to `/etc`; only code inside the container can resolve it. `find -printf` is GNU-only, so the same tool would behave differently on the developer's Mac, where the unit tests run, and file names with newlines break line-based output. A script gives exact types, NUL-safe names and one code path in both places. The script is a constant, and model text reaches it only as separate arguments.
- **Alternatives:** `find`/`realpath -e` shell commands (non-portable, parsing fragile); doing it all host-side (blind to symlinks).
- **Consequences:** Relies on `python` being in the sandbox image (it is: the sandbox is built for Python repos). Unit tests run the same script on the host through a folder-backed fake sandbox; Docker tests prove the real behaviour.

## AD-088: `edit_file` is exact find-and-replace, and creates files when `old_text` is omitted

- **Date:** 2026-11-01 · **Phase:** P15 · **Status:** Accepted
- **Decision:** The model gives `old_text` and `new_text`; `old_text` must match exactly once. Omitting `old_text` creates a new file (which must not exist). Edits preserve line endings, the trailing newline and the file mode.
- **Why:** FR5.6 wants minimal edits. Replace-in-place keeps the change as small as the model's own text, costs few tokens, and fails loudly (zero or many matches) instead of guessing. Small models do this more reliably than writing diffs. Preserving mode, line endings and the final newline prevents noise in the patch that would count against the "minimal diff" goal.
- **Alternatives:** Whole-file rewrite (invites unrelated changes, expensive); unified diff (small models often produce invalid diffs); a separate `create_file` tool (a seventh tool beyond FR5.2's list).
- **Consequences:** The model must quote enough context to be unique; the error says how many matches there were. Multi-edit batching is left for later if needed.

## AD-089: Cheating guards sit in `edit_file` as code, with a caller-only allow list

- **Date:** 2026-11-01 · **Phase:** P15 · **Status:** Accepted
- **Decision:** `edit_file` refuses existing test files, test configuration, CI files and dependency pins, and refuses skip or xfail markers in test files the agent creates. The caller may pass exact paths to allow when the issue is about them; the model cannot.
- **Why:** FR6.5 requires these rules in code, not in the prompt, and the earliest place to stop a model from "fixing" a failing test by editing it is the tool. Stopping it at the tool also tells the model what to do instead, saving wasted steps. A caller-only switch keeps the legitimate case possible (an issue that really is about CI) without letting the model flip it.
- **Alternatives:** Verifier only (the agent wastes steps and the problem is found late); a model-visible override flag (defeats the purpose).
- **Consequences:** These guards do not cover changes made through `run_command`; the verifier phases (P33 to P36) must check the final patch independently. This is stated in the README as a known gap. Patch-size caps are not part of this phase.

## AD-090: `run_command` runs any shell command, contained by the sandbox

- **Date:** 2026-11-01 · **Phase:** P15 · **Status:** Accepted
- **Decision:** The command is a shell string run in the repo directory inside the sandbox, with a timeout (default and maximum from the sandbox config), capped output, a fixed environment (virtualenv first on `PATH`), and a refusal to run if the sandbox still has network access.
- **Why:** The container is already the boundary: non-root, capabilities dropped, no host mounts, no credentials, network cut after setup. Debugging needs pipes, redirects and varied tools, and an allow-list would block them and make small models stumble. The network check is a cheap extra lock so a setup mistake cannot give a model command execution with internet.
- **Alternatives:** An allow-list of programs (safer in theory, too restrictive in practice, and easy to bypass through `python -c` anyway); no network check (relies on setup order alone).
- **Consequences:** `run_command` is the one place model text is run as a shell command. It can modify files, including protected ones; see AD-089.

## AD-091: `run_tests` returns a compact summary, not raw pytest output

- **Date:** 2026-11-01 · **Phase:** P15 · **Status:** Accepted
- **Decision:** The tool runs the existing runner and returns status, counts, up to 15 failing or erroring IDs with one-line messages, up to 5 collection errors and a 1,500-character output tail when something failed.
- **Why:** The structured report already exists (P6); the model needs which tests fail and why, not pages of progress output, and every token is paid for on every later turn (FR3.4). The tail keeps the traceback visible when the one-line message is not enough.
- **Alternatives:** Raw output (large and noisy); full per-test details (large for big suites).
- **Consequences:** If the summary hides something a model needs, it can call `run_command` with pytest and its own options. Sizes are starting values for P20 to tune.

## AD-092: `max_steps` is required, with no default, until P17 adds the real caps

- **Date:** 2026-11-01 · **Phase:** P16 · **Status:** Accepted (owner agreed)
- **Decision:** `run_agent` requires a `max_steps` argument and has no default. It counts model calls. When the last allowed reply still asks for tools, the run ends as `max_steps` and those calls are not run.
- **Why:** The roadmap says "no caps yet", but a loop on a paid model with no way to stop is an unbounded spend if a model gets stuck, and every test or script would carry that risk. A required argument costs one line for the caller and cannot be forgotten. Not running the last reply's tools keeps the stop clean: nothing changes in the sandbox after the limit.
- **Alternatives:** No limit at all (literal reading of the roadmap); a default such as 50 (silently applied, and it would hide that the limit exists).
- **Consequences:** P17 replaces this with steps, cost and wall-clock caps and a proper stop reason; `max_steps` will stay as one of them.

## AD-093: Model failures end the run with a result, never an exception

- **Date:** 2026-11-01 · **Phase:** P16 · **Status:** Accepted (owner agreed)
- **Decision:** An `AdapterError` ends the run with status `model_error` and a `PrivacyError` with `privacy_blocked`. The result keeps the error code and message, all earlier steps and the conversation. The loop does not retry.
- **Why:** By the time a call fails the sandbox may already hold edits and the run has cost money; losing the record of that would make failures impossible to analyse (FR11) or replay. Adapters deliberately do not retry (P9, P10), so a retry policy belongs with the caps and spend control, where it can count cost. Privacy keeps its own status because it is a different kind of event from a provider failure (AD-079).
- **Alternatives:** Raise (loses the work done); retry inside the loop (hides cost, no policy yet).
- **Consequences:** Callers must check `status`. Programming mistakes (bad arguments) still raise.

## AD-094: The loop reports through an optional observer with typed events

- **Date:** 2026-11-01 · **Phase:** P16 · **Status:** Accepted (owner agreed)
- **Decision:** `run_agent` accepts an observer callback and sends `ModelCallEvent`, `ToolCallEvent` and `FinishEvent`. If the observer raises, the error is logged by type only, counted in `observer_errors`, and the run continues.
- **Why:** P21 (trace store) and P22 (recorder) must see every call as it happens, but they should not need to change the loop. A recorder failing in the middle of a paid job should not throw the job away; the count makes the gap visible to the caller, who can decide to discard the run.
- **Alternatives:** Only the returned result (recording happens after the fact, so a crash loses everything); letting observer errors propagate (loses the job over a logging fault).
- **Consequences:** Events carry full content, so observers must protect private code (AD-076 onward); the loop itself logs none of it.

## AD-095: The task is a plain string; the system prompt is versioned and built in

- **Date:** 2026-11-01 · **Phase:** P16 · **Status:** Accepted (owner agreed)
- **Decision:** `run_agent` takes the task as text. `format_issue_task(context)` builds that text from a fetched issue with size limits and clearly marked untrusted-data sections. The system prompt lives in `bugbite.agent.prompt` with `PROMPT_VERSION`.
- **Why:** The loop should work the same for a GitHub issue, an evaluation case and a hand-written test, and should not depend on GitHub types. A prompt version lets a recording say exactly which instructions were used (FR10.4) and lets comparisons across models be fair. Marking issue text as data and limiting its size reduces prompt-injection and token cost; it does not remove the risk, which is why the real defences stay in code.
- **Alternatives:** Passing a `JobContext` into the loop (couples it to GitHub, harder to test and reuse).
- **Consequences:** Changing the prompt means bumping `PROMPT_VERSION`. Pre-steps (P19) will add to the task text.

## AD-096: Tool calls in a reply cut off by the output limit are not run

- **Date:** 2026-11-01 · **Phase:** P16 · **Status:** Accepted
- **Decision:** If a reply ends because it hit the output token limit (`max_tokens`), the run ends as `truncated` and none of its tool calls are executed, even if they parse.
- **Why:** A cut-off reply can contain a tool call whose arguments were cut in the middle, for example an `edit_file` with half of the new text. Running it could write a broken file, and the model has no chance to notice. Stopping is the honest result; P17 or a later retry policy can decide whether to ask the model to continue.
- **Alternatives:** Run calls that parse (risky); ask the model to continue automatically (a policy and cost decision for later).
- **Consequences:** A model with too small an output limit will end runs early; the status makes this visible.

## AD-097: Limits are one `Limits` object, built from config by a helper; the cost cap is the lower of two config values

- **Date:** 2026-11-01 · **Phase:** P17 · **Status:** Accepted (owner agreed)
- **Decision:** `run_agent` takes `limits=Limits(max_steps, max_cost_usd, max_wall_clock_s, cost_margin)` instead of a `max_steps` argument. `limits_from_config(app, model)` fills it: steps and time from `config/app.yaml`, cost as the lower of `app.max_cost_usd` and the model's `per_issue_cap_usd`.
- **Why:** There are two cost values in the config (a global job cap and a per-model cap) and the README asks for both ("hard cap per issue, set per model"). Combining them in one tested place means no caller can apply only one. A single object also gives later phases (batch caps, the CLI, evals) one thing to pass around and record. Costs are `Decimal`s built from text so `0.1` stays exact.
- **Alternatives:** Separate keyword arguments (every caller combines the config values itself); keeping `max_steps` and adding more arguments (more places to forget one).
- **Consequences:** The P16 `max_steps=` argument is gone (no callers outside tests yet). Config values the loader allows but a limit cannot use (zero steps, zero time) fail with a message naming the field.

## AD-098: The cost cap is checked before every model call, using the worst case

- **Date:** 2026-11-01 · **Phase:** P17 · **Status:** Accepted (owner agreed)
- **Decision:** Before each model call the loop adds the worst case for that call to the job's spend and stops with `cost_cap` if the sum is above the cap. The worst case is the adapter's `worst_case_cost` (estimated prompt scaled by `cost_margin`, default 1.25, at the dearest rate; the full output limit at the output rate) multiplied by the model calls one step can make (`max_calls_per_step`, 2 for text-action models). After the call the loop checks the real spend again before running tools. A cost cap requires the ledger of a `MeteredAdapter` in the chain, checked before the first call.
- **Why:** The README says the cap must stop the run and not the credit card. Checking only after a call lets a job overshoot by a whole call; checking before, with a deliberately pessimistic estimate, keeps the real spend under the cap unless the estimate itself is wrong, and the post-call check then catches that and says so. If cost cannot be measured the safe answer is to refuse to start, so a missing or unattached ledger is an error. The text-action repair is a second paid call inside one step, so it is counted.
- **Alternatives:** Stop after the call that crosses the cap (simpler, can overspend); use only the typical cost (can overspend).
- **Consequences:** Jobs may stop a little early because the worst case is pessimistic. The 1.25 margin is a guess to be calibrated with real usage (P20, P46). A reply that arrives over the cap but is a final answer is still returned as `finished`, with the overshoot reported, because the money is already spent and the answer is usable.

## AD-099: The wall-clock cap is checked before every model and tool call, and tools get the time left

- **Date:** 2026-11-01 · **Phase:** P17 · **Status:** Accepted (owner agreed)
- **Decision:** The loop uses a monotonic clock started at the call. It checks the time before every model call and before every tool call. `run_command` and `run_tests` receive `time_limit_s` and use the smaller of their own limit and the time left, and are not started with less than a second left. Tool calls that cannot start are answered with a "not run" result and the run ends with `time_cap`. The clock is injectable for tests.
- **Why:** The default time cap is 600 s but a full test run may take 300 s and a command 120 s. Checking only between steps would let a job overshoot by most of a cap; clamping the tools keeps the overshoot to what cannot be interrupted: one model call (bounded by the adapter's timeout) and one read-only tool call (at most 30 s). Answering skipped calls keeps the conversation valid for a recording or a later resume.
- **Alternatives:** Check only between steps (simple, large overshoot); run the model call in a thread and abandon it at the deadline (a call that keeps running and costing money after the job has stopped is worse).
- **Consequences:** Every tool now takes `time_limit_s`; a custom tools object without it would fail, which the loop reports as a tool error.

## AD-100: `cost_cap` and `time_cap` are stop reasons, and the result reports cost, time and detail

- **Date:** 2026-11-01 · **Phase:** P17 · **Status:** Accepted
- **Decision:** `AgentResult` has the new statuses `cost_cap` and `time_cap`, plus `cost_usd`, `elapsed_s` and `limit_detail` (one sentence naming the limit, its value and what was used). When several limits are reached together, time wins over cost and cost over steps.
- **Why:** Failure analysis (FR11) and the dashboard must tell "ran out of money" from "ran out of time" from "ran out of steps", and a person reading a report needs numbers, not just a label. A fixed order makes results reproducible.
- **Alternatives:** One `limit_reached` status (loses the reason); reusing `model_error` (a cap is not an error).
- **Consequences:** Anything switching on `status` must handle the new values.

## AD-101: Loop detection uses two exact rules, and a successful edit starts the count again

- **Date:** 2026-11-01 · **Phase:** P18 · **Status:** Accepted (owner agreed)
- **Decision:** Rule 1 flags the same tool call (same name, same arguments) returning the same result again and again. Rule 2 flags failed `edit_file` calls to the same file piling up, even with different text. Any successful `edit_file` clears all counts.
- **Why:** These are the two ways small models are known to get stuck: repeating a call that cannot change, and guessing the wrong `old_text` over and over. Exact rules can be explained to a user, replayed, and tested; fuzzy "looks similar" matching would also stop legitimate work. Restarting the count after a real change matters because the normal fix loop (edit, run the tests, see the same failure, edit again) repeats the test call with an identical result while genuinely making progress.
- **Alternatives:** Only repeated failed edits (misses a model re-reading a file or re-running a command); alternating-pattern detection (needs fuzziness, better tuned on real traces in P60).
- **Consequences:** A model that re-reads one file three times without editing gets a nudge. Streaks of invalid actions and generic tool errors are not covered yet.

## AD-102: Nudge once, then stop; thresholds are defaults in a `LoopPolicy`

- **Date:** 2026-11-01 · **Phase:** P18 · **Status:** Accepted (owner agreed)
- **Decision:** At the first threshold (3 repeats, or 4 failed edits to one file) the model is told it is repeating itself. At the second (5 repeats, or 6 failed edits) the run ends with `loop_detected`. The note is appended to the last tool result of the step. `LoopPolicy` holds the numbers; `loop_policy=None` turns detection off.
- **Why:** FR5.5 says "change strategy or stop". One nudge costs only a few tokens in the next prompt and gives a model a chance to recover; stopping after it keeps the "agent loops forever" risk closed without relying on the cost and time caps to end a stuck run. A tool result is the one place both native and text-action models are guaranteed to read, and adding text to it avoids a second consecutive user message, which the request check forbids.
- **Alternatives:** Stop immediately (gives up runs a nudge could save); nudge only (a stuck model burns money until a cap).
- **Consequences:** The numbers are guesses to be tuned in P60. The recorded `ToolRun` keeps the real output; only the conversation carries the note, and `Step.nudge` records it.

## AD-103: `loop_detected` is a stop reason; time wins over it; the conversation stays valid

- **Date:** 2026-11-01 · **Phase:** P18 · **Status:** Accepted
- **Decision:** After a stop signal the step's tool results are still added to the conversation, then the run ends as `loop_detected` with a sentence naming the rule and the count. If the time limit has also been reached the status is `time_cap`.
- **Why:** The result is more useful for analysis (FR11, "agent loop detected" is a planned failure class) when it says why it stopped, and keeping every tool call answered means the recording can be replayed or resumed. Time already wins over cost and cost over steps (AD-100); a loop stop is decided only after the tools ran, so it ranks just after them.
- **Alternatives:** Dropping the last results on a stop (breaks the conversation); reusing `max_steps` (hides the cause).
- **Consequences:** Anything switching on `status` must handle `loop_detected`.

## AD-104: The detector is a pure class that sees one executed tool run at a time

- **Date:** 2026-11-01 · **Phase:** P18 · **Status:** Accepted
- **Decision:** `LoopDetector.observe(run)` returns a `Signal` and keeps small counters (output text only as a hash). It ignores runs that were not executed. The loop only acts on the signal.
- **Why:** The rules can then be tested exhaustively with hand-built runs and no model, and a recorder or replayer can run the same detector over a stored trace and get the same verdicts (FR10). Hashing keeps memory small however large the tool output is. Ignoring answered-but-not-run calls stops a skipped call from being counted as an attempt.
- **Alternatives:** Detection code inside the loop (hard to test, hard to reuse for replay).
- **Consequences:** Replays must feed runs in the same order to get the same verdicts.

## AD-105: Pre-step results are a labelled, quoted section in the task text

- **Date:** 2026-11-01 · **Phase:** P19 · **Status:** Accepted (owner agreed)
- **Decision:** What the pre-steps find (the exception, code at the traceback locations, files that exist, the result of the named test) is added to the end of the task text under a heading saying it was computed by code. Every line that came from the issue or the repository is quoted with `| `.
- **Why:** The model sees one honest user message. The alternative, fake earlier tool calls and results, invents turns the model never made, which complicates recording, replay (FR10) and prompt caching, and blurs where the information came from. Quoting follows the convention from P16 and keeps repository content and issue text visibly data, so a hostile file or traceback cannot pass itself off as an instruction.
- **Alternatives:** Faked conversation history (trusted more by some models, but dishonest and harder to replay).
- **Consequences:** The section is part of the first message and is paid for on every step; it is capped (AD-106) and its size is reported (AD-107).

## AD-106: The issue steers what is read and run only after the code has checked it

- **Date:** 2026-11-01 · **Phase:** P19 · **Status:** Accepted
- **Decision:** Paths and test ids found in the issue are claims. A file is read only if it is in `git ls-files` (directly or by a unique tail match) and resolves, symlinks followed, to a file inside the repo. Test ids must have a tracked test file, use a restricted character set, not start with `-`, and reach pytest as separate arguments after `--`; at most 3 run, in one call. Nothing from the issue is ever run as a command, including code or commands pasted into it. Work is bounded (5 tracebacks, 3 snippets, 10 listed files, 5 name lookups, 30,000 characters of text).
- **Why:** The issue is written by anyone and these steps run before the model and before any guard that watches the model, so they must be safe by themselves. Using git's own file list means the issue cannot name `.git`, a file outside the repo or a file the project does not track; the pytest argument rules stop an id such as `--pdb` or `-p evil` from becoming an option. Running pasted reproduction code would be an unreviewed execution step that belongs to the reproduction phase (FR4), not here.
- **Alternatives:** Reading any path that exists (reaches untracked or generated files); running everything the issue suggests (unsafe and out of scope).
- **Consequences:** A test that is not tracked (for example a generated one) is not run by the pre-step; the model can still run it.

## AD-107: Log the certain facts; measure the saving with an on/off switch in the evals

- **Date:** 2026-11-01 · **Phase:** P19 · **Status:** Accepted (owner agreed)
- **Decision:** `PrestepReport` records what was found and done, the characters and estimated tokens added to the prompt, the number of operations done in code, the test status and the seconds spent, and one log line carries the counts. `enabled=False` switches the pre-steps off. No "tokens saved" number is produced or reported by this phase.
- **Why:** FR5.7 asks to measure the reduction in tokens and cost, but one job cannot show what the run without pre-steps would have cost. An estimate built from assumptions looks like a measurement and is not. The honest measurement is the eval harness running the same issues both ways and comparing real token and cost totals from the ledger. The report supplies the cost side (tokens added) so the comparison can be explained.
- **Alternatives:** An estimated saving per job (a guess presented as a result).
- **Consequences:** The roadmap item "log token savings" is met by logging the inputs and providing the switch; the actual saving is a result of the eval phases.

## AD-108: Pre-steps never fail the job, and have their own time budget

- **Date:** 2026-11-01 · **Phase:** P19 · **Status:** Accepted
- **Decision:** A git failure, an unreadable file, a runner error or a timeout inside the pre-steps becomes a note in the report and the remaining parts still run. Only mistakes in the arguments raise. `time_limit_s` (default 180) bounds the whole pre-step, and the test run gets the time left; the caller subtracts the time used from the job's wall-clock limit.
- **Why:** The pre-steps are a convenience for saving money, so a fault in them must not turn a fixable issue into a failed job or hold it up. The job's time limit starts when the loop starts, so the pre-step needs its own bound, and the caller, who knows both, accounts for it.
- **Alternatives:** Letting errors propagate (a parsing bug would kill every job with an odd issue); counting pre-step time inside the loop's limit (the loop does not know about it).
- **Consequences:** Failures are visible only in the report and its notes, so the recorder (P22) must store them.
