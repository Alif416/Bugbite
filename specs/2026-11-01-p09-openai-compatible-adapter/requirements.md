# Requirements: OpenAI-Compatible Adapter (Roadmap P9)

## Goal

Let Bugbite talk to any model behind an OpenAI-style chat API (Ollama, Groq, OpenRouter, vLLM, and similar) through the adapter interface from P8, so free models can be used for development and for the model comparison without spending the 5 USD budget (FR14.2, README sections 4 and 9).

## Scope

**In:**
- `OpenAICompatibleAdapter`: request translation, tolerant response parsing, error mapping, no retries
- Native tool calling through the chat API's `tools` and `tool_calls`
- Registration for the `openai_compatible` provider
- A `groq-free` model entry with every unverified value marked, and the matching `.env.example` key
- `usage_estimated` flag on responses for servers that report no token counts
- Protocol tests (mock transport), contract tests, real-socket tests on loopback, and an opt-in live test

**Out (later phases):**
- The Claude adapter and prompt caching on Claude (P10)
- Cost calculation and per-call usage storage (P11)
- Text-action fallback for models without native tool calling (P12); P9 refuses to drop tools silently
- The privacy gate that stops private code reaching providers not marked as allowed (P13); P9 only records `allow_private_code: false` in config
- Retries, backoff, queueing, rate-limit waiting (FR14.5, P51)
- Streaming, images, embeddings, the Responses API
- Choosing and verifying a final comparison model list; that happens when the comparison runs (P62, P63)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Client | `httpx`, Chat Completions API, no vendor SDK | One small dependency already in use; works with every compatible server; full control of errors (AD-052) |
| Parsing | Tolerant of server differences | Free and local servers differ in ids, argument formats, content shapes (AD-053) |
| No native tools | Refuse clearly; do not drop tools | Silent loss of tools would produce confusing runs; P12 wraps (AD-054) |
| Errors | Mapped table; provider message shortened; no bodies or keys | Stable codes for the loop and queue (AD-055) |
| Missing usage | Estimate and flag `usage_estimated` | Measured claims only; the owner's choice (AD-056) |
| Free model | Hosted Groq tier, live check when a key is supplied; entry unverified | The owner's choice; limits and terms must be confirmed on Groq's own pages (AD-057) |

See `specs/decisions.md` AD-052 to AD-057.

## Context

- README: FR14.2 (an OpenAI-compatible adapter covering Ollama, Groq, OpenRouter, vLLM), FR14.4 (text-action fallback for models without reliable tool calling, built later), FR14.5 (rate limits, handled in P51), FR14.6 (usage per call), FR14.9 (free hosted tiers may use prompts for training, so only public repos and sandbox issues), FR13.9 (report the tier or hardware used for free models), risk table rows on free-model rate limits, tool calling, and changing terms.
- Builds on P8: `ModelAdapter`, `GenerationRequest` / `GenerationResponse`, `validate_request`, `AdapterError` and its codes, `ScriptedAdapter`, `AdapterContract`, `create_adapter`.
- What was found about free tiers on 2026-11-01 comes only from third-party pages, not the providers' own current documentation, so none of it is treated as verified:
  - Groq: free tier with no credit card; limits are per model; one source gives about 30 requests per minute but only about 8,000 tokens per minute and 200,000 tokens per day for `openai/gpt-oss-120b`. A prompt that carries repo context may exceed a per-minute token limit like that. Data terms for the free tier were unclear.
  - OpenRouter: free (`:free`) models reportedly allow 20 requests per minute and only 50 per day until about $10 of credits have been bought in total, then 1,000 per day.
- An agent run makes roughly 10 to 30 model calls per issue, so these limits decide how many benchmark issues a free tier can finish. The adapter reports `rate_limited` with the server's `Retry-After`; deciding what to do about it is P51.
- Model output is untrusted data, like issue text.

## Constraints

- The API key is only ever in the `Authorization` header: never in errors, logs, `repr`, or recordings.
- No redirects are followed (the key must not travel to another host).
- Requests are validated before any network call; a rejected request never reaches the server.
- Tools are never silently dropped.
- No retries or sleeping in the adapter.
- Default `uv run pytest` needs no internet, no key, and no Docker for these tests.
- The live test is never counted as done unless it was actually run.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- The model name, context window, tool-calling support, limits, and data terms in the `groq-free` entry must be confirmed on Groq's own pages before the first real run, and the date and terms recorded for the run (README risk table).
- The live check waits for the owner to create a free Groq account and set `GROQ_API_KEY`.
- Whether OpenRouter or a local Ollama model is added to the comparison is decided later (P63).
- Some servers need extra parameters (for example Ollama's `num_ctx`); revisit when a real local model is used.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-052 to AD-057).
