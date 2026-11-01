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
