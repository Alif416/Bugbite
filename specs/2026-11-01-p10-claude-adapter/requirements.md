# Requirements: Claude Adapter (Roadmap P10)

## Goal

Let Bugbite call Claude (Haiku 5.5 by default) through the adapter interface, with prompt caching on from day one, correct token accounting, and honest handling of what the Claude API will and will not accept (FR14.2, FR5.1, README cost rules). This is the paid model that the 5 USD budget is spent on, so correctness of usage and of the price data matters.

## Scope

**In:**
- `ClaudeAdapter` on the official `anthropic` SDK, with the SDK's own retries switched off
- Request translation, response parsing, error mapping, redaction
- Prompt caching in three modes (`auto`, `explicit`, `off`) through a `prompt_caching` model setting, defaulting to `auto`
- Optional temperature in the shared request type (`None` = provider default); the Claude adapter accepts only the default
- A `refusal` normalised stop reason
- Thinking turned off, with its limits stated
- Verified Haiku 5.5 values in `config/models.yaml`, replacing the earlier placeholders
- Shared HTTP helpers used by both real adapters
- Protocol, contract, loopback-server, registry, and opt-in live tests

**Out (later phases):**
- Thinking pass-through (provider-specific thinking blocks kept in the conversation) and a thinking on/off experiment: new phase P10b
- Cost calculation and per-call usage storage, including cache prices and the over-100K-token price tier (P11)
- Batches API, files, vision, server tools, streaming, structured outputs
- Fallback models after a refusal (Haiku 5.5 has no server-side fallback)
- Text-action fallback (P12) and the privacy gate (P13)
- Retries and backoff (P51)
- Other Claude models that cannot run with thinking off (Opus 5.5, Fable); they fail with the API's own error until P10b

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Client | Official `anthropic` SDK, `max_retries=0` | The project's API reference requires the SDK for Python; it tracks API versions and headers; retries stay out per AD-049 (AD-058) |
| Temperature | Optional in the interface; Claude accepts only the default | Haiku 5.5 rejects any other value; no silent ignoring; the owner's choice (AD-059) |
| Thinking | Off for now; pass-through in a later phase | Keeps the interface unchanged and context trimming safe; becomes a measurable experiment; the owner's choice (AD-060) |
| Caching | `auto` top-level plus honoured explicit markers; `explicit` and `off` available | Cache reads cost a tenth of normal input; supports the README caching experiment; the owner's choice (AD-061) |
| Refusals | Normalised `refusal` stop reason | The loop must handle declines explicitly; no server-side fallback exists on Haiku 5.5 (AD-062) |
| Prices | Official Haiku 5.5 values recorded with the date; tier modelling deferred to P11 | Corrects a 10 times error in the earlier placeholder (AD-063) |
| Helpers | One shared module for Retry-After, shortening, redaction | No duplicated safety code (AD-064) |

See `specs/decisions.md` AD-058 to AD-064.

## Context

- README: FR14.2 (a Claude adapter), FR5.1 (no model name in code; Haiku default by config), FR13.2 (same temperature across compared models), FR13.8 (report the integration method), FR14.6 (usage per call), cost rules ("prompt caching is on for Claude models from day one"), experiment 3 (prompt caching on or off, measured on cost), risk table ("Haiku is weaker than larger models").
- Verified on 2026-11-01 from the official pages (platform.claude.com, pricing and models overview):
  - Model ID `claude-haiku-5-5`; 1M token context window; 128K maximum output; default effort `medium`; adaptive thinking on by default.
  - Prompts up to 100,000 tokens: $0.10 per million input tokens, $0.50 per million output tokens, 5-minute cache writes $0.125, 1-hour cache writes $0.20, cache hits $0.01. Prompts over 100,000 tokens: $0.50 input, $2.50 output, $0.625 and $1 cache writes, $0.05 cache hits. A request's prompt length counts all its input tokens including cache reads and writes; each request is priced on its own.
  - The earlier placeholder in `config/models.yaml` ($1 and $5 per million) was Claude Haiku 4.5's price and ten times too high for typical prompts.
- From the project's API reference (a local copy dated 2026-10-06; behaviour to be confirmed by the live check):
  - Haiku 5.5 rejects any `temperature` other than the default: on API version `2023-06-01` it must be `1`; on version `2026-10-21` any value is a 400. The current Python SDK no longer accepts the argument at all.
  - `thinking: {"type": "disabled"}` is accepted at effort `low`, `medium`, and `high`.
  - Assistant prefill is a 400; a final assistant turn is not allowed (our validator already requires the last message to be from the user).
  - Safety classifiers can decline a request with `stop_reason: "refusal"` and a category; there is no server-side fallback for Haiku 5.5.
  - Minimum cacheable prefix is about 512 tokens (the reference says to check the caching docs before relying on it); cache reads are 0.1 times the input rate.
  - The same text counts as about 30 percent more tokens than on Haiku 4.5.
- Thinking blocks must be passed back unchanged, and editing earlier turns invalidates them on newer accounts. With thinking off there are none, so context trimming (FR14.8) stays safe.
- An agent run makes 10 to 30 calls per issue; at these prices a 20,000-token prompt costs about $0.002 uncached and about a fifth of that on cache hits, so the 0.10 USD per-issue cap is generous. The cap and budget logic itself belongs to P11 and P46.

## Constraints

- The API key appears only in the client's authentication; never in errors, logs, `repr`, or recordings.
- No sampling parameter (`temperature`, `top_p`, `top_k`) is ever sent to Claude.
- Requests are validated before any network call.
- The SDK's retries stay off (`max_retries=0`).
- Default `uv run pytest` needs no internet, no key, and no Docker for these tests.
- The live test is never counted as done unless it was actually run.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- The live check against the real API has not been run; the behaviours taken from the local API reference (temperature rule, thinking disabled, cache minimum) are unconfirmed until it is.
- Tiered pricing and cache prices are modelled in P11; until then any cost estimate from `config/models.yaml` alone ignores cache pricing and the over-100K tier.
- The default `max_output_tokens` of 4096 may be too small for large edits; revisit when the agent loop writes files.
- Per-message effort (a beta feature) and the `effort` setting are not used; the default `medium` applies. An effort setting can be added to the model config with P10b.
- Whether to run comparisons with every model at temperature 1.0 is decided when the comparison runs (P62).

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-058 to AD-064).

## Findings from the build (2026-11-01)

- **Live check not run.** No `ANTHROPIC_API_KEY` was available, so nothing was exercised against the real API. The behaviours taken from the local API reference (temperature rule, thinking disabled accepted at the default effort, the 512-token cache minimum) are still unconfirmed, and so is the cost of a real call. Everything else is verified against a mock of the SDK's HTTP layer, a loopback server (using the adapter's own default client), and the shared adapter contract.
- **SDK found: `anthropic` 2.3.0** (built on `httpx2`). It sends `Authorization: Bearer` (not `x-api-key`) and API version `2026-10-21`; `messages.create` has no sampling arguments at all, so no sampling parameter can be sent even by mistake. The SDK quirks that mattered (silent use of ambient credentials, redirects followed by default, error messages that repeat the whole body, malformed 200 responses returned as odd objects instead of errors) are listed under AD-058.
- Safety properties were checked by breaking them on purpose: removing the temperature rule, no longer disabling thinking, leaving the SDK's retries on, following redirects, not redacting the key, putting tool results after text, letting a malformed 200 pass, ignoring the top-level cache slot in the marker budget, and allowing an adapter without a key each made at least one test fail; the restored code passes.
- A test-writing error was caught on the way: the SDK itself coerces the string `"9"` to the integer 9 in usage counts, so that was not an adapter case.
