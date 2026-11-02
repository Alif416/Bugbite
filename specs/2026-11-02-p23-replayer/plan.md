# Plan: Replayer (Roadmap P23)

Branch: `2026-11-02-p23-replayer` (from `main`; the P20 branch is on hold). See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-121 onward).

## 1. Small changes to existing code

1. `create_adapter(..., provider_adapter=None)`: when given, it is used instead of `factory(model, api_key)` and the API-key check is skipped (the recording layer, if requested, still goes directly above it, then the guard).
2. The agent loop measures tool durations with its injected `clock` instead of `time.monotonic()`; all callers that did not inject a clock behave as before (the default clock is `time.monotonic`).
3. The golden recording is rebuilt with a fixed system prompt (so it does not change when the real prompt does) and the new duration source; its test values are updated.

## 2. Replay pieces (`src/bugbite/replayer/`)

1. `clock.py`: `ReplayClock` (`now()`, `advance_to(t)` never backwards, `sleep(seconds)`).
2. `errors.py`: `ReplayError` (cannot be replayed) and `ReplayDivergence` (carries `kind`, `call`, `message`, `fields`, `path`).
3. `model.py`: `model_from_manifest(manifest["model"]) -> ModelConfig`, including `Pricing` with a long-prompt tier, by hand; exact for the shipped models.
4. `diff.py`: `fingerprint_differences(recorded, replayed)` and `first_difference(a, b)` (a path like `messages[2].blocks[0].content`).
5. `provider.py`: `ReplayProvider(model, recorded_calls, clock)`; the check is done by a thin checking layer between the recording layer and the provider, because the fingerprint has to be computed from the request as it arrives.
6. `tools.py`: `ReplayTools(definitions, recorded_tool_calls, clock)` with `definitions()` and `execute(name, arguments, *, time_limit_s=None)`.
7. `memory.py`: `MemoryWriter`, an in-memory stand-in for `RunWriter` (same sink interface; keeps events, no `t`-dependent files).
8. `replay.py`: `replay(path, *, allow_partial=False, system_prompt=None, tool_definitions=None, loop_policy=<recorded>) -> ReplayResult`, `compare_events(recorded, replayed)`, `ReplayResult`.
9. `__main__.py`: `python -m bugbite.replay <folder> [--allow-partial] [--json]`.

## 3. Tests

1. Clock: monotonic, `advance_to`, `sleep`.
2. `model_from_manifest`: equality with the original for the shipped `models.yaml` entries (including Haiku's long-prompt tier), and for a hand-made config; bad manifests are refused.
3. Diff helpers: each fingerprint field, nested paths in messages, tools and system.
4. Provider: order, responses, errors equal to recorded, fingerprint match and each kind of mismatch, exhaustion, a recorded bug, clock set from events.
5. Tools: order and matching, skipping not-executed entries, argument order irrelevant, mismatch, exhaustion, leftover.
6. End to end, recorded then replayed: a finished run with tools; a model-error ending; a text-action repair; a loop-detection nudge and stop; a privacy refusal; `max_steps`; a cost cap; a time cap with a stepped clock; a run with a failed first attempt (no retry layer: the error reaches the loop); an empty-patch style immediate answer. Each gives `identical` true.
7. Determinism: two replays of each give equal results and equal event lists; the recording folder is unchanged (hashes before and after).
8. Difference detection: a different system prompt, a changed tool description, a changed schema, a changed loop policy, a changed task, a changed limit, and a model result that no longer fits, each stop with the right kind and fields; with a full-request recording the path is named; unused recorded calls are reported.
9. Partial and damaged recordings; a retry policy in the manifest is refused.
10. The golden recording replays identically with its fixed prompt and the test tool set.
11. The command line: output and the three exit codes.
12. No network or environment access in the new code; the replay never writes in the recording folder.
13. Mutation check: no fingerprint check, a response served out of order, tool arguments not compared, not-executed entries counted, clock not advanced, clock allowed to go backwards, the comparison afterwards skipped, the recording modified, the privacy sensitivity ignored, prices not rebuilt, the first difference not stopping the replay, the exit codes.

## 4. Docs

README section "Replaying a recording"; roadmap P23 ticked; findings; validation ticked; AD-121 to AD-124.
