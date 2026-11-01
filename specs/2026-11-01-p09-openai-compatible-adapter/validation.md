# Validation: OpenAI-Compatible Adapter (Roadmap P9)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable and no internet: only Docker, internet, and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Request translation** is tested for: system text joined into one system message; cache markers ignored; empty text skipped; user text; assistant text with and without tool calls (arguments sent as JSON strings, `content` an empty string when there is only a tool call); tool results as separate `tool` messages with `tool_call_id`; a user message with tool results and text (tool messages first); tools in function format; `temperature`; `max_tokens` taken from the request or the model default; `stop`; `stream` false; `model` from config.
- [x] A request with tools for a model configured without native tool calling is rejected as `invalid_request` before any network call, and the message names the text-action wrapper.
- [x] **Response parsing** is tested for: plain text; text with a null `content`; list-of-parts content; reasoning fields ignored; tool calls with string arguments, object arguments, empty arguments, invalid JSON arguments (empty dict plus `error`), non-object arguments, missing and duplicate ids, several calls; a tool call without a name giving `bad_response`.
- [x] **Stop reasons**: `stop`, `length`, `tool_calls`, `content_filter`, unknown, and `null` map correctly; tool calls with `stop` become `tool_use`; tool calls with `length` stay `max_tokens`; `raw_stop_reason` keeps the server's value.
- [x] **Usage**: normal counts; cached tokens subtracted from input and reported as cache reads; missing usage, partial usage, negative or non-integer usage are estimated and flagged `usage_estimated`; reported usage is not flagged.
- [x] **Errors**: every row of the mapping table is tested, including context-length wording in several shapes (`code`, `message`), `Retry-After` as seconds and as an HTTP date, error bodies shaped as `{"error": {...}}`, `{"error": "text"}`, `{"message": "text"}`, plain text, and empty; an `error` object inside a 200; non-JSON 200; wrong JSON type; no choices; redirects not followed; timeout; connection error.
- [x] Error messages include the provider's message shortened to 300 characters and never include the request body, headers, or API key.
- [x] Headers: `Authorization` present only when a key was given; content type JSON; base URL joined correctly with and without a trailing slash and with a path such as `/v1`.
- [x] The key never appears in any exception message, `str`, `repr` of the adapter, or captured log output, across all error paths.
- [x] Invalid requests are rejected without any network call (the mock sees zero requests); the request object is not modified.
- [x] The shared `AdapterContract` tests pass for this adapter.
- [x] **Real-socket tests** on loopback pass: success round trip with real HTTP; slow server gives `timeout`; closed port gives `network_error`; `429` with `Retry-After` gives `rate_limited` with the value; connection dropped mid-response gives an adapter error (not a crash); a large response parses.
- [x] `GenerationResponse.usage_estimated` defaults to false, round-trips through JSON, and is strictly decoded; P8 tests are updated accordingly.
- [x] `import bugbite.adapter` registers `openai_compatible`; `create_adapter` builds it for keyless local models and requires a key when `api_key_env` is set; `claude` is still unregistered.
- [x] The shipped `config/models.yaml` loads; `groq-free` has `allow_private_code: false`, price 0, `api_key_env: GROQ_API_KEY`, and every unverified value is commented `confirm`.

## Live check (needs a Groq key)

- [ ] **Live check NOT RUN (2026-11-01): no `GROQ_API_KEY` was available.** To run it: `BUGBITE_LIVE_TESTS=1 GROQ_API_KEY=... uv run pytest tests/adapter/test_live_openai_compatible.py -s`, then record the result, date, model, and the limits and terms read from Groq's own pages in `requirements.md` under findings. Until then this box stays unticked.

## Manual checks

- [x] `git grep -nE "groq|ollama|openrouter|anthropic" src/bugbite/adapter` returns nothing (no provider names in adapter code; they live in config).
- [x] `git grep -nE "os.environ|getenv" src/bugbite/adapter` returns nothing.
- [x] `git grep -nE "follow_redirects=True|retry|sleep" src/bugbite/adapter` shows no redirects or retries.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.
- [x] Error messages spot-checked for clarity (one per code).
- [x] `.env.example` lists `GROQ_API_KEY` with no value.

## Docs and process

- [x] `specs/decisions.md` has AD-052 to AD-057 with reasons.
- [x] `specs/roadmap.md` has P9 ticked (with the live-check status stated: not run).
- [x] README explains the adapter's use, the free-tier cautions, and the live test.
- [x] Commits are small and logical on branch `2026-11-01-p09-openai-compatible-adapter`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no Claude adapter, cost tracking, fallback, or privacy gate).

## Definition of done

All boxes ticked except, if no key was available, the live check, which must then be stated plainly as not run. Tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
