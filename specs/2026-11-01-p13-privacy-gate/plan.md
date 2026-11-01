# Plan: Privacy Gate (Roadmap P13)

Branch: `2026-11-01-p13-privacy-gate`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-076 onward).

## 1. Config: the owner's sandbox repos (AD-077)

1. Add `sandbox_repos` to `AppConfig` (a tuple of `owner/name` strings, empty by default) and to `load_app_config`: an optional list; every entry must look like `owner/name` (the same character rules as the repo URL parser), comparisons are case-insensitive, duplicates collapse, anything else is a `ConfigError` naming the entry.
2. Add `sandbox_repos: []` to `config/app.yaml` with a comment: these are repos you own and are happy for any configured model to see (your demo and test repos); here "sandbox" does not mean the Docker sandbox.

## 2. Errors

Add `PrivacyError(code, message)` to `src/bugbite/errors.py` with the stable code `private_code_blocked` (AD-079). It is its own family: not an `InputError`, not an `AdapterError`, so nothing that handles those can swallow it by accident.

## 3. Classification and the job-start check

Create `src/bugbite/privacy.py`:

1. `Sensitivity`: `PUBLIC`, `SANDBOX`, `PRIVATE`.
2. `classify(full_name, private, sandbox_repos) -> Sensitivity`: `SANDBOX` if the name is in the owner's list; else `PUBLIC` only if GitHub says the repo is public (`private is False`); otherwise `PRIVATE`. A missing or unknown visibility is `PRIVATE` (fail closed). The name used is the one GitHub returned (`RepoInfo.full_name`), never the text the user typed.
3. `classify_context(context, sandbox_repos)` for a fetched `JobContext`.
4. `may_receive(model, sensitivity) -> bool`: a model may receive anything if `allow_private_code` is true; otherwise only `PUBLIC` and `SANDBOX` data.
5. `check_job_privacy(model, context, sandbox_repos, models=None) -> Sensitivity`: returns the classification, or raises `PrivacyError` before any work. The message names the model, the repository, and the models in the config that would be allowed. There is no override flag (AD-078).

## 4. The guard at the model boundary

Create `src/bugbite/adapter/privacy_guard.py` with `PrivacyGuardAdapter(inner, sensitivity)`:

1. Its `generate` checks `may_receive` first, before anything else (even before the request is validated), and raises `PrivacyError` without calling the inner adapter. Otherwise it passes the call straight through.
2. `estimate_tokens`, `close`, `name`, and `config` come from the inner adapter. `sensitivity` is a required argument with no default.
3. In `create_adapter(model, api_key=..., ledger=..., sensitivity=Sensitivity.PRIVATE)` the guard wraps the raw adapter **innermost**, so every wrapper above it (metering, text-action repair) can only reach the network through it (AD-076). The default is `PRIVATE`: forgetting to say what the data is makes a model that cannot take private code refuse, instead of leaking.
4. A `PrivacyError` passes through the metering wrapper without being recorded as a call and is never repaired by the text-action wrapper.

## 5. No way around `create_adapter`

An architecture test reads every source file outside `src/bugbite/adapter/` and fails if one imports the concrete adapter classes or modules (`ClaudeAdapter`, `OpenAICompatibleAdapter`, `bugbite.adapter.claude`, `bugbite.adapter.openai_compatible`), so later code cannot build an unguarded adapter by accident (AD-081).

## 6. The Haiku policy

`allow_private_code` for `haiku` stays `false` (AD-080). Add a comment above the field recording that this is the owner's decision to change after reading Anthropic's data terms, and that `local-free` is the model allowed to see private code.

## 7. Tests

1. **Classification:** public, private, unknown visibility, a private sandbox repo, a public sandbox repo, case-insensitive matching, near-miss names (`octo/hello-world` versus `octo/hello`, a different owner), an empty list, and the canonical-name rule.
2. **Policy table:** every combination of model setting and sensitivity gives the expected `may_receive`.
3. **Job-start check:** allowed combinations return the sensitivity; blocked ones raise a `PrivacyError` whose message names the model and repository and lists the allowed models, or says plainly that none is allowed; it never contains issue text or code.
4. **Guard:** the inner adapter is never called when blocked, for requests with tools, without tools, and invalid ones; allowed calls pass through unchanged (same response object); inner errors propagate; delegation works; the sensitivity argument is required and type-checked.
5. **Wiring matrix:** for every model setting, every sensitivity, with and without a ledger, and for native and non-native models, the raw adapter is called if and only if the policy allows it; a blocked call leaves the ledger empty and never triggers a repair; the default sensitivity of `create_adapter` is `PRIVATE`.
6. **End to end:** a private repo fetched through the GitHub client (mock transport) is classified `PRIVATE`; a request for `groq-free` is refused at job start; the same job on `local-free` is accepted; a sandbox-listed private repo is accepted for `groq-free`.
7. **Architecture test** from section 5, plus a check that it would catch a violation.
8. **Config:** `sandbox_repos` loading and every rejection; the shipped files; `haiku` is `false`, `local-free` is `true`.
9. Break the rule on purpose (unknown treated as public, guard disabled, case-sensitive sandbox match, default sensitivity `PUBLIC`, guard moved above the repair wrapper, `PrivacyError` recorded as a call) and confirm the tests fail.

## 8. Docs and wrap-up

1. Add AD-076 to AD-081 to `specs/decisions.md` (written with the specs). Tick P13 in `specs/roadmap.md` and note on the CLI and API phases (P45, P66) that they must call `check_job_privacy` and pass its result to `create_adapter`.
2. README: the privacy rule, how data is classified, how to list sandbox repos, how to allow a model, and the instruction for entry points.
3. Commit in small logical commits, then merge into `main` with `--no-ff` and push when asked. Commit messages carry no co-author trailer.
