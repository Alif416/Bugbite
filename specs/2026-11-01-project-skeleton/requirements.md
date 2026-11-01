# Requirements: Project Skeleton (Roadmap P1)

## Goal

Give Bugbite a runnable, tested foundation: package layout, config loading, test runner and CI, so later phases (P2 onward) can add behavior without re-deciding structure.

## Scope

**In:**
- uv-managed Python 3.11+ project with `src/` layout
- Empty, importable module packages matching the architecture (sandbox, retrieval, agent, adapter, verifier, pr_writer, recorder, failure_classifier, evals, trace_store, github)
- YAML config loading with validation for app config and per-model config (FR14.3 fields)
- Secrets read from environment variables only
- pytest suite passing
- GitHub Actions workflow running pytest
- `.gitignore`, `.env.example`, README dev-setup section

**Out (later phases):**
- Any real behavior: input validation (P2), GitHub fetch (P3), Docker (P4+), model adapters (P8+)
- Ruff, mypy, or other lint/type tooling
- Docker Compose, Postgres, Redis
- FastAPI app and React dashboard

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Git | `git init`, initial commit of README and specs on `main`, feature branch from there | Folder was not a repo |
| Packaging | uv + `pyproject.toml` | Fast, single lockfile |
| Config format | YAML, secrets via env vars | Comments allowed, readable model table; keeps secrets out of files (NFR Security) |
| Scope level | Minimal | Keep the phase very small, per roadmap |
| Layout | `src/bugbite/` | Prevents accidental imports from the repo root |
| Python | >= 3.11 | tech-stack.md |

## Context

- Mission principles in play: model-agnostic (no model name hard coded, #5), secrets never in code or logs (#4), enforce in code not prompts (#3).
- Tech stack: Python 3.11+, pytest, GitHub Actions CI (`specs/tech-stack.md`).
- README references: FR5.1 (model and provider are config values), FR14.3 (model config fields), NFR Security and Maintainability (module boundaries with unit tests), section 6 budget (total 5 USD).
- Default model is Haiku; the free-model entry is a placeholder only. Real model IDs are set by the owner in `models.yaml` and are not asserted by tests.

## Constraints

- No gradients matter only for the UI; not applicable here.
- No real secrets committed; `.env` is git-ignored.
- Config validation errors must be clear, naming the file and field.
- Keep each module package empty of logic in this phase.

## Open items

- Exact free model entry (Ollama model name) is left as a placeholder until the owner answers open question 4 in the README.
- Haiku's current model ID and prices must be confirmed by the owner before the first paid run; tests do not depend on them.
