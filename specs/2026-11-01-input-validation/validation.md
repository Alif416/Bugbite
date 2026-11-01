# Validation: Input Validation (Roadmap P2)

The work can be merged when every item below is true.

## Automated

- [ ] `uv run pytest` passes with zero failures and zero errors, including the 28 existing tests.
- [ ] `tests/github/test_urls.py` covers and passes:
  - [ ] repo URL: plain, trailing slash, `.git` suffix, `http`, `www.github.com`, host in upper case
  - [ ] issue URL: plain, trailing slash, query string, `#issuecomment-…` fragment
  - [ ] owner and repo names keep their original case
  - [ ] rejects non-GitHub hosts (e.g. gitlab.com)
  - [ ] rejects look-alike hosts (`github.com.evil.io`, `evilgithub.com`, `github.com@evil.io`)
  - [ ] rejects a pull-request URL, discussion URL, and repo URL given as the issue URL
  - [ ] rejects an issue URL given as the repo URL
  - [ ] rejects issue numbers that are 0, negative, non-numeric, or not an integer
  - [ ] rejects empty, whitespace-only, and non-string input
  - [ ] rejects owner or repo names with illegal characters, spaces, `..`, or shell metacharacters
- [ ] `tests/github/test_inputs.py` covers and passes:
  - [ ] matching issue and repo pair returns a `JobInput`
  - [ ] repo comparison is case-insensitive
  - [ ] mismatched repos raise `REPO_MISMATCH` and the message names both repos
  - [ ] an invalid issue URL or invalid repo URL raises the right code
- [ ] `tests/test_errors.py` confirms every error code has a non-empty message and `InputError.code` is stable.
- [ ] A test confirms parsing makes no network call (e.g. runs with sockets blocked).

## Manual checks

- [ ] `grep -rn "requests\|urllib.request\|httpx\|socket" src/bugbite/github/` returns nothing (offline only).
- [ ] No new dependencies were added to `pyproject.toml` or `uv.lock`.
- [ ] Error messages read clearly to a non-developer (spot check a few by hand).
- [ ] `bugbite.github` exports `parse_repo_url`, `parse_issue_url`, `parse_job_input`, `RepoRef`, `IssueRef`, `JobInput`.

## Docs and process

- [ ] `specs/decisions.md` has AD-011 to AD-014 with reasons.
- [ ] `specs/roadmap.md` has P2 ticked and P3 now includes the Python-only repo rejection.
- [ ] Commits are small and logical on branch `2026-11-01-input-validation`.
- [ ] No files outside this phase's scope were changed (no CLI, API, or network code).

## Definition of done

All boxes ticked, tests green locally, and the branch is ready for review and merge into `main`.
