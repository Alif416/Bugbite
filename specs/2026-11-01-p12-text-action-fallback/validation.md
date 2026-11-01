# Validation: Text-Action Fallback (Roadmap P12)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable and no internet: only Docker, internet, and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [ ] **Parser** (`parse_action`) returns the right result, or a specific error message, for each of:
  - [ ] a bare tool action, a bare final action, with and without `arguments`
  - [ ] the action inside a code fence (with and without a language tag), with prose before it, after it, and both
  - [ ] braces inside strings and nested objects in `arguments`; unicode and escaped characters
  - [ ] the same action repeated identically (one action); two different actions (error); an object with both `tool` and `final` (error)
  - [ ] no JSON at all; prose only; an empty reply; a top-level list; objects that are not actions
  - [ ] invalid JSON: trailing comma, single quotes, unquoted keys, truncated reply (the message mentions the token limit when the reply looks cut off)
  - [ ] `tool` not text; `arguments` not an object; unknown tool name (the message lists the valid names)
  - [ ] schema violations: missing required argument, wrong type, value not in an enum, bad nested value, extra property when not allowed; the message names the path
  - [ ] a tool whose own schema is invalid is refused locally with `invalid_request` and no model call
- [ ] **Properties:** over at least 500 seeded random replies (random text, random fragments of valid actions, random corruptions) the parser never raises, and every returned tool action names a request tool and satisfies that tool's schema.
- [ ] **Round trip:** rendering a tool call as its JSON action and parsing it back gives the same tool and arguments, for arguments with unicode, nesting, and special characters.
- [ ] **Translation:** the system prompt gains the instruction block (tool names, descriptions, schemas, both shapes, an example) and its `PROMPT_VERSION`; the request sent to the inner adapter has no tools; history renders calls as JSON actions, results with the tool name and call id, errors marked, final answers as `{"final": ...}`, failed steps as the model's own reply plus the "not a valid action" message; ids are `ta_<n>`, unique, and identical for identical histories; cache flags, temperature, stop sequences, and the output cap carry over; the original request object is not modified.
- [ ] **Flow with a scripted inner adapter:**
  - [ ] valid action first time: one inner call, no repair
  - [ ] invalid then valid: two inner calls, the repair request contains the bad reply and a specific message, the response is the repaired action, stats show one repaired step
  - [ ] invalid then invalid: exactly two inner calls (never a third), the response holds an `invalid_action` call with empty arguments and a non-empty `error`, stop reason `tool_use`, the model's last reply kept as text, stats show one failed step
  - [ ] usage, latency, and the estimated flag are summed over the step's calls; model and request id come from the last call
  - [ ] an inner `AdapterError` propagates unchanged with no repair; an inner refusal passes through with no repair
  - [ ] a request without tools passes through untouched (the very same response object) and is not counted as a step
  - [ ] an invalid request is rejected before any inner call
- [ ] **Contract:** the shared `AdapterContract` tests pass for the wrapper over a scripted inner adapter.
- [ ] **Wiring:** `create_adapter` returns the wrapper for `native_tool_calling: false` and the plain adapter for native models; with a ledger the wrapper's inner adapter is the metered one; a repaired step leaves two ledger entries while the response carries their sum; the registry tests for `local-free` are updated.
- [ ] **End to end:** a non-native model served by the OpenAI-compatible adapter over a mock transport: the HTTP request contains no `tools` field, the system message contains the instructions, and a JSON action in the mock's reply comes out as a tool call with the right arguments; a broken first reply triggers a second HTTP request; a second broken reply gives the `invalid_action` call.
- [ ] **Mutation check:** each of these deliberate breakages makes at least one test fail: schema validation skipped, two repairs allowed, prose-only treated as a final answer, two different actions accepted, the passthrough for requests without tools removed, usage not summed.

## Manual checks

- [ ] `git grep -nE "os.environ|getenv" src/bugbite/adapter` returns nothing new.
- [ ] The only new dependency is `jsonschema` and what it brings (note the version).
- [ ] The instruction prompt printed once for the six planned tool shapes reads clearly to a person (looked at once).
- [ ] A transcript of one repaired and one failed step reads sensibly (printed from a scripted run, looked at once).
- [ ] `git grep -nE "random|time\." src/bugbite/adapter/text_action.py` shows no randomness or clock use in the wrapper.

## Docs and process

- [ ] `specs/decisions.md` has AD-070 to AD-075 with reasons.
- [ ] `specs/roadmap.md` has P12 ticked.
- [ ] README explains non-native models, the action format, the repair rule, and how to read the counters.
- [ ] Commits are small and logical on branch `2026-11-01-p12-text-action-fallback`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no agent loop, tools, privacy gate, or retries).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
