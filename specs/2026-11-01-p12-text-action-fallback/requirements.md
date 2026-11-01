# Requirements: Text-Action Fallback (Roadmap P12)

## Goal

Let models that cannot reliably call tools natively (most small local and free models) do the same agent work, through the same interface, so the agent loop never needs to know which kind of model it is talking to (FR14.4, FR5.3). The model writes one JSON action per turn; the wrapper parses and validates it, asks for one repair when it is wrong, and otherwise reports a failed step honestly.

## Scope

**In:**
- `TextActionAdapter`: a wrapper that gives any adapter a tool-calling interface through text
- The action format, the tolerant parser, and schema checking of arguments
- One repair attempt, and a recoverable failed step (`invalid_action`) after it
- Conversion of a tool conversation to plain text and back, with deterministic ids
- Summed usage on the step's response; per-call ledger entries; repair and failure counters
- Automatic wiring in `create_adapter` for models with `native_tool_calling: false`
- Instruction prompt with a version number

**Out (later phases):**
- The agent loop and how it counts failed steps toward its caps (P16, P17, P18)
- The tools themselves and their schemas (P14, P15)
- Privacy checks on where text is sent (P13)
- Retries and backoff for provider errors (P51)
- Few-shot tuning of the instruction prompt per model, and any model-specific prompt tricks
- Several actions in one reply (FR14.4 says one action per turn)
- Streaming

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Shape | Wrapper adapter, automatically applied to non-native models | The loop sees one interface (AD-051, AD-070) |
| Parsing | Tolerant extraction of the one JSON action; prose-only replies are invalid | Weak models add prose and fences; a chatty reply must never end the job early; the owner's choice (AD-071) |
| Failure | One repair attempt, then an `invalid_action` tool call carrying an error | The recoverable-step design from P8; the owner's choice (AD-072) |
| Validation | `jsonschema` against the tool's parameter schema | Complete, well-tested checks and clear messages; the owner's choice (AD-073) |
| Accounting | Each model call is its own ledger entry; the step's response carries the sum | Exact cost, countable repairs; the owner's choice (AD-074) |
| History | Calls rendered as JSON actions, ids `ta_<n>`, failed replies kept as text | Consistent format for the model and reproducible replays (AD-075) |

See `specs/decisions.md` AD-070 to AD-075.

## Context

- README: FR14.4 ("for models without reliable native tool calling, the model writes one JSON action per turn and the adapter parses and validates it; invalid output gets one repair attempt, then counts as a failed step"), FR5.2 and FR5.3 (the tools and the loop), FR13.8 (report the integration method, a known confounder), FR13.5 (failure counts per model), FR11 (failure labels), risks ("Free models handle tool calling badly").
- Builds on P8 (a tool call carries an `error` so the loop can answer it, AD-048), P9 (the OpenAI-compatible adapter refuses tools for non-native models, AD-054, so this wrapper is how those models get tools), P11 (the ledger, which must see each model call).
- The six planned tools are `read_file`, `search_code`, `edit_file`, `run_tests`, `run_command`, `list_directory`; their schemas are simple objects, but the wrapper must handle any valid JSON Schema.
- Model output is untrusted data. The parser must never raise on any text and must never return arguments that break the tool's schema.
- Whether a particular small model can follow the format well enough to be useful is an empirical question for the comparison phases; this phase makes the attempt possible and measurable.

## Constraints

- The parser never raises, whatever the reply contains.
- A returned tool call always names a tool from the request and always has arguments that satisfy its schema, except the deliberate `invalid_action` failed step.
- At most one repair per step; the inner adapter is called at most twice per step.
- Adapter errors and refusals are never repaired.
- No randomness: the same conversation and replies always give the same ids and text.
- The wrapper never reads the environment and never logs reply text.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- How the loop counts `invalid_action` steps against its step cap and loop detection (P17, P18) is decided there; this phase only guarantees the signal.
- The instruction prompt is generic; per-model tuning waits for real models, and any change bumps `PROMPT_VERSION`.
- Tokens spent on the instruction block and the repaired steps are a cost of the text-action method and will appear in the model comparison.
- Models that emit their action in an unexpected channel (a separate reasoning field, tool-call-like markup) are treated as having no action until a real model shows what is needed.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-070 to AD-075).
