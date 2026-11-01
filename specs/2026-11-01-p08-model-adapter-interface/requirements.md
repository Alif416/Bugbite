# Requirements: Model Adapter Interface and Model Config (Roadmap P8)

## Goal

Define the one interface that every model goes through, so the agent never depends on a particular model or provider (FR5.1, FR14.1). This phase fixes the shapes of requests, responses, tool calls, usage, stop reasons, and errors, plus the model configuration they depend on (FR14.3). The OpenAI-compatible adapter (P9), the Claude adapter (P10), cost tracking (P11), the text-action fallback (P12), the privacy gate (P13), the agent loop (P16), and record and replay (P22 to P24) are all built on what is decided here.

## Scope

**In:**
- Provider-neutral request, message, content-block, tool, usage, stop-reason, and response types, with exact JSON conversion for recording
- The abstract `ModelAdapter` with `generate`, `estimate_tokens`, and shared request validation
- Normalised `AdapterError` with stable codes
- `ModelConfig` additions (`api_key_env`, `max_output_tokens`, `integration`) and stricter model-config validation
- An adapter registry and factory (`create_adapter`)
- `ScriptedAdapter` for tests, and a reusable adapter contract test class
- Documentation of the interface

**Out (later phases):**
- Real adapters: OpenAI-compatible (P9) and Claude (P10)
- Cost calculation and per-call usage storage (P11); this phase only defines `Usage`
- The text-action fallback (P12); it will wrap any adapter and use this same interface
- Privacy checks on where code is sent (P13)
- Retries, backoff, queueing, and resume (FR14.5, P51)
- Context trimming (FR14.8, P28); only a token estimate hook is provided here
- Recording and replay (P22 to P24); only the JSON conversion they will use is provided
- Streaming responses

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Calling style | Synchronous | Simple loop, simple replay; parallelism through worker processes later; the owner's choice (AD-045) |
| Message format | Bugbite's own neutral dataclasses with content blocks | Provider-independent recordings; each adapter translates; the owner's choice (AD-046) |
| Streaming | Whole responses only | Easier to record, replay, and cost; dashboard progress comes from loop events; the owner's choice (AD-047) |
| Tool calls | Parsed arguments plus an `error` field; strict conversation-shape validation before any call | Weak models emit bad JSON; invalid requests must not cost money (AD-048) |
| Errors | One `AdapterError` with stable codes; no retries inside adapters | Policy lives in one place later (AD-049) |
| Keys and config | Caller passes the key; `api_key_env` names the variable; providers validated | Same secret-handling rule as the GitHub client (AD-050) |
| Fallback and tests | Text-action as a wrapper adapter; `ScriptedAdapter` and a contract test class | One interface for all models, testable with no provider (AD-051) |

See `specs/decisions.md` AD-045 to AD-051.

## Context

- README: FR5.1 (no model or provider name hard coded; Haiku default by config), FR14.1 (one adapter interface; input messages, tool definitions, config; output normalised text, tool calls, token usage, stop reason), FR14.3 (model config fields), FR14.4 (text-action fallback, built on this interface), FR14.6 (usage per call), FR14.7 (record and replay works for every adapter), FR13.2 (same temperature for all models in a comparison), FR13.8 (report the integration method).
- Mission principles: model-agnostic; secrets never in code or logs; measured claims; honest failures.
- Builds on P1: `ModelConfig` already carries provider, base URL, model name, context window, native tool-call support, prices, per-issue cap, and the private-code flag. P8 adds only what the interface needs.
- Prompt caching is on for Claude from day one (README cost rules), so content blocks carry a cache marker that adapters without caching ignore.
- Free local models have no API key, hence `api_key_env` is optional.

## Constraints

- No provider SDK imports in the interface modules; only the standard library plus existing dependencies.
- Types are immutable, and JSON conversion is exact: converting to JSON and back gives an equal object.
- Request validation runs before any network call, so a malformed conversation never spends tokens.
- No secrets are read from the environment by adapters or the registry.
- Error messages never contain API keys or request bodies.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Cache price fields (cache reads and writes are priced differently from normal input) are added to `ModelConfig` in P11 with cost tracking.
- Whether the response should carry the provider's raw payload for debugging is deferred to P22, where the recorder decides what to keep.
- Image or file inputs are not supported; text only.
- Token estimates are a rough heuristic; exact counts, where a provider offers them, can be added per adapter later.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-045 to AD-051).
