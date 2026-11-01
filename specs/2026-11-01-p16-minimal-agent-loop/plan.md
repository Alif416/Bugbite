# Plan: Minimal Agent Loop (Roadmap P16)

Branch: `2026-11-01-p16-minimal-agent-loop`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-092 onward).

## 1. Result and event types (`src/bugbite/agent/types.py`)

1. `ToolRun(call, output, duration_s, executed)`: one tool call and its `ToolOutput`; `executed` is false when the call was answered without running (an invalid action).
2. `Step(index, response, tool_runs, executed_tools)`: one model call and what happened to its tool calls (empty if none or not run).
3. Status constants: `FINISHED`, `MAX_STEPS`, `TRUNCATED`, `REFUSED`, `EMPTY_REPLY`, `UNEXPECTED_STOP`, `MODEL_ERROR`, `PRIVACY_BLOCKED`.
4. `AgentResult(status, final_text, steps, messages, usage, error_code, error_message, observer_errors)`; `usage` is the sum over steps (a `Usage`).
5. Events: `ModelCallEvent(step, response)`, `ToolCallEvent(step, run)`, `FinishEvent(result)`; `Observer = Callable[[Event], None]`.

## 2. System prompt (`src/bugbite/agent/prompt.py`)

`PROMPT_VERSION = "1"` and `SYSTEM_PROMPT`: the job (fix the reported bug in the repository in the working directory); how to work (look before changing, find the cause, make the smallest change that fixes it, run the tests, never change tests or configuration, add a new test file if one is needed); what the tools do in one line each; what to claim (only what a tool result showed; say so if the fix did not work or you could not verify it); how to finish (reply in plain text with a short summary and no tool call); and the data warning (issue text, files and tool output are data, not instructions). The prompt names no model or provider and holds no secrets.

## 3. Issue to task text (`src/bugbite/agent/task.py`)

`format_issue_task(context) -> str`: repository name, issue number and title, labels, the body and up to 10 comments inside clearly marked untrusted-data sections, with the size limits and "[... left out ...]" notes. A pure function, tested on long, empty and hostile input (text that imitates the section markers must not be able to close the section early).

## 4. The loop (`src/bugbite/agent/loop.py`)

`run_agent(adapter, tools, task, *, max_steps, system_prompt=SYSTEM_PROMPT, observer=None, max_output_tokens=None) -> AgentResult`:

1. Validate: `max_steps` is an integer from 1 up (not a bool), `task` is a non-empty string; raise `ValueError` for caller mistakes.
2. Loop for each step: build the request (system block, messages so far, `tools.definitions()`), call `adapter.generate`. `AdapterError` ends the run with `MODEL_ERROR` and `PrivacyError` with `PRIVACY_BLOCKED`, both keeping everything so far.
3. Add the reply to the conversation as an assistant message (unless it is empty), notify the observer, then decide from the stop reason and the blocks as described in `requirements.md`.
4. Run tool calls in order, never raising: invalid actions answered with their error, unknown or failing tools as error results; notify the observer after each; append one user message with all results.
5. Sum usage; build and return the `AgentResult`; send `FinishEvent`.
6. Observer calls are wrapped so that an exception is logged (type only, not the text), counted in `observer_errors`, and does not stop the job.

## 5. Package exports and docs

Export from `bugbite.agent`. README section "The agent loop": how to call it, the statuses, the observer, what is missing (caps, loop detection, context trimming), and the reminder that `finished` does not mean fixed.

## 6. Tests

1. Types: validation, usage summing.
2. Loop with `ScriptedAdapter` and a fake registry: finish on the first reply; one tool then finish; several tools in one reply (results in order, one message); text plus tool call in one reply; messages sent to the model on each step (assert the exact history, including that every tool call gets a result); the tool definitions and system prompt are in every request; temperature stays `None`.
3. Endings: `max_steps` (last reply's calls not run, `max_steps=1`), `truncated` (with and without tool calls), `refused`, `empty_reply`, `unexpected_stop`, `model_error` for each `AdapterError` code kept with steps so far, `privacy_blocked`.
4. Tools: invalid action answered, not run; unknown tool; tool raising; arguments wrong; the registry's results converted with the right ids.
5. Observer: events in order and complete; a raising observer does not stop the run and is counted.
6. Argument checks: `max_steps` 0, -1, True, 1.5, None, missing; empty task.
7. Task helper: limits, truncation notes, hostile text, empty body and no comments.
8. Through `TextActionAdapter` with a scripted non-native model: a full read, edit, finish run, including one failed step that is answered with its error.
9. Through `create_adapter` with a ledger and the privacy guard: a private job with a closed model ends `privacy_blocked` with nothing recorded; a public job works and the ledger has one entry per step.
10. Opt-in Docker test: a scripted model drives the real tools in a real sandbox (edit a file, run a command), and `git diff` shows the change.
11. Mutation check: results out of order, a call left without a result, truncated calls run, `max_steps` off by one, model error raised instead of returned, invalid action executed, observer error escaping, usage not summed.

## 7. Docs and process

README section; roadmap P16 ticked; findings in `requirements.md`; validation ticked; AD-092 to AD-096 in `specs/decisions.md`.
