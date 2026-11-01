# Validation: Project Skeleton (Roadmap P1)

The work can be merged when every item below is true.

## Automated

- [x] `uv sync` succeeds from a clean checkout.
- [x] `uv run pytest` passes with zero failures and zero errors.
- [x] `tests/test_layout.py` imports every module package: sandbox, retrieval, agent, adapter, verifier, pr_writer, recorder, failure_classifier, evals, trace_store, github.
- [x] `tests/test_config.py` covers and passes:
  - [x] valid app config loads
  - [x] valid models config loads with all FR14.3 fields
  - [x] missing required field raises `ConfigError` naming the field
  - [x] wrong type raises `ConfigError`
  - [x] negative price or cap raises `ConfigError`
  - [x] unknown `default_model` raises `ConfigError`
  - [x] secret is read from an environment variable
  - [x] missing secret raises a clear error without printing any secret value
- [x] GitHub Actions workflow `ci.yml` is valid YAML and runs `uv sync` and `uv run pytest` on push and pull request (confirmed by a green run, or by reading the workflow if no remote exists yet).

## Manual checks

- [x] `config/models.yaml` lists Haiku as default and one free-model placeholder with price 0.
- [x] `grep -ri "haiku\|ollama\|anthropic" src/` returns nothing (no model or provider name in code, FR5.1). Provider *type* strings handled in later adapter phases are out of scope here.
- [x] `.env.example` contains secret names only, no values; `.env` is in `.gitignore`.
- [x] No secrets or API keys anywhere in the repo (`git grep -i "sk-"` is empty).
- [x] Every module package contains only `__init__.py` with a one-line docstring; no logic.
- [x] README has a Development setup section, and the steps work as written on a fresh clone.

## Docs and process

- [x] P1 is ticked in `specs/roadmap.md`.
- [x] Commits are small and logical on branch `2026-11-01-project-skeleton`.
- [x] No files outside this phase's scope were changed (no Docker, FastAPI, lint config).

## Definition of done

All boxes ticked, tests green locally, and the branch is ready for review and merge into `main`.
