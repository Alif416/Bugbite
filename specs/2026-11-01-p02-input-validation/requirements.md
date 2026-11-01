# Requirements: Input Validation (Roadmap P2)

## Goal

Turn the raw strings a user submits (a GitHub issue URL and a repo URL) into trusted, structured references, or reject them with a clear message. This is the first gate every job passes through (FR1.1).

## Scope

**In:**
- Parse and validate a GitHub **issue URL** and **repo URL**, offline
- Check that the issue belongs to the given repo
- Reject non-GitHub hosts, pull-request or other non-issue URLs, malformed or look-alike URLs, and empty input
- A typed `InputError` with a stable code and a clear user-facing message
- Unit tests for all of the above

**Out (later phases):**
- Checking that a repo is Python (FR1.4): moves to **P3**, since it needs the GitHub API
- Fetching issue title, body, labels, comments (P3)
- Public or token-accessible check (P3, FR1.3)
- "Issue text + repo URL" input and "issue URL only" input
- CLI command (P45) and dashboard form (P67)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Python check | Deferred to P3 | Needs the GitHub API and a token; keeps P2 pure and offline |
| Input forms | Issue URL + repo URL | Matches the README and the user's choice; one clear form |
| Errors | `InputError` with a stable `code` and a message | CLI and API can each map the code to their own output |
| Network | None in P2 | Fast, deterministic tests; no secrets involved |
| Hosts | `github.com` and `www.github.com` only | GitHub Enterprise is out of scope for v1 |

See `specs/decisions.md` AD-011 to AD-014.

## Context

- README FR1.1 (accept issue URL and repo URL), FR1.3 and FR1.4 (validation, partly deferred).
- Mission principles: safety first (untrusted input must be strictly validated before anything uses it, such as a git clone URL), and honesty (clear rejection messages).
- Security note: the parsed `RepoRef` is what later phases will use to build clone commands and API calls. Strict character validation here prevents path traversal and argument injection downstream. Look-alike hosts such as `github.com.evil.io` must be rejected.
- Tech stack: stdlib only (`urllib.parse`, `re`, `dataclasses`). No new dependencies.

## Constraints

- No network calls, no secrets.
- Error messages must not echo secrets or leak internals; they may quote the offending input.
- Keep the parser pure so both the CLI and the API can reuse it.
- No gradient or UI work applies in this phase.

## Open items

- None blocking. FR1.4 (Python-only rejection) is explicitly handed to P3; the roadmap is updated to say so.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-011 to AD-014).
