# Plan: OpenAI-Compatible Adapter (Roadmap P9)

Branch: `2026-11-01-p09-openai-compatible-adapter`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-052 onward).

## 1. One small change to the response type

1. Add `usage_estimated: bool = False` to `GenerationResponse` (and to its JSON form, with the same strict decoding as the other fields). It marks token counts that were estimated because the server did not report any (AD-056).
2. Update the P8 type and JSON tests. `SCHEMA_VERSION` stays 1: nothing has been recorded yet, so nothing needs migrating (recorded in AD-056).

## 2. The adapter

Create `src/bugbite/adapter/openai_compatible.py` with `OpenAICompatibleAdapter(config, api_key=None, *, timeout=120.0, client=None)`. It talks to `{base_url}/chat/completions` with `httpx` (AD-052). It never reads the environment, follows no redirects, sends the key only in the `Authorization` header (and only when a key was given), and never retries.

### Request translation
1. System text blocks are joined into one `system` message. Cache markers are ignored. Empty text blocks are skipped.
2. User text becomes `user` messages. Tool results become one `role: "tool"` message each, with `tool_call_id`, placed before any text from the same user message.
3. Assistant messages become `content` (the joined text, or an empty string) plus a `tool_calls` list whose `arguments` are JSON strings.
4. Tools become `{"type": "function", "function": {name, description, parameters}}`; `tool_choice` is left to the server's default.
5. Parameters: `model` from the config, `temperature`, `max_tokens` (the request's value or the model's default), `stop` when given, `stream: false`.
6. If the request has tools but the model is configured without native tool calling, raise `invalid_request` saying to use the text-action wrapper (P12). Tools are never silently dropped (AD-054).
7. `validate_request` runs first, before any network call.

### Response parsing (tolerant of server differences)
1. Require a JSON object with a non-empty `choices` list and a `message` object; otherwise `bad_response`.
2. `content` may be a string, `null`, or a list of text parts; reasoning fields (`reasoning`, `reasoning_content`) are ignored, not mixed into the text.
3. Tool call `arguments` may be a JSON string or an object. Unparseable or non-object arguments give an empty dictionary and a short `error` on the tool call (never an exception). Empty arguments are valid. A missing or empty id becomes `call_<n>`; duplicate ids are made unique. A tool call without a name is a `bad_response`.
4. Stop reasons: `stop` to `end_turn`, `length` to `max_tokens`, `tool_calls` to `tool_use`, anything else to `other`. If tool calls are present the stop reason is `tool_use` unless the server said `length`. The server's value is kept in `raw_stop_reason`.
5. Usage: `prompt_tokens` and `completion_tokens`; cached tokens (`prompt_tokens_details.cached_tokens`) are subtracted from the input count and reported as cache reads (AD-046 note). Missing or malformed usage is estimated and flagged `usage_estimated`.
6. `model` and `request_id` come from the response (falling back to the config and the `x-request-id` header); latency is measured around the call.

### Errors (AD-055)
| Situation | Code |
|---|---|
| 400 mentioning context length or too many tokens; 413 | `context_too_long` |
| other 400, 404 (unknown model or endpoint), 422, other 4xx | `invalid_request` |
| 401, 402, 403 | `auth_failed` |
| 408; httpx timeouts | `timeout` |
| 429 (with `retry_after_s` from `Retry-After`, seconds or HTTP date) | `rate_limited` |
| 5xx | `server_error` |
| connection refused, DNS, TLS, dropped connection | `network_error` |
| 3xx, non-JSON, wrong shape, no choices, `error` object inside a 200 | `bad_response` (or the code the embedded error maps to) |

The provider's own error message is included, shortened to 300 characters. Request bodies, headers, and the key are never included.

## 3. Registration and config

1. Register the adapter for the `openai_compatible` provider when `bugbite.adapter` is imported, so `create_adapter` works for such models. The factory passes the key through.
2. Add a `groq-free` entry to `config/models.yaml` with every unverified value marked `confirm` (base URL `https://api.groq.com/openai/v1`, `api_key_env: GROQ_API_KEY`, `allow_private_code: false`, prices 0, no model or limit claimed as verified). Keep the `local-free` placeholder.
3. Replace `OPENAI_COMPATIBLE_API_KEY` in `.env.example` with `GROQ_API_KEY`.

## 4. Tests

1. **Protocol tests** with `httpx.MockTransport` (no network): every translation rule above, every parsing rule, every error mapping row, headers (key present or absent), URL joining with and without a trailing slash, no redirect following, validation before any network call, request not modified, and the key never appearing in errors, `repr`, or logs.
2. **Contract tests**: the `AdapterContract` class from P8, run against this adapter over a mock backend.
3. **Real-socket tests** against a small HTTP server on the loopback interface (no internet): success over the wire, a slow server giving `timeout`, a closed port giving `network_error`, a 429 with `Retry-After`, a connection dropped mid-response, and a large response.
4. **Registry tests**: importing `bugbite.adapter` registers the provider; keyless local models work; a model with `api_key_env` needs a key.
5. **Live test** (`tests/adapter/test_live_openai_compatible.py`), opt-in: runs only when `BUGBITE_LIVE_TESTS=1` and `GROQ_API_KEY` are set; makes two calls (plain text, one tool call) against the `groq-free` entry and checks the responses are well-formed. Skipped by default and never counted as done unless it was actually run (the validation file says so plainly).
6. Update the P8 tests for `usage_estimated` and the registry test about unregistered providers.

## 5. Docs and wrap-up

1. Add AD-052 to AD-057 to `specs/decisions.md` (written with the specs). Tick P9 in `specs/roadmap.md`.
2. README: how to point a model at an OpenAI-compatible server, the free-tier cautions (limits and data terms must be checked on the provider's own pages, public repos only), and how to run the live test.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked. Commit messages carry no co-author trailer.
