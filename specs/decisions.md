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
- **Why:** Running the suite the way the project does keeps results meaningful: overriding `addopts` could drop flags the suite needs and silently change which tests run. `-p no:cacheprovider` avoids writing `.pytest_cache` into the repo, `--tb=short` and no colour keep the saved output compact and readable in PR evidence. 300 s fits the 10-minute median-job target when a baseline, a fix, and a verification run all happen. The owner chose both defaults.
- **Alternatives:** Empty `addopts` (changes which tests run); a longer limit (a single run could use the whole job budget); a shorter one (many real suites would time out).
- **Consequences:** Repos whose `addopts` need missing plugins fail clearly as `collection_error`. Tests that need the internet fail because the network is cut after setup; baseline comparison (P31, P32) must treat tests failing both before and after as pre-existing.

## AD-039: What P6 guarantees about result integrity

- **Date:** 2026-11-01 · **Phase:** P6 · **Status:** Accepted
- **Decision:** Before every run the plugin file is rewritten and the report file is deleted, so stale or edited artifacts are never reused. P6 does not defend against code running inside pytest that deliberately forges the report (for example a malicious `conftest.py`). That defence is left to the verifier in P33, which will re-run tests in a clean container built from the patch.
- **Why:** README FR6.5 requires the pass check to be done by the verifier, not by the agent. Trying to make an in-container run tamper-proof would add complexity without a real guarantee, because the code under test and the report writer share one process. Stating the limit plainly keeps later claims honest (mission principle 8).
- **Alternatives:** Hashing or signing the report from inside the container (the forger has the same access); running the plugin on the host (not possible, tests run in the container).
- **Consequences:** Until P33, a result is only as trustworthy as the repo code and the agent's edits. Test results from agent runs must not be reported as final verification.
