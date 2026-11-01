# Plan: Input Validation (Roadmap P2)

Branch: `2026-11-01-p02-input-validation`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-011 onward).

## 1. Error type

1. Create `src/bugbite/errors.py` with `InputError(Exception)` carrying a stable `code` (string) and a user-facing `message`.
2. Define the error codes as constants: `INVALID_URL`, `NOT_GITHUB`, `NOT_AN_ISSUE_URL`, `NOT_A_REPO_URL`, `REPO_MISMATCH`, `EMPTY_INPUT`.
3. Make `ConfigError` unchanged; the two error types stay separate.

## 2. URL parsing (offline, no network)

1. Create `src/bugbite/github/urls.py` with frozen dataclasses `RepoRef(owner, name)` and `IssueRef(repo, number)`.
2. `parse_repo_url(url)` accepts `https://github.com/owner/name`, with optional trailing slash and optional `.git`. Returns `RepoRef`.
3. `parse_issue_url(url)` accepts `https://github.com/owner/name/issues/123`, with optional trailing slash, query, or fragment (such as `#issuecomment-1`). Returns `IssueRef`.
4. Normalise input: strip whitespace, accept `http` or `https`, accept `www.github.com`, lowercase the host only (owner and repo names keep their case).
5. Reject with clear messages:
   - empty or non-string input
   - a host other than github.com (including look-alikes such as `github.com.evil.io` and `evilgithub.com`)
   - missing owner or repo
   - a pull request, discussion, or other non-issue path given as the issue URL
   - an issue number that is not a positive integer
6. Validate owner and repo characters against GitHub's allowed set; reject path traversal and unusual characters.

## 3. Combined input

1. Create `src/bugbite/github/inputs.py` with `JobInput(repo: RepoRef, issue: IssueRef)`.
2. `parse_job_input(issue_url, repo_url)` parses both and requires that the issue's repo matches the repo URL (case-insensitive compare). A mismatch raises `REPO_MISMATCH` naming both.
3. Export the public names from `bugbite.github`.

## 4. Tests

1. `tests/github/test_urls.py`: accepted forms (trailing slash, `.git`, `www`, `http`, fragment, query), each rejection, look-alike hosts, case handling, number edge cases (0, negative, text, huge).
2. `tests/github/test_inputs.py`: matching pair, mismatched repo, case-insensitive match, either side invalid, empty input.
3. `tests/test_errors.py`: each error carries a code and a non-empty message; messages never echo anything beyond the offending input.
4. Confirm `uv run pytest` passes.

## 5. Entry-point readiness (no UI yet)

1. Keep the parser pure so the CLI (P45) and FastAPI (P66) can both call `parse_job_input` and map `InputError.code` to their own output.
2. Do not add CLI or API code in this phase.

## 6. Docs and wrap-up

1. Update `specs/roadmap.md`: reword P2 to offline parsing, and move the "reject non-Python repos" check into P3. Tick P2.
2. Add AD-011 to AD-014 to `specs/decisions.md`.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked.
