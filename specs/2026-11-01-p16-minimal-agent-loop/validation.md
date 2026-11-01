# Validation: Minimal Agent Loop (Roadmap P16)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable: only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Argument checks:** `max_steps` is required and must be an integer of at least 1 (0, negatives, bools, floats, None and a missing value are rejected); an empty or non-string task is rejected; these raise `ValueError`/`TypeError` before any model call.
- [x] **Happy path:** a reply with no tool calls ends the run as `finished` with the text as the final answer; one tool call then an answer works; several tool calls in one reply run in order and their results come back in one user message in the same order; a reply with text and a tool call keeps both in the history.
- [x] **History:** at every step the request holds the system prompt, the tool definitions and the exact conversation so far; every tool call in the history has exactly one result with the same id; temperature is left at `None`.
- [x] **Endings:** `max_steps` (tool calls of the last reply recorded but not run), `truncated` (calls in a cut-off reply not run), `refused`, `empty_reply`, `unexpected_stop`, `model_error` (every `AdapterError` code, with the steps so far kept), `privacy_blocked`; none of them raises.
- [x] **Tools:** an `invalid_action` call is answered with its error and not run; an unknown tool, bad arguments and a tool that raises each become an error result the model sees; the loop continues after them.
- [x] **Result:** steps, messages, summed usage, error code and message are correct for each ending; the result is immutable.
- [x] **Observer:** events arrive in order (model call, then each tool call, then finish); an observer that raises does not stop the run and is counted in `observer_errors`; the log line for it contains no task or tool text.
- [x] **Task helper:** limits on body, comments and count; notes when text was left out; empty body and no comments; hostile text cannot close the untrusted-data section.
- [x] **Prompt:** `PROMPT_VERSION` is "1"; the prompt names no model or provider; it contains the data warning, the rule about tests, and the instruction to finish with plain text; it is the system prompt in every request.
- [x] **Text-action path:** a non-native scripted model completes a read, edit and finish run through `TextActionAdapter`, including one failed step answered with its error.
- [x] **Privacy and cost:** a private job with a closed model ends `privacy_blocked` with the ledger empty; a public job completes with one ledger entry per model call.
- [x] **No hard-coded model:** a test scans `src/bugbite/agent` for provider and model names (`claude`, `haiku`, `openai`, `groq`, `anthropic`, `gpt`) and finds none outside comments that explain the rule.
- [x] **Mutation check:** each of these breakages makes at least one test fail: results out of order, a call left without a result, truncated calls run, `max_steps` off by one, model error raised instead of returned, invalid action executed, observer error escaping, usage not summed.

## Docker test (opt-in; run once before merge)

- [x] A scripted model drives the real tools in a real sandbox: it edits a file and runs a command, the run ends `finished`, `git diff` shows exactly the edit, and no labelled containers or volumes are left.

## Manual checks

- [x] Read the system prompt once as if you were a small model: is each rule clear and short enough to follow?
- [x] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-092 to AD-096 with reasons.
- [x] `specs/roadmap.md` has P16 ticked.
- [x] README explains how to run the loop, the statuses, the observer, and what is not there yet.
- [x] Commits are small and logical on branch `2026-11-01-p16-minimal-agent-loop`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no caps, no loop detection, no storage, no CLI).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
