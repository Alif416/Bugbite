# Validation: Model Adapter Interface and Model Config (Roadmap P8)

The work can be merged when every item below is true.

## Automated (no Docker, no network)

- [ ] `uv run pytest` passes with Docker unreachable and no network: only Docker and internet tests are skipped, none fail, and all earlier tests still pass.
- [ ] Types: blocks, messages, tool definitions, requests, usage, and responses reject invalid values (empty tool name, bad characters in names, unknown role, non-dict schema, negative token counts, unknown stop reason); all are immutable.
- [ ] JSON round-trip is exact for requests and responses, including unicode, empty strings and tuples, cache flags, tool calls with nested arguments, tool calls with an `error`, and tool results flagged as errors.
- [ ] `from_dict` rejects unknown block types, missing fields, wrong types, and an unknown `schema_version`, each with a clear error naming the problem.
- [ ] `GenerationResponse.text` joins text blocks in order; `tool_calls` lists tool calls in order; `Usage.total` adds input and output tokens.
- [ ] `validate_request` has a test for each rule: empty messages; first message not from the user; roles not alternating; tool call in a user message; tool result in an assistant message; tool result with no matching call; tool call never answered when a next user message exists; duplicate tool call ids; duplicate tool names; temperature below 0 and above 2; non-positive `max_output_tokens`; and passes for valid multi-turn tool conversations.
- [ ] `estimate_tokens` grows with message length and counts tool schemas.
- [ ] Registry: register and create; unknown provider and not-yet-registered provider raise `ConfigError` naming the provider and listing registered ones; duplicate registration raises; the key passed to `create_adapter` reaches the factory; nothing is read from the environment.
- [ ] `ScriptedAdapter`: returns responses in order, raises scripted errors, supports function steps, records requests, validates a request before consuming the script, and raises a clear error when the script runs out.
- [ ] The adapter contract tests pass for `ScriptedAdapter`: well-formed response, invalid requests rejected as `invalid_request`, the request object is not mutated, usage and normalised stop reason present.
- [ ] `ModelConfig` loads the new fields and defaults; `integration` is `native` or `text_action`; unknown provider, non-http base URL, non-positive `context_window` or `max_output_tokens`, `max_output_tokens` not smaller than `context_window`, and a malformed `api_key_env` all raise `ConfigError` naming the field; the shipped `config/models.yaml` loads and Haiku names `ANTHROPIC_API_KEY`.
- [ ] `AdapterError` codes are stable, validated, and carry `retry_after_s` and `status_code`; covered in `tests/test_errors.py`.

## Manual checks

- [ ] `git grep -nE "anthropic|openai|haiku|ollama" src/bugbite/adapter` returns nothing (no provider or model names in the interface code).
- [ ] `git grep -n "os.environ\|getenv" src/bugbite/adapter` returns nothing.
- [ ] No new dependencies in `pyproject.toml` or `uv.lock`.
- [ ] Error messages for invalid requests read clearly to a non-developer (spot check several).
- [ ] The README section matches the code (read once).

## Docs and process

- [ ] `specs/decisions.md` has AD-045 to AD-051 with reasons.
- [ ] `specs/roadmap.md` has P8 ticked.
- [ ] Commits are small and logical on branch `2026-11-01-p08-model-adapter-interface`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no real adapters, cost tracking, recorder, or agent code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch is ready for review and merge into `main`.
