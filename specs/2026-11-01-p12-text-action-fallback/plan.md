# Plan: Text-Action Fallback (Roadmap P12)

Branch: `2026-11-01-p12-text-action-fallback`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-070 onward).

## 1. Dependency

Add `jsonschema` with `uv add jsonschema` (AD-073). Record the version. Tool parameter schemas are checked with its Draft 2020-12 validator.

## 2. The action format and the parser (pure, no model calls)

Create `src/bugbite/adapter/text_action.py` (the parser and prompt parts first):

1. **Format (AD-071).** A reply holds exactly one JSON action:
   - a tool call: `{"tool": "<name>", "arguments": {...}}` (`arguments` may be left out when the tool needs none)
   - a final answer: `{"final": "<text>"}`
   Other keys (such as `thought`) are ignored.
2. `parse_action(text, tools) -> ParsedAction | ActionError`:
   - find every top-level JSON object in the reply by decoding from each `{`; prose and code fences around them are ignored and the prose is kept
   - an object is an action when it has a text `tool` or a text `final`; identical repeated actions count once
   - no action, more than one different action, an object with both `tool` and `final`, a `tool` that is not text, `arguments` that is not an object, an unknown tool name (the message lists the valid names), or arguments that break the tool's schema are all errors, each with a specific, short message
   - unparseable JSON gives the decoder's reason (trailing comma, single quotes, and so on); a reply that looks cut off by the token limit says so
3. **Schema check.** Validate `arguments` with `jsonschema`; report the best-matching error with its path (for example `arguments.path: 'x' is not of type 'integer'`). A tool whose own schema is invalid is refused locally before any call.
4. `PROMPT_VERSION = "1"` and the instruction block: tool list with descriptions and parameter schemas, the two shapes, a worked example for each, and the rule "one action per reply". The version is exposed for recordings (FR10.4).

## 3. The wrapper adapter

1. `TextActionAdapter(inner)` in the same module, a `ModelAdapter` with the inner adapter's config and name (AD-070).
2. **Requests without tools** pass straight to the inner adapter untouched.
3. **Requests with tools:**
   1. run `validate_request`
   2. build a text-only request (section 4) and call the inner adapter
   3. parse the reply; a valid action becomes the response (section 5)
   4. an invalid reply gets exactly one repair attempt: the same request plus the bad reply and a short message saying what was wrong and how to reply (AD-072)
   5. if the repair is also invalid the step has failed: the response holds a tool call named `invalid_action` with empty arguments and an `error` describing the problem, plus the model's last reply as text
4. A refusal from the inner adapter, and any `AdapterError`, pass through with no repair (repairing a refusal or a rate limit makes no sense).
5. `stats` counts steps, repaired steps, and failed steps (thread-safe), for model comparison and failure analysis.
6. `close()` and `estimate_tokens` delegate to the inner adapter.

## 4. Turning a tool conversation into plain text

1. System prompt: the original system blocks, then the instruction block.
2. User messages: tool results become text naming the tool and call id (`[result of read_file call ta_2]`), with errors marked; any other text stays as it is.
3. Assistant messages: a tool call becomes its JSON action; text before it stays; an assistant message with no tool call becomes a `{"final": ...}` action, so the format stays consistent in the history.
4. Failed steps: an `invalid_action` call is not rendered as an action (that would teach the format wrongly); the model's own failed reply text is shown, and its tool result becomes "Your previous reply was not a valid action: ...".
5. Tool-call ids are `ta_<n>`, where n is one more than the number of tool calls already in the conversation, so ids are unique and the same history always gives the same ids.
6. Cache flags, temperature, stop sequences, and the output cap carry over; the tool list does not.

## 5. Turning a reply into a response

1. A valid tool action: blocks = the prose before or after it (if any) as text, then one tool call; stop reason `tool_use`. A valid final answer: one text block; stop reason `end_turn`.
2. Usage, latency, and estimated-flag are summed over every model call the step made, so the response describes the whole step. The model and request id come from the last call.
3. A failed step has stop reason `tool_use` (the loop must answer the `invalid_action` call).

## 6. Wiring and cost accounting (AD-074)

1. In `create_adapter`: a model with `native_tool_calling: false` is built as `TextActionAdapter(metered inner)`, so every model call, including a repair, is its own ledger entry; the response the loop sees carries the summed usage. Native models are unchanged. Document that metering goes inside the wrapper, never outside it.
2. Update the registry tests that expect the plain adapter for `local-free`.

## 7. Tests

1. **Parser:** code fences, prose before and after, nested and string-embedded braces, unicode, two different actions, duplicate identical actions, trailing comma, single quotes, truncated reply, top-level list, `tool` and `final` together, wrong types, missing `arguments`, unknown tool, schema violations (required, type, enum, nested, additional properties), an invalid tool schema, very long replies, and a round trip (render an action, parse it back, same call).
2. **Translation:** instruction block content and version, history rendering (calls, results, errors, final answers, failed steps), deterministic ids, cache flags and options kept, tools removed.
3. **Flow with a scripted inner adapter:** valid first try; repair succeeds; repair fails; exactly one repair (the inner adapter is never called a third time); usage and latency summed; stats counted; refusal and adapter errors pass through unrepaired; requests without tools pass through untouched; the shared `AdapterContract` passes.
4. **Wiring:** `create_adapter` wraps non-native models and not native ones; the ledger holds two entries for a repaired step and the response carries their sum.
5. **End to end:** a non-native model served through the OpenAI-compatible adapter on a mock transport: the HTTP request has no `tools` field, carries the instructions, and a JSON reply in the mock's answer becomes a tool call.
6. **Properties:** over a seeded set of random replies the parser never raises and never returns an action that violates the tool schema.
7. Break the parser and wrapper on purpose (ignore the schema, allow two repairs, treat prose as a final answer, accept two actions, skip the passthrough) and confirm the tests fail.

## 8. Docs and wrap-up

1. Add AD-070 to AD-075 to `specs/decisions.md` (written with the specs). Tick P12 in `specs/roadmap.md`.
2. README: how models without native tool calling work, the action format, the repair rule, and how to read repair counts.
3. Commit in small logical commits, then merge into `main` with `--no-ff` and push when asked. Commit messages carry no co-author trailer.
