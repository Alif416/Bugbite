# Plan: Replay works for both adapters (Roadmap P24)

Branch: `2026-11-02-p24-replay-both-adapters`. See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-127 onward).

## 1. Test support (`tests/replayer/adapters/`)

1. `real_adapter_helpers.py`: for each provider, a factory that builds the real adapter on `httpx.MockTransport` (Claude through the SDK's `http_client`, OpenAI-compatible through `client=`), registered under the real provider name for the duration of a test and restored afterwards. A reply script (list of canned HTTP replies, or callables) shared by both.
2. A `record_real(tmp_path, provider, replies, ...)` helper like P23's `record`: it builds the chain with `create_adapter(..., recorder=...)`, runs the loop with scripted tools, returns the result and recording path.

## 2. Tests

1. Per adapter, record then replay, each `identical`: tool call then final answer; text-only answer; rate-limit error then the loop's reaction; server error; two tool calls in one reply; a truncated (`max_tokens`/`length`) answer.
2. Claude-only: cache markers on the system block and last messages are in the fingerprint and survive replay; usage with cache read/write tokens gives the same cost on replay.
3. OpenAI-compatible-only: usage with and without a `usage` block; tool-call arguments as a JSON string; a missing tool-call id handled as the adapter does.
4. Text-action fallback on a model without native tool calling, for both providers.
5. Parity: one conversation through both adapters; both replay identically; the neutral parts (tool calls, texts, step count, outcome) are equal.
6. Goldens: `claude-golden` and `openai-golden` recordings replay identically; rebuild script `tests/replayer/adapters/make_adapter_goldens.py`; a test asks git that the fixtures are not ignored.
7. Secret check: the fake API key, and any `Authorization`/`x-api-key` header value, appear nowhere in any recording file.
8. Detection: change a Claude tool description or an OpenAI request field in the adapter's translation (simulated by editing the recorded fingerprint) and see the right divergence.
9. Mutation check: break the adapter translation (drop cache marker, change the id mapping, change usage mapping, reorder tool results) and confirm a test fails.

## 3. Docs

README sentence in "Replaying a recording" listing the adapters covered; decisions; roadmap tick; findings.

## 4. Commits (small, logical)

1. Specs. 2. Test support. 3. Tests per adapter. 4. Goldens and rebuild script. 5. Fixes found (if any). 6. Docs and ticks.
