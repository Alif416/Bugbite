# Plan: Claude Adapter (Roadmap P10)

Branch: `2026-11-01-p10-claude-adapter`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-058 onward).

## 1. Interface changes the Claude API forces (affect P8 and P9 code)

1. **Optional temperature (AD-059).** `GenerationRequest.temperature` becomes `float | None = None`, where `None` means "the provider's default". JSON conversion accepts `null`. `validate_request` checks the 0 to 2 range only when a value is given.
2. **P9 follows:** the OpenAI-compatible adapter sends `temperature` only when it is not `None`. Update its tests and the shared contract helpers, which currently assume `0.0`.
3. **Refusals:** add `refusal` to the normalised stop reasons (`STOP_REFUSAL`), and to `STOP_REASONS` and its tests.
4. **Cache switch:** add `prompt_caching` to `ModelConfig` (`"auto"` default, `"explicit"`, or `"off"`), validated on load. Providers without prompt caching ignore it.
5. **Shared helpers:** move the Retry-After parser, the message shortener, and the credential redaction from `openai_compatible.py` into `src/bugbite/adapter/_http.py` so both adapters use one copy; `openai_compatible` keeps importing the same names.

## 2. Dependency

Add the official `anthropic` package with `uv add anthropic`. Record its version. Check what the installed release does with `temperature`, `top_p`, and `top_k`, how it is mocked in tests (its HTTP client), and which API version header it sends; write what is found into `requirements.md`.

## 3. The adapter

Create `src/bugbite/adapter/claude.py` with `ClaudeAdapter(config, api_key=None, *, timeout=120.0, client=None)`. It uses the official SDK (AD-058) with `max_retries=0`, takes `base_url` from the model config, never reads the environment, and never logs or echoes the key.

### Request translation
1. `system` becomes a list of text blocks; empty blocks are skipped.
2. User text becomes text blocks. Tool results become `tool_result` blocks with `tool_use_id`, `content`, and `is_error` when set; **tool results are placed before any text in the same user message** (the API requires this).
3. Assistant messages become text blocks plus `tool_use` blocks (`id`, `name`, `input`).
4. Tools become `{name, description, input_schema}`. `tool_choice` is left at the default.
5. `max_tokens` is the request's value or the model's default. `stop_sequences` are passed when given.
6. **Temperature:** `None` or exactly `1.0` are accepted and nothing is sent; any other value raises `invalid_request` before any network call, saying this model only supports its default (AD-059). No sampling parameter is ever sent.
7. **Thinking is turned off** with `thinking: {"type": "disabled"}` (AD-060). Models that reject disabled thinking therefore fail with the API's own error mapped to `invalid_request`; supporting them is the later pass-through phase.
8. **Prompt caching (AD-061).** Mode `auto` sets the API's top-level `cache_control` so the conversation prefix is cached on every call, and also honours `cache` flags on text blocks. Mode `explicit` honours only the flags. Mode `off` sends no cache markers. At most four markers are sent per request in total; when more are flagged, the last ones are kept (a later marker covers everything before it) and the rest dropped.
9. `validate_request` runs first, before any network call. Tools are accepted even when `native_tool_calling` is false (Claude always supports them).

### Response parsing
1. Content blocks: `text` becomes text, `tool_use` becomes a tool call (`input` is already an object, so `error` stays `None`). `thinking`, `redacted_thinking`, and any block type not understood are ignored.
2. Stop reasons: `end_turn`, `tool_use`, `max_tokens`, and `stop_sequence` map to their normalised names; `refusal` maps to `refusal` (the category is appended to the raw value, for example `refusal:cyber`); `pause_turn`, `model_context_window_exceeded`, and anything new map to `other`. The raw value is kept.
3. Usage: `input_tokens`, `output_tokens`, `cache_creation_input_tokens` (cache writes), and `cache_read_input_tokens` (cache reads). Missing cache fields count as zero. Absent usage is estimated and flagged `usage_estimated`.
4. `model` and `request_id` come from the response; latency is measured around the call.

### Errors (AD-058)
| SDK error / status | Code |
|---|---|
| 400 saying the prompt is too long or over the context window; 413 | `context_too_long` |
| other 400, 404 (unknown model), 422, other 4xx | `invalid_request` |
| 401, 402, 403 | `auth_failed` |
| 429 (with `retry_after_s` from `Retry-After`) | `rate_limited` |
| 5xx including 529 overloaded | `server_error` |
| timeouts | `timeout` |
| connection failures | `network_error` |
| anything unreadable | `bad_response` |

The API's own error message is included, shortened to 300 characters, with the key and any `Bearer` token redacted. Request bodies and headers are never included. No retries.

## 4. Registration and config

1. Register the adapter for the `claude` provider when `bugbite.adapter` is imported.
2. Update the `haiku` entry in `config/models.yaml` with the verified values (AD-063): `context_window: 1000000`, input price `0.0000001` and output price `0.0000005` per token, `prompt_caching: auto`, comments recording the source and date, and a note about the over-100K-token price tier that cost tracking (P11) will model. Remove the old `confirm` comments for values that are now verified; keep one for anything still unverified.

## 5. Tests

1. **Protocol tests** (mock transport, no network): every translation rule, including the tool-result ordering, temperature handling, thinking disabled, all three cache modes with the four-marker limit, and no sampling parameter ever sent; every parsing rule; every error row, with no retries (the mock sees one request); key redaction and the key never in errors, `repr`, or logs; validation before any network call; the request not modified.
2. **Contract tests:** the shared `AdapterContract` class, with its helpers changed to the portable temperature (`None`).
3. **Loopback server tests:** success over real HTTP with the headers the SDK sends (`x-api-key`, version, content type), `Retry-After` on 429, a slow server giving `timeout`, a closed port giving `network_error`, a dropped connection.
4. **Registry and config tests:** the provider is registered and keyless/keyed rules hold; `prompt_caching` validation; the shipped `haiku` entry matches the verified numbers.
5. **Live test** (opt-in, `BUGBITE_LIVE_TESTS=1` and `ANTHROPIC_API_KEY`): a plain call, a tool call with its follow-up, and two calls sharing a long prefix to show `cache_read_tokens` greater than zero on the second; it prints usage and the cost at the official prices. If it is not run, the validation file says so.
6. Update the P8 and P9 tests for the optional temperature and the new stop reason.

## 6. Docs and wrap-up

1. Add AD-058 to AD-064 to `specs/decisions.md` (written with the specs). Tick P10 in `specs/roadmap.md`, stating the live-check status. Add "P10b: thinking pass-through" to the roadmap and a note to P11 about cache prices and the long-prompt tier.
2. README: using a Claude model, the temperature rule, the thinking-off limitation, prompt caching modes, the live test, and the corrected Haiku prices.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked. Commit messages carry no co-author trailer.
