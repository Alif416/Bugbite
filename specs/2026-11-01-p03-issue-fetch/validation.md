# Validation: Issue Fetch and Repo Access Check (Roadmap P3)

The work can be merged when every item below is true.

## Automated

- [ ] `uv run pytest` passes with zero failures and zero errors, including the 121 existing tests.
- [ ] The default test run makes no real network calls and needs no token or environment variables.
- [ ] `tests/github/test_client.py` covers and passes:
  - [ ] repo, issue, and comments are parsed correctly into the data types
  - [ ] a token adds the `Authorization` header; no token adds none
  - [ ] repo 404 raises `REPO_NOT_FOUND`, and the message suggests a token only when none was used
  - [ ] issue 404/410 raises `ISSUE_NOT_FOUND`
  - [ ] an issue number that is a pull request raises `NOT_AN_ISSUE`
  - [ ] 401 raises `auth_failed`
  - [ ] rate limit (403 with remaining 0, and 429) raises `rate_limited` and includes the reset time
  - [ ] 5xx raises `server_error`; timeout and connection error raise `network_error`
  - [ ] unexpected or malformed JSON raises `unexpected_response`
  - [ ] comments paginate across pages and stop at `max_comments` with `truncated` set
  - [ ] long issue body and comment text are cut to `max_chars` with a flag
  - [ ] null body becomes an empty string
  - [ ] the token never appears in any exception message, `str`, or `repr` of the client
- [ ] `tests/github/test_context.py` covers and passes:
  - [ ] a Python repo returns a full `JobContext`
  - [ ] a non-Python repo raises `NOT_PYTHON` naming the language, and the issue endpoint is never called
  - [ ] a repo with no detected language raises `NOT_PYTHON`
  - [ ] a redirect to a differently named repo raises `REPO_NOT_FOUND`
  - [ ] an archived repo is accepted and flagged
  - [ ] the order of calls is repo, then issue, then comments
- [ ] The live smoke test exists and is skipped by default (runs only with `BUGBITE_LIVE_TESTS=1`).
- [ ] New error codes are covered in `tests/test_errors.py`.

## Manual checks

- [ ] If network and a token are available: run the live smoke test once against a small public Python repo issue and see it succeed. Record the result in the PR or commit notes. If not run, say so plainly.
- [ ] Error messages read clearly to a non-developer (spot check by hand).
- [ ] `git grep -n "GITHUB_TOKEN" src/` shows no environment reads inside the client.
- [ ] `httpx` is the only new dependency in `pyproject.toml`, and `uv.lock` is refreshed.
- [ ] No secrets or tokens appear anywhere in the repo (`git grep -iE "ghp_|github_pat_"` is empty).
- [ ] `bugbite.github` exports `GitHubClient`, `fetch_job_context`, `RepoInfo`, `IssueData`, `CommentData`, `JobContext` in addition to the P2 names.

## Docs and process

- [ ] `specs/decisions.md` has AD-016 to AD-021 with reasons.
- [ ] `specs/roadmap.md` has P3 ticked and P6 mentions rejecting repos with no tests.
- [ ] README development setup mentions `GITHUB_TOKEN` as optional.
- [ ] Commits are small and logical on branch `2026-11-01-p03-issue-fetch`.
- [ ] No files outside this phase's scope were changed (no cloning, sandbox, PR, or retry code).

## Definition of done

All boxes ticked, tests green locally, and the branch is ready for review and merge into `main`.
