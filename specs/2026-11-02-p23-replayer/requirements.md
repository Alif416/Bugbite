# Requirements: Replayer (Roadmap P23)

## Goal

Re-run a recorded run offline, with no API calls and no sandbox, and get the same result every time (README FR10.2, FR10.5). The current agent code is run against the model answers and tool results saved in a recording, and every request it builds is compared with the recorded request fingerprint. Replay is how the pipeline gets regression tests (FR10.3): a change to the prompt, a tool description, the loop or the limits shows up as an exact, named difference instead of a silent change. The per-adapter checks (Claude and OpenAI-compatible) are P24.

## Scope

**In:**
- `replay(path)`: load a recording, rebuild the adapter chain and settings from its manifest, run the current agent against the recorded answers, compare, and return a `ReplayResult`
- `ReplayProvider`: stands in for the provider adapter; serves the recorded responses and errors in order and checks each request's fingerprint
- `ReplayTools`: serves the recorded tool outputs in order and checks each call
- A virtual clock driven by the recorded timestamps, so time limits and measured durations replay deterministically
- A precise report of the first difference (strict): which call, which parts of the request changed, and where in the full request if the recording kept it
- After a replay that did not diverge: a comparison of everything the replayed run produced (steps, tool calls, outcome) with the recording
- `create_adapter(..., provider_adapter=...)`, used to put the replay provider in place of the real one
- A small command line, `python -m bugbite.replay <recording folder>`, with exit codes
- Rebuilding a `ModelConfig` (prices included) from a manifest

**Out (later phases):**
- Replay checks per real adapter, Claude and OpenAI-compatible (P24)
- Reproducing an old run exactly after the code changed, from stored copies of the old prompt and tool definitions (the owner chose current-code replay only)
- Continuing past a difference to list all of them
- Replaying recordings that used the retry layer until the P20 branch is merged (refused with a clear message)
- Wiring into the runner or CLI, a dashboard player, re-scoring with a verifier

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Which code | The current agent code with the recorded model answers; no snapshot mode | A regression test for the whole pipeline; no change to the recording format (AD-121) |
| On a difference | Stop at the first one and report it exactly | Everything after a difference was answered for different questions (AD-122) |
| Time | A virtual clock set from the recorded event times; the loop measures tool durations with its injected clock | Deterministic replay of time limits (FR10.5) (AD-123) |
| Where it plugs in | At the provider boundary; the whole chain above it is rebuilt from the manifest | Metering, text-action repair, the privacy guard and the loop are exercised again by every replay (AD-124) |

See `specs/decisions.md` AD-121 to AD-124.

## Behaviour

- **Input:** the folder of a recording. A complete recording is replayed; a partial one is refused unless `allow_partial=True` (then the recording running out is reported, not an error). A damaged recording raises the reader's `RecordingError` unchanged.
- **Rebuilt from the manifest:** the model config (with its prices, so the cost ledger agrees), the data sensitivity (so the privacy guard behaves as it did), the task text, the limits, the loop-detection policy. A manifest that records a retry policy is refused for now.
- **Taken from the current code:** the system prompt, the tool definitions, and the loop itself. Tests and "what if" runs can pass a different `system_prompt`, `tool_definitions` or `loop_policy`. If the recording's prompt version, system prompt hash or tools version differ from the current code, the result carries a note saying so before any call is made.
- **Chain:** text-action (only if the model has no native tool calling), metering with a fresh cost ledger, the privacy guard, a recording layer writing to memory, then the replay provider. The loop runs with the replay tools, the virtual clock and a recorder that writes to memory.
- **Provider calls:** call n gets recorded `model_call` event n: a response is returned, an error is raised as an `AdapterError` equal to the recorded one. Before it is served, the request the chain actually built is fingerprinted and compared with the recorded fingerprint.
- **Tool calls:** the loop's calls that really run are matched, in order, against the recorded `tool_call` events that really ran (`executed` true). The name and the arguments (canonical JSON) must equal the recorded ones; the recorded output is returned. Calls the loop answers itself (invalid actions, calls skipped for time) are produced by the loop and compared afterwards.
- **First difference (strict):** a request that does not match, a tool call that does not match, more provider or tool calls than were recorded, or a recorded bug in the provider adapter stops the replay at once with a `ReplayDivergence`: its kind, the call number, a sentence, and for requests the names of the fingerprint fields that differ (`sha256`, `bytes`, `messages`, `system_blocks`, `tools`, sampling settings). If the recording kept full requests, the path of the first differing value in the request (for example `messages[2].blocks[0].content`) is given too. Nothing is served after that.
- **After a replay with no difference:** the replayed events (model calls, steps, tool calls, finish) are compared with the recorded ones, leaving out the timestamps `t` and the tool durations, and unused recorded calls are reported. Any difference is listed in `ReplayResult.differences`; `identical` is true only if there are none.
- **Virtual clock:** starts at 0 when the run starts. Serving a recorded event sets the clock to that event's recorded time (never backwards). The loop's wall-clock checks, elapsed time and tool durations all use it, so a recorded `time_cap` replays as a `time_cap` and two replays of one recording are identical. Retry waits, once the retry layer exists, advance the same clock without sleeping.
- **Result:** `ReplayResult` holds `identical`, `divergence` (or None), `differences`, `notes`, the `AgentResult` (None after a divergence), and the replayed events.
- **Command line:** prints a summary (identical, or what differed and where) and exits 0 if identical, 1 if the replay differs or diverged, 2 if the recording cannot be replayed (damaged, partial without the flag, unsupported settings).
- **Determinism:** replaying one recording twice gives equal `AgentResult`s and equal event lists.

## Context

- README: FR10.2, FR10.3, FR10.5, FR14.7 (P24 completes it).
- Builds on P22 (the recording, `RecordingAdapter`, `RunRecorder`, the reader and codec), P16 to P19 (the loop and its settings), P13 (the guard), P11 (metering).
- The recorded time `t` is when the writer wrote the event, measured from when the recording started, a few milliseconds before the loop's own start; replayed elapsed times are therefore equal across replays but can differ from the recorded `elapsed_s` by that offset.

## Constraints

- Replay never touches the network, Docker, a sandbox, the environment or any key; the model config in the manifest has no key and the dummy adapter needs none.
- The replay never writes to the recording it reads.
- Replay uses only what is in the recording plus the current code; it does not fetch the issue or the repository.
- Default `uv run pytest` needs no Docker, internet or key.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Time-limit decisions that were close to a limit when recorded can differ by the few-millisecond offset above.
- Recordings made with the P20 retry layer cannot be replayed until that branch is merged and the replay chain gains the same layer.
- Tool definitions come from the current code; a recording made with a different set of tools (as in tests) needs `tool_definitions=`.
- An exact old-run mode (stored prompt and tool text) is deliberately not built.
- A recorded bug in the provider adapter (an `exception` event) cannot be replayed as a bug; it is reported as a divergence.

## Findings from the build

- **A P22 defect, found and fixed here: the golden recording was never committed.** `.gitignore` has `recordings/` (for real runs), which also matched `tests/fixtures/recordings/`, so the P22 fixture existed only on the disk it was made on. The tests passed locally, and the regeneration test would have passed anywhere, but the test that reads the committed fixture would have failed on a fresh clone. The ignore rule now has an exception for `tests/fixtures/recordings/`, a test asks git whether the fixture is ignored, and the (rebuilt) fixture is committed in this phase.
- **The golden recording changed on purpose.** It now uses a fixed system prompt (so editing the real prompt does not alter it) and has no failed first attempt: the test retry layer is not part of a replay chain, and the real retry layer is on the P20 branch. Error events are still covered by the codec, reader and recorder tests. The recording therefore has 6 events instead of 7.
- **Design points that came up while building.**
  - `ReplayDivergence` had to be a `BaseException`: the loop's `except Exception` around tool execution swallowed it (AD-125).
  - The plan had a separate "checking layer" in front of the replay provider; it turned out to be unnecessary, because the provider receives the very request the recording layer saw, so it checks the fingerprint itself.
  - The command line is the single module `bugbite/replay.py` (the plan listed a `__main__.py` inside the package, but `python -m bugbite.replay` needs a module of that name).
  - The output-token limit is read from the first recorded request (AD-126), found when a mutation check showed no test covered it.
  - A report of a difference between two long strings shows an excerpt around the first differing character; without that the system prompt's tail was cut off by the length limit and the report showed nothing useful.
  - The after-replay comparison also ignores `elapsed_s` and the "(N s used)" part of a time-cap message, because a replay's elapsed time can differ from the recorded one by the writer-to-loop start offset.
  - Recorded events are passed through JSON in the in-memory writer, so they compare as plain data (tuples and lists, for example).
- **Test-writing pitfalls.** A scripted reply reused for several steps repeats its tool call id, and the request check rejects the conversation locally, which looked like a model error; replies need distinct ids. The recording helper wrote a loop policy into the manifest without running the loop with it; it now does both.
- **Mutation check:** 29 breakages (no fingerprint check, answers out of order, tool arguments or names not compared, not-executed entries counted, the clock not advanced by model calls or by tools, the clock allowed to go backwards, the comparison afterwards skipped, unused calls ignored, the sensitivity ignored, prices not rebuilt, the long-prompt tier dropped, the first difference not stopping the replay, the divergence made an `Exception`, limits ignored, loop policy ignored, the real clock instead of the virtual one, elapsed time compared, the task taken from the code, partial recordings replayed silently, a retry policy accepted, the output-token limit not taken, a wrong exit code for a difference or an unreplayable recording, loop durations from the real clock, the provider override ignored, the path of a difference not named) are all caught. The first run missed one (the output-token limit); a test was added.
- **Merge note:** `create_adapter` is edited again (`provider_adapter`), so the P20 branch will have another small conflict there. When P20 merges, the replay chain must also build the retry layer, and the "retry policy" refusal can go.
- Full suite (foreground): 2364 passed and 156 skipped with Docker unreachable; 2514 passed and 6 skipped with Docker running; no leftover containers or volumes (the other databases on the machine were not touched); no new dependencies.

