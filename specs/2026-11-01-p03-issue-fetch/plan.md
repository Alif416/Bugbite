# Plan: Issue Fetch and Repo Access Check (Roadmap P3)

Branch: `2026-11-01-p03-issue-fetch`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-016 onward).

## 1. Dependency and error types

1. Add `httpx` to `pyproject.toml` dependencies and refresh `uv.lock`.
2. Extend `src/bugbite/errors.py` with new `InputError` codes for problems the user can fix: `REPO_NOT_FOUND`, `NOT_PYTHON`, `ISSUE_NOT_FOUND`, `NOT_AN_ISSUE` (the number is a pull request).
3. Add `GitHubAPIError(Exception)` with a stable `code` (`rate_limited`, `network_error`, `server_error`, `auth_failed`, `unexpected_response`) and a message. These are system or provider problems, not user mistakes, so they stay separate from `InputError`.
4. Unit-test the new codes and that every message is non-empty.

## 2. Data types

1. Create `src/bugbite/github/models.py` with frozen dataclasses:
   - `RepoInfo(full_name, private, language, default_branch, archived, fork, html_url)`
   - `IssueData(number, title, body, labels, state, author, html_url, body_truncated)`
   - `CommentData(author, body, created_at, truncated)`
   - `JobContext(repo, issue, comments, comments_truncated)`
2. Missing or null fields from the API (such as an empty issue body) become safe defaults, never `None` where text is expected.

## 3. GitHub client

1. Create `src/bugbite/github/client.py` with `GitHubClient`.
   - Constructor takes an optional token, `base_url` (default `https://api.github.com`), timeout, and an optional injected `httpx.Client` so tests can supply a mock transport.
   - Token comes from the caller (use `get_secret("GITHUB_TOKEN")` at the entry point only if set). The client never reads the environment itself and never logs or echoes the token.
   - Send `Accept: application/vnd.github+json`, `X-GitHub-Api-Version`, and a `User-Agent`. Add `Authorization` only when a token is present.
   - Redirects allowed (renamed repos), relying on httpx to drop the token on cross-origin redirects.
2. `get_repo(RepoRef) -> RepoInfo`.
   - 404 raises `REPO_NOT_FOUND`. The message says the repo does not exist or is private, and suggests setting `GITHUB_TOKEN` if no token was used.
   - 401 raises `auth_failed`; 403 or 429 with an exhausted rate limit raises `rate_limited` including the reset time; 5xx raises `server_error`; connection errors and timeouts raise `network_error`.
3. `get_issue(IssueRef) -> IssueData`.
   - 404/410 raises `ISSUE_NOT_FOUND`.
   - A response containing `pull_request` raises `NOT_AN_ISSUE` (GitHub's issues endpoint also returns pull requests).
   - Text fields are truncated to `max_chars` with a flag.
4. `get_comments(IssueRef, max_comments) -> (list[CommentData], truncated)`.
   - Follow `Link: rel="next"` pagination at 100 per page and stop at `max_comments`. Set `truncated` if more existed.
5. No retries or sleeping in this phase (see AD-020). Errors are raised immediately.

## 4. Validation flow

1. Create `src/bugbite/github/context.py` with `fetch_job_context(client, job_input, max_comments=50) -> JobContext`.
2. Order: `get_repo` first, then check Python, then `get_issue`, then `get_comments`. Cheap rejections happen before the bigger calls.
3. Python check: `RepoInfo.language == "Python"` (case-sensitive match to GitHub's label). Anything else, including `None`, raises `NOT_PYTHON` naming the detected language (or "unknown").
4. Confirm the returned repo full name matches the requested one case-insensitively; if a redirect points elsewhere, raise `REPO_NOT_FOUND` rather than silently working on a different repo.
5. Archived repos: allowed to read, but record `archived` in `RepoInfo` so later phases can refuse to push.
6. Export `GitHubClient`, `fetch_job_context`, and the data types from `bugbite.github`.

## 5. Tests (all offline)

1. `tests/github/test_client.py` using `httpx.MockTransport`:
   - happy paths for repo, issue, comments
   - header checks: token present gives `Authorization`; token absent gives none
   - 404 repo, 404 issue, pull request given as issue, 401, rate limit (403 with remaining 0 and 429), 5xx, timeout, connection error
   - pagination across two pages; truncation at `max_comments`; long text truncation; null body
   - the token never appears in any exception message or `repr` of the client
2. `tests/github/test_context.py`:
   - Python repo returns a full `JobContext`
   - non-Python repo and unknown language raise `NOT_PYTHON` and the issue endpoint is never called
   - redirected/renamed repo mismatch handling
   - archived repo is flagged but accepted
3. A live smoke test against the real API, skipped unless `BUGBITE_LIVE_TESTS=1` is set, so the default run needs no network or token.
4. Confirm `uv run pytest` passes, with no real network access in the default run.

## 6. Docs and wrap-up

1. Add AD-016 to AD-020 to `specs/decisions.md` (already written with the specs).
2. Update `specs/roadmap.md`: tick P3, and add "reject repos with no tests" to P6.
3. Mention `GITHUB_TOKEN` as optional in the README development setup.
4. Commit in small logical commits, then merge into `main` with `--no-ff` when asked.
