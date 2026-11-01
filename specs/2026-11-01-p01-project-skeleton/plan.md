# Plan: Project Skeleton (Roadmap P1)

Branch: `2026-11-01-p01-project-skeleton`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria.

## 1. Repository tooling

1. Create `pyproject.toml` (project `bugbite`, Python >= 3.11, `src/` layout) managed by uv.
2. Add runtime deps: `pyyaml`. Add dev deps: `pytest`.
3. Generate `uv.lock` with `uv sync`.
4. Add `.gitignore` (Python, venv, `.env`, caches, `data/`).
5. Add `.env.example` listing secret names only (no values): `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `OPENAI_COMPATIBLE_API_KEY`.

## 2. Package layout

1. Create `src/bugbite/` with `__init__.py` exposing `__version__`.
2. Create empty module packages, each with `__init__.py` and a one-line docstring stating its job:
   `sandbox`, `retrieval`, `agent`, `adapter`, `verifier`, `pr_writer`, `recorder`, `failure_classifier`, `evals`, `trace_store`, `github`.
3. Create `tests/` mirroring the module names, plus `tests/conftest.py`.
4. Add `config/` with `app.yaml` and `models.yaml` examples.

## 3. Config loading

1. Add `src/bugbite/config.py` with typed dataclasses: `AppConfig` and `ModelConfig`.
   - `ModelConfig` fields follow FR14.3: provider, base_url, model_name, context_window, native_tool_calling, price_per_input_token, price_per_output_token, per_issue_cap_usd, allow_private_code.
   - `AppConfig` fields: default_model, max_steps, max_cost_usd, max_wall_clock_s, total_budget_usd (5.0).
2. Implement `load_app_config(path)` and `load_models_config(path)` reading YAML.
3. Validate: missing required fields, wrong types, negative prices or caps, and unknown `default_model` all raise a clear `ConfigError`.
4. Secrets are read only through `get_secret(name)` from environment variables. Never from YAML.
5. Write `config/models.yaml` with Haiku (default) and one free-model placeholder (Ollama, price 0).
6. Ensure no model or provider name appears in any code path outside config files and tests (FR5.1).

## 4. Tests

1. `tests/test_config.py`: valid load, each validation failure, secret from env, missing secret error, default model resolves.
2. `tests/test_layout.py`: every module package imports.
3. Confirm `uv run pytest` passes locally.

## 5. CI stub

1. Add `.github/workflows/ci.yml`: on push and pull_request, set up uv, install Python 3.11, run `uv sync` and `uv run pytest`.

## 6. Docs and wrap-up

1. Add a "Development setup" section to `README.md` (install uv, `uv sync`, `uv run pytest`, copy `.env.example`).
2. Tick P1 in `specs/roadmap.md`.
3. Commit in small logical commits on the feature branch.
