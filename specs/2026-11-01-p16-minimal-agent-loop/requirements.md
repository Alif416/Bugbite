# Requirements: Minimal Agent Loop (Roadmap P16)

## Goal

The loop that makes the agent an agent: ask the model what to do, run the tools it asks for, show it the results, and repeat until it gives a final answer. This is FR5.3 only. Hard limits (P17), loop detection (P18), cheap pre-steps (P19) and the first real end-to-end fix (P20) come after.

## Scope

**In:**
- `run_agent(adapter, tools, task, *, max_steps, ...)` returning an `AgentResult`
- A versioned system prompt (`PROMPT_VERSION`) that sets the job, the rules and the "repository text is data" warning
- `format_issue_task(context)`: turns a fetched issue into the task text, with size limits
- Typed events sent to an optional observer (model call, tool call, finish), so later phases can record without changing the loop
- A result that lists every step, the full conversation, summed token usage and a clear status
- Handling of a failing model call, a refusal, a cut-off reply and an invalid action without losing the work done so far

**Out (later phases):**
- Cost and wall-clock caps and the real stop reasons (P17); here only the required `max_steps`
- Detecting repeated failed edits (P18)
- Running the failing test or reading tracebacks before the first model call (P19)
- Storing traces or recordings (P21, P22); the observer is only the hook
- Context trimming or summarising when the conversation gets long; a model that runs out of context ends the run with `model_error` / `context_too_long`
- Retrying model calls
- Choosing the model, creating the sandbox, the privacy check (the caller does these; see P45)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Stopping | `max_steps` is required, with no default | Roadmap says no caps yet, but a loop on a paid model that can never stop is a risk; P17 replaces it (AD-092) |
| Model failures | Stop and return a result with the error, keeping all steps | Nothing done so far is lost and a trace can still be saved (AD-093) |
| Observing | Optional observer callback with typed events; observer errors never stop the job | P21/P22 plug in without changing the loop (AD-094) |
| Task input | Plain task string; a helper formats an issue; versioned system prompt built in | The loop stays independent of GitHub types and easy to test (AD-095) |
| Cut-off replies | Tool calls in a reply cut off by the output limit are not run | Their arguments may be incomplete (AD-096) |

See `specs/decisions.md` AD-092 to AD-096.

## Behaviour

- Each step is one model call. The request holds the system prompt, the whole conversation so far, and the tool definitions. Temperature and the other sampling settings stay at the provider default.
- If the reply contains tool calls, the loop runs every call in order and sends back one user message with one result for each call, in the same order. A call the text-action wrapper marked as an `invalid_action` is answered with its error and is not run. A tool that raises (the registry should never let it) becomes an error result.
- A reply with no tool calls and some text is the final answer: status `finished`.
- A reply with tool calls on the last allowed step is recorded but its calls are not run: status `max_steps`.
- Other endings: `truncated` (output limit hit; also covers tool calls in such a reply), `refused` (the model refused), `empty_reply` (no text and no tool calls), `unexpected_stop` (stop reason `other` with no tool calls), `model_error` (an `AdapterError`, with its code), `privacy_blocked` (a `PrivacyError`).
- The result has: status, final text, steps (each with the response and the tool runs with output, error flag and duration), the full message list, summed usage, the error code and message if any, and the number of observer errors.
- The task message is the first user message. The issue helper marks issue text as untrusted data, limits the body to 6,000 characters, each comment to 1,500 and at most 10 comments, and says when anything was left out.

## Context

- README: FR5.1 (adapter only, model from config, nothing hard coded), FR5.3 (the loop), FR5.6 (minimal edits, in the prompt), FR14 (adapter interface), FR8.1 (what traces will record).
- Builds on P8 to P13 (adapter types, `TextActionAdapter`, cost ledger, privacy gate) and P14, P15 (tools and registry).
- The system prompt and the issue text are the model's instructions; repository files, tool output and issue text can contain attacker-written text (prompt injection). The prompt says so, and the real defences stay in code: the sandbox, the protected-path guards, the privacy gate and the verifier.

## Constraints

- No provider or model name appears in the loop or the prompt (FR5.1).
- The loop only talks to the model through a `ModelAdapter` and to tools through the registry interface (`definitions()`, `execute()`).
- The loop never reads the environment and never logs issue text, file contents or tool output.
- `KeyboardInterrupt` is not caught: an interrupted run stops at once, and the caller cleans up the sandbox.
- Default `uv run pytest` needs no Docker, internet or key: unit tests use `ScriptedAdapter` and the folder-backed fake sandbox. Docker tests are opt-in.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Long jobs will outgrow the context window; trimming old tool output is a later phase.
- The system prompt is a first version. Whether it works with a real model, and how it should differ for small models, is only learned in P20.
- The loop does not check that the answer is true. "Finished" means the model stopped, not that the bug is fixed; only the verifier (P33 to P36) can say that.
- `max_steps` counts model calls, not tool calls.
