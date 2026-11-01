# Plan: Model Adapter Interface and Model Config (Roadmap P8)

Branch: `2026-11-01-p08-model-adapter-interface`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-045 onward).

## 1. Model config additions

1. In `src/bugbite/config.py`, extend `ModelConfig` with two optional fields (defaults at the end, so existing code keeps working):
   - `api_key_env: str | None = None`: the name of the environment variable that holds the API key (`None` for keyless local models)
   - `max_output_tokens: int = 4096`: the default cap on generated tokens for this model
2. Add `integration` as a read-only property: `"native"` when `native_tool_calling` is true, otherwise `"text_action"` (reported in model comparisons, FR13.8).
3. Tighten validation in `load_models_config`: `provider` must be one of the supported providers (`claude`, `openai_compatible`); `base_url` must start with `http://` or `https://`; `context_window` and `max_output_tokens` must be greater than zero and `max_output_tokens` must be smaller than `context_window`; `api_key_env`, when given, must look like an environment variable name.
4. Update `config/models.yaml`: `api_key_env: ANTHROPIC_API_KEY` for Haiku, none for the local free model. Update the existing config tests for the stricter provider check.

## 2. Errors

1. In `src/bugbite/errors.py` add `AdapterError(code, message, *, retry_after_s=None, status_code=None)` and the stable codes: `rate_limited`, `auth_failed`, `context_too_long`, `invalid_request`, `server_error`, `network_error`, `timeout`, `bad_response`.
2. Unit-test the codes, the validation, and that `retry_after_s` and `status_code` are carried.

## 3. Types (provider-neutral, frozen dataclasses)

Create `src/bugbite/adapter/types.py`:

1. Content blocks: `TextBlock(text, cache=False)`, `ToolCallBlock(id, name, arguments, error=None)`, `ToolResultBlock(tool_call_id, content, is_error=False)`. `arguments` is the parsed dictionary; if a weak model produced unparseable arguments, `arguments` is empty and `error` says why.
2. `Message(role, blocks)` with `role` either `"user"` or `"assistant"`, and helpers `Message.user(text)`, `Message.assistant(*blocks)`, `Message.tool_results(*results)`.
3. `ToolDefinition(name, description, parameters)`; `parameters` is a JSON Schema object. Names must match `[A-Za-z0-9_-]{1,64}`.
4. `GenerationRequest(system, messages, tools, temperature=0.0, max_output_tokens=None, stop_sequences=())`. The system prompt is a tuple of text blocks kept apart from messages, because providers handle it differently.
5. `Usage(input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0)`. `input_tokens` excludes cached tokens; `prompt_tokens` adds the three prompt counts and `total` adds the output tokens (AD-046 note).
6. Stop reasons, normalised: `end_turn`, `tool_use`, `max_tokens`, `stop_sequence`, `other`.
7. `GenerationResponse(blocks, stop_reason, usage, model, raw_stop_reason=None, latency_s=0.0, request_id=None)` with `text` (joined text blocks) and `tool_calls` properties.
8. JSON conversion for requests and responses: `to_dict()` and `from_dict()` with a `schema_version`. Unknown block types, missing fields, wrong types, and unknown versions are rejected with a clear error. Round-trips must be exact, including unicode.

## 4. The adapter base class and request validation

Create `src/bugbite/adapter/base.py`:

1. `ModelAdapter` (abstract): holds the `ModelConfig`; abstract `generate(request) -> GenerationResponse`; `name` property; `estimate_tokens(request) -> int` with a default heuristic (characters divided by 4 over system, messages, and tool schemas), which adapters can override.
2. `validate_request(request)`, called by every adapter before any network call. It raises `AdapterError("invalid_request")` unless: messages are not empty; the first and the last message are from the user; roles alternate; assistant messages contain only text and tool calls; user messages contain only text and tool results; every tool result answers a tool call in the immediately preceding assistant message and every tool call is answered by the next user message when one exists; tool call ids are unique; tool names are unique; the temperature is between 0 and 2; `max_output_tokens`, when given, is positive.
3. Helper to resolve defaults: `request.max_output_tokens` or the model's `max_output_tokens`.

## 5. Registry

Create `src/bugbite/adapter/registry.py`:

1. `register_adapter(provider, factory)` and `create_adapter(model_config, *, api_key=None) -> ModelAdapter`. The caller reads the environment variable named by `api_key_env` and passes the key in; adapters never read the environment themselves (same rule as the GitHub client, AD-017).
2. An unknown provider, or a provider with no adapter registered yet, raises `ConfigError` that names the provider and lists the registered ones. Registering a provider twice is an error.
3. `claude` and `openai_compatible` stay unregistered until P10 and P9 add them.

## 6. A scripted adapter for tests

Create `src/bugbite/adapter/testing.py`:

1. `ScriptedAdapter(config, script)` returns the scripted responses in order (a response, an `AdapterError` to raise, or a function of the request), records every request it receives, validates requests like a real adapter, and raises a clear error when the script runs out.
2. Builders `text_response(...)` and `tool_call_response(...)`.
3. This lets the agent loop (P16), the recorder (P22), and the replayer (P23) be built and tested without any provider.

## 7. Tests

1. Types: validation, immutability, helpers, properties, exact JSON round-trips (including unicode, empty values, tool call errors, cache flags), and rejection of malformed input.
2. `validate_request`: one test per rule above, plus valid multi-turn tool conversations.
3. `estimate_tokens`: grows with content and counts tool schemas.
4. Registry: register, create, unknown provider, unregistered provider, duplicate registration, key passed through.
5. `ScriptedAdapter`: order, errors, function steps, recorded requests, exhaustion, validation before consuming the script.
6. A reusable adapter contract test class (`tests/adapter/adapter_contract.py`) that checks any adapter returns a well-formed response, rejects invalid requests, never mutates the request, and reports usage and a normalised stop reason. It is run against `ScriptedAdapter` now; P9 and P10 run it against their adapters.
7. Config: new fields, defaults, `integration`, provider and URL validation, shipped `models.yaml`.

## 8. Docs and wrap-up

1. Add AD-045 to AD-051 to `specs/decisions.md` (written with the specs). Tick P8 in `specs/roadmap.md`.
2. README: a short section describing the adapter interface and the model config fields.
3. Commit in small logical commits, then merge into `main` with `--no-ff` when asked. Commit messages carry no co-author trailer.
