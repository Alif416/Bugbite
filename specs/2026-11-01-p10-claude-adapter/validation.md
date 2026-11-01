# Validation: Claude Adapter (Roadmap P10)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable and no internet: only Docker, internet, and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [ ] **Interface changes:** `GenerationRequest.temperature` defaults to `None`, accepts `None` and numbers, round-trips `null` through JSON, and `validate_request` checks the 0 to 2 range only for numbers (NaN and out-of-range still rejected); `STOP_REFUSAL` exists and is in `STOP_REASONS`; the OpenAI-compatible adapter sends `temperature` only when set (and still sends `0` when asked for `0`); P8 and P9 tests are updated and pass.
- [ ] `ModelConfig.prompt_caching` defaults to `auto`, accepts `auto`, `explicit`, `off`, and rejects anything else naming the field; the shipped config loads.
- [ ] **Request translation** is tested for: system blocks with and without cache flags and empty blocks skipped; user text; assistant text with tool calls (`input` is an object); tool results before text in the same user message; `is_error` set only when true; tools in `input_schema` form; `max_tokens` from the request or the model default; `stop_sequences`; `thinking` disabled on every request; **no `temperature`, `top_p`, or `top_k` ever sent**; `base_url` taken from the model config.
- [ ] **Temperature:** `None` and `1.0` are accepted; `0`, `0.5`, `1.5`, `2` raise `invalid_request` before any network call with a message naming the model.
- [ ] **Caching modes:** `auto` sets top-level cache control and also marks flagged blocks; `explicit` marks only flagged blocks and sets no top-level cache control; `off` sends no cache markers at all, even for flagged blocks; more flagged blocks than allowed keeps the last ones so the total never exceeds four markers (including the top-level one in `auto`).
- [ ] **Response parsing:** text; tool use (one and several, with order kept); text mixed with tool use; thinking, redacted thinking, and unknown block types ignored; empty content; model and request id; latency.
- [ ] **Stop reasons:** `end_turn`, `tool_use`, `max_tokens`, `stop_sequence` map to themselves; `refusal` maps to `refusal` with the category kept in the raw value; `pause_turn`, `model_context_window_exceeded`, and an unknown value map to `other`; `raw_stop_reason` always holds the provider's value.
- [ ] **Usage:** input, output, cache-creation (to cache writes), and cache-read tokens map correctly; missing or null cache fields count as zero; absent usage is estimated and flagged; reported usage is not flagged.
- [ ] **Errors:** every row of the mapping table is tested through real status responses (400 with and without context-length wording, 401, 402, 403, 404, 413, 422, 429 with `Retry-After`, 500, 529), timeouts, and connection failures; **the mock sees exactly one request for 429 and 5xx** (no SDK retries).
- [ ] Messages carry the API's own message shortened to 300 characters; the API key and any `Bearer` token are redacted when echoed; request bodies and headers never appear; the key is not in any exception, `str`, `repr`, or captured log output.
- [ ] Invalid requests are rejected without any network call; the request object is not modified.
- [ ] The shared `AdapterContract` tests pass for this adapter.
- [ ] **Loopback server tests** pass: a round trip over real HTTP showing the headers sent (`x-api-key`, API version, content type) and the body; `429` with `Retry-After` gives `rate_limited` with the value; a slow server gives `timeout`; a closed port gives `network_error`; a dropped connection gives an adapter error.
- [ ] `import bugbite.adapter` registers `claude`; `create_adapter` builds it for the shipped `haiku` entry with a key and raises without one; both real providers are now registered.
- [ ] The shipped `haiku` entry has the verified values (1M context, input $0.10 and output $0.50 per million tokens, `prompt_caching: auto`, `api_key_env: ANTHROPIC_API_KEY`) and comments recording the source and the date.
- [ ] Shared helpers (`parse_retry_after`, shortening, redaction) live in one module and both adapters use them; the P9 tests still pass.

## Live check (needs an Anthropic key)

- [ ] **Run with a real key, or state plainly that it was not run.** `BUGBITE_LIVE_TESTS=1 ANTHROPIC_API_KEY=... uv run pytest tests/adapter/test_live_claude.py -s` passes: a plain call, a tool call with its follow-up, and a repeated long prefix showing `cache_read_tokens` greater than zero on the second call. Record the date, model, tokens, and cost at the official prices in `requirements.md` under findings. If no key was available, this box stays unticked and the file says "live check not run".

## Manual checks

- [ ] `git grep -nE "haiku|claude-|groq|ollama|openrouter" src/bugbite/adapter` shows no model names in adapter code (the provider name `claude` in registration is allowed).
- [ ] `git grep -nE "os.environ|getenv" src/bugbite/adapter` returns nothing.
- [ ] `git grep -nE "temperature|top_p|top_k" src/bugbite/adapter/claude.py` shows them only in the refusal-to-send logic and comments, never in a request.
- [ ] `max_retries=0` is set on the SDK client (read once).
- [ ] The only new dependency is `anthropic` and what it brings (note the version).
- [ ] Error messages spot-checked for clarity (one per code).
- [ ] `.env.example` already lists `ANTHROPIC_API_KEY` with no value.

## Docs and process

- [ ] `specs/decisions.md` has AD-058 to AD-064 with reasons.
- [ ] `specs/roadmap.md` has P10 ticked with the live-check status stated, and lists P10b; P11's line mentions cache prices and the long-prompt tier.
- [ ] README explains the Claude adapter, the temperature and thinking limits, caching modes, the corrected prices, and the live test.
- [ ] Commits are small and logical on branch `2026-11-01-p10-claude-adapter`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no cost tracking, thinking pass-through, fallback wrapper, or privacy gate).

## Definition of done

All boxes ticked except, if no key was available, the live check, which must then be stated plainly as not run. Tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
