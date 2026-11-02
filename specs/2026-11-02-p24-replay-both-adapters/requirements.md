# Requirements: Replay works for both adapters (Roadmap P24)

Branch: `2026-11-02-p24-replay-both-adapters` (from `main` at `8f27d27`). Covers FR14.7: record and replay (FR10) works for every adapter.

## Why this phase exists

The recorder (P22) and replayer (P23) work on Bugbite's neutral request and response types, so in principle they do not care which provider produced the answers. P23 proved that only with a scripted test adapter. Nothing yet shows that a run made through the **real** Claude adapter or the **real** OpenAI-compatible adapter (their translation code, usage fields, tool-call ids, cache markers and error mapping) records and replays identically. P24 proves it, and keeps that proof from rotting.

## Decisions made with the owner

1. **Proof method:** run the real `ClaudeAdapter` and `OpenAICompatibleAdapter` against canned provider HTTP replies (mock transport), record the run, replay it. No network, no keys, no cost.
2. **Coverage:** native tool calls, text-only answers, provider errors (rate limit, server error), Claude cache markers, OpenAI-style usage fields, and the text-action fallback on a model without native tool calling.
3. **Golden recordings:** one small tracked recording per adapter, replayed by a test that expects `identical`.

## In scope

- Test support that builds a real adapter on a mock transport and plugs it into the same recording chain `create_adapter` builds.
- End-to-end record-then-replay tests for both adapters over the coverage list above.
- Two golden recordings under `tests/fixtures/recordings/`, with a script that rebuilds them.
- A parity test: the same scripted conversation through both adapters gives recordings that replay identically and differ only in provider-specific fields (model name, usage, ids).
- Fixes to any adapter, recorder or replayer defect the new tests expose.
- README note and decisions for anything chosen along the way.

## Out of scope

- Live runs against real providers (the existing opt-in live tests remain).
- Wiring record/replay into the runner or CLI (P45), the retry layer (P20, on hold).
- New adapters.

## Constraints that still hold

- No network, no environment reads, no Docker needed for the new tests; no new dependencies.
- Secrets only in env vars; the fake key used in tests must not appear in any recording.
- No `Co-Authored-By` trailer on commits.

## Findings

(Filled in during the build.)
