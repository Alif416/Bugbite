# Requirements: Issue Fetch and Repo Access Check (Roadmap P3)

## Goal

Given a validated `JobInput` (from P2), talk to the GitHub API to confirm the repo is reachable and is a Python repo, then fetch the issue's title, body, labels, and comments. This completes the input gate (FR1.2, FR1.3, FR1.4) and produces the `JobContext` the agent will start from.

## Scope

**In:**
- `GitHubClient` over `httpx` using the GitHub REST API
- Repo info (visibility, primary language, default branch, archived, fork)
- Issue fetch (title, body, labels, state, author) with pull requests rejected
- Comment fetch with pagination and a cap
- Python-only rejection using GitHub's primary language
- Optional token via `GITHUB_TOKEN`, passed in by the caller
- Clear, coded errors for each failure
- Size caps on text and comment count
- Offline tests with a mock transport, plus an opt-in live smoke test

**Out (later phases):**
- Checking that the repo has a test suite: deferred to P6 (AD-019)
- Cloning, installing, running tests (P4 to P6)
- Retries, backoff, queueing, rate-limit resume (P51 and the adapter phases)
- Creating branches, pushes, PRs, issue comments (P41 onward)
- Parsing tracebacks from the issue text (P19)
- GitHub Enterprise hosts

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| HTTP library | `httpx`, direct REST | Small, easy to mock offline, full control of timeouts, pagination and errors (AD-016) |
| Token | Optional, supplied by caller | Public repos work without it; clear message if a private repo needs one (AD-017) |
| Python check | GitHub primary language equals "Python" | One cheap call, matches the owner's choice (AD-018) |
| Test suite check | Not in P3 | Best detected after cloning by running pytest (AD-019) |
| Errors | `InputError` for user-fixable, `GitHubAPIError` for provider or network problems | Callers present them differently (AD-020) |
| Retries | None in P3 | Keeps the phase small; backoff arrives with the resume and rate-limit phases (AD-020) |
| Size limits | 50 comments, 20,000 characters per text field, flagged when cut | Context must stay small (FR3.4) (AD-021) |

See `specs/decisions.md` AD-016 to AD-021.

## Context

- README: FR1.2 (fetch title, body, labels, comments), FR1.3 (public or accessible with token, clear rejection), FR1.4 (Python only).
- Mission principles in play: safety (the token never reaches logs, errors, or the agent), honesty (clear reasons for rejection), measured and small context.
- Security notes:
  - Issue and comment text is **untrusted input**. It can contain prompt-injection attempts. P3 only stores it as data; later phases must keep it clearly separated from instructions when building prompts.
  - The token is sent only to the GitHub API host. httpx drops it on cross-origin redirects.
  - The client takes the token as an argument and never reads the environment itself, so tests cannot leak a real token.
- The GitHub issues endpoint also returns pull requests, so `NOT_AN_ISSUE` is a real case.
- Redirects: a renamed or transferred repo redirects. The result is checked against the requested name so a job never silently works on a different repo.
- Tech stack: Python 3.11+, one new dependency (`httpx`).

## Constraints

- Default test run must make no network calls and need no token.
- Never print, log, or embed the token in any message or `repr`.
- Anonymous API access has a low rate limit (60 requests per hour). P3 uses at most three call kinds per job (repo, issue, comments pages).
- No UI work, so the no-gradient rule does not apply here.

## Open items

- Real-world check of the primary-language approach on mixed repos is deferred; it will show up in failure analysis later.
- Whether to send the token from `GITHUB_TOKEN` automatically at the entry point is decided when the CLI is built (P45).

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-016 to AD-021).
