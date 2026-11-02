# Validation: Replay works for both adapters (Roadmap P24)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable (foreground): none fail, all earlier tests pass. (2402 passed, 156 skipped; with Docker running 2552 passed, 6 skipped.)
- [x] **Real Claude adapter:** a recorded run through `ClaudeAdapter` (mock transport) replays `identical` for: tool call then answer, text-only answer, rate-limit error, server error, two tool calls in one reply, truncated answer.
- [x] **Real OpenAI-compatible adapter:** the same list replays `identical`, plus a reply without a `usage` block.
- [x] **Cache markers and usage:** Claude cache markers are part of the recorded request fingerprint, and the cost reported by a replay equals the recorded cost exactly, including cache read/write tokens.
- [x] **Text-action fallback:** a model without native tool calling replays `identical` through each real adapter, repair calls included.
- [x] **Parity:** the same conversation through both adapters replays `identical`, and the neutral results (steps, tool calls, final text, outcome) are equal.
- [x] **Goldens:** one tracked golden recording per adapter replays `identical`; the fixtures are not git-ignored (checked by git); a script rebuilds them byte-for-byte.
- [x] **No secrets:** the fake API key and header values appear in no recording file.
- [x] **Detection:** a changed request (tool description, system prompt) against each adapter's recording stops with `request_mismatch`.
- [x] **No outside access** during these replays (sockets blocked, environment emptied), and no new dependencies (`pyproject.toml`, `uv.lock` unchanged).
- [x] **Mutation check (6 breakages, all caught after one test was strengthened):** each of these breakages fails at least one new test: Claude cache marker dropped, tool-call id mapping changed, usage mapping changed, tool results reordered, recorder skipping an error response.
- [x] No leftover containers or volumes; the user's databases untouched.

## Manual

- [x] README lists the covered adapters; `specs/decisions.md` has an AD for each choice; roadmap P24 ticked; no `Co-Authored-By` on any commit.
