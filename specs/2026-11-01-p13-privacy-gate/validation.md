# Validation: Privacy Gate (Roadmap P13)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable and no internet: only Docker, internet, and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Classification:**
  - [x] a public repo is `PUBLIC`; a private repo is `PRIVATE`; unknown visibility is `PRIVATE`
  - [x] a repo on the sandbox list is `SANDBOX` whether it is private or public
  - [x] matching the list is case-insensitive, exact on the whole `owner/name` (`octo/hello-world` and `other/hello` do not match `octo/hello`), and the list may be empty
  - [x] the name used is the one the GitHub API returned, not the name the user typed
- [x] **Policy table:** `may_receive` is true for every sensitivity when the model allows private code, and true only for `PUBLIC` and `SANDBOX` when it does not.
- [x] **Job-start check:** returns the sensitivity when allowed; raises `PrivacyError` (code `private_code_blocked`) when not; the message names the model and the repository, lists the configured models that would be allowed (or says that none is), says how the owner can change the policy (editing the model config), and contains no issue text, comments, or file contents; there is no argument that bypasses it.
- [x] **Guard:**
  - [x] when the policy forbids the call, the inner adapter is never called, for requests with tools, without tools, and invalid ones, and the error is raised before the request is looked at
  - [x] when allowed, the call passes through and the response is the very same object
  - [x] inner errors propagate unchanged; `name`, `config`, `estimate_tokens`, and `close` come from the inner adapter
  - [x] `sensitivity` is required and must be a `Sensitivity`
- [x] **Wiring matrix:** for each combination of model setting (allowed or not), sensitivity (public, sandbox, private), native and non-native tool calling, and with and without a ledger, the raw adapter is called if and only if `may_receive` says so; the default sensitivity of `create_adapter` is `PRIVATE`; a blocked call leaves the ledger empty and never triggers a text-action repair or a second call.
- [x] **Ordering:** the guard is the innermost wrapper (the metering and text-action wrappers sit above it), checked by inspecting the built adapter chain.
- [x] **End to end:** a private repo fetched through the GitHub client on a mock transport is classified `PRIVATE`; the job-start check refuses it for `groq-free` and for `haiku`, and accepts it for `local-free`; a private repo on the sandbox list is accepted for `groq-free`; a public repo is accepted for all three.
- [x] **Architecture test:** no source file outside `src/bugbite/adapter/` imports the concrete adapter classes or modules; a deliberately bad sample file is caught by the same checker.
- [x] **Config:** `sandbox_repos` loads, normalises, de-duplicates, and rejects non-lists, non-strings, empty strings, and entries not of the form `owner/name` naming the entry; the shipped `config/app.yaml` has `sandbox_repos: []`; in the shipped models file `haiku` and `groq-free` are `false` and `local-free` is `true`.
- [x] **Error family:** `PrivacyError` is not an `InputError` or `AdapterError`; its code is stable and covered in `tests/test_errors.py`; the metering wrapper does not record it as a call.
- [x] **Mutation check:** each of these deliberate breakages makes at least one test fail: unknown visibility treated as public, the guard disabled, a case-sensitive sandbox match, a `PUBLIC` default in `create_adapter`, the guard placed above the text-action wrapper, `PrivacyError` recorded as a model call, and the job-start check skipping the sandbox list.

## Manual checks

- [x] `git grep -nE "allow_private_code" -- src` shows the field is read only in the policy function (and defined in config), never bypassed elsewhere.
- [x] `git grep -nE "os.environ|getenv" src/bugbite/privacy.py src/bugbite/adapter/privacy_guard.py` returns nothing: no environment switch can turn the rule off.
- [x] The text of the refusal message read once for a person who is not a developer.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-076 to AD-081 with reasons.
- [x] `specs/roadmap.md` has P13 ticked and a note on P45 and P66.
- [x] README explains the rule, the classification, the `sandbox_repos` list, and what entry points must do.
- [x] Commits are small and logical on branch `2026-11-01-p13-privacy-gate`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no CLI, API, storage, or agent code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
