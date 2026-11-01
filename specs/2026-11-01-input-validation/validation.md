# Validation: Input Validation (Roadmap P2)

The work can be merged when every item below is true.

## Automated

- [x] `uv run pytest` passes with zero failures and zero errors, including the 28 existing tests.
- [x] `tests/github/test_urls.py` covers and passes:
  - [x] repo URL: plain, trailing slash, `.git` suffix, `http`, `www.github.com`, host in upper case
  - [x] issue URL: plain, trailing slash, query string, `#issuecomment-…` fragment
  - [x] owner and repo names keep their original case
  - [x] rejects non-GitHub hosts (e.g. gitlab.com)
  - [x] rejects look-alike hosts (`github.com.evil.io`, `evilgithub.com`, `github.com@evil.io`)
  - [x] rejects a pull-request URL, discussion URL, and repo URL given as the issue URL
  - [x] rejects an issue URL given as the repo URL
  - [x] rejects issue numbers that are 0, negative, non-numeric, or not an integer
  - [x] rejects empty, whitespace-only, and non-string input
  - [x] rejects owner or repo names with illegal characters, spaces, `..`, or shell metacharacters
- [x] `tests/github/test_inputs.py` covers and passes:
  - [x] matching issue and repo pair returns a `JobInput`
  - [x] repo comparison is case-insensitive
  - [x] mismatched repos raise `REPO_MISMATCH` and the message names both repos
  - [x] an invalid issue URL or invalid repo URL raises the right code
- [x] `tests/test_errors.py` confirms every error code has a non-empty message and `InputError.code` is stable.
- [x] A test confirms parsing makes no network call (e.g. runs with sockets blocked).

## Manual checks

- [x] `grep -rn "requests\|urllib.request\|httpx\|socket" src/bugbite/github/` returns nothing (offline only).
- [x] No new dependencies were added to `pyproject.toml` or `uv.lock`.
- [x] Error messages read clearly to a non-developer (spot check a few by hand).
- [x] `bugbite.github` exports `parse_repo_url`, `parse_issue_url`, `parse_job_input`, `RepoRef`, `IssueRef`, `JobInput`.

## Docs and process

- [x] `specs/decisions.md` has AD-011 to AD-014 with reasons.
- [x] `specs/roadmap.md` has P2 ticked and P3 now includes the Python-only repo rejection.
- [x] Commits are small and logical on branch `2026-11-01-input-validation`.
- [x] No files outside this phase's scope were changed (no CLI, API, or network code).

## Definition of done

All boxes ticked, tests green locally, and the branch is ready for review and merge into `main`.
