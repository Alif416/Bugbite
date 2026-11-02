# Validation: Replayer (Roadmap P23)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable (run in the foreground): only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [ ] **Identical replays:** recording and then replaying each of these scripted runs gives `identical` true, no divergence and no differences: a finished run with tool calls; a model-error ending; a text-action repair; a loop-detection nudge and stop; a privacy refusal; a `max_steps` ending; a cost cap ending; a time cap ending; a run whose first provider call fails.
- [ ] **Determinism:** replaying one recording twice gives equal `AgentResult`s and equal event lists, and the recording folder (every file's hash) is unchanged afterwards.
- [ ] **No outside access:** a replay opens no socket, starts no process and reads no environment variable (asserted with the test suite's network and subprocess guards), needs no Docker, and needs no key even for a model that normally requires one.
- [ ] **Virtual clock:** a recorded `time_cap` replays as `time_cap`; the clock never goes backwards; elapsed time and tool durations come from the recorded timestamps; replays of one recording agree exactly.
- [ ] **Model config:** `model_from_manifest` gives a `ModelConfig` equal to the original for every entry of the shipped `config/models.yaml` (Haiku's long-prompt tier included) and the cost reported by a replay equals the recorded cost exactly.
- [ ] **Sensitivity:** a recording made for private data and a model that may not see it replays as `privacy_blocked` with no provider call served.
- [ ] **Strict divergence:** each of these stops at the first difference with the right kind, call number and fields, and serves nothing afterwards: a changed system prompt, a changed tool description, a changed tool schema, a changed task, a different loop policy that changes a request, more provider calls than recorded, a tool call with a different name, a tool call with different arguments, more tool calls than recorded, a recorded bug in the provider adapter.
- [ ] **Where the difference is:** with a full-request recording the report names the path of the first differing value; without one it names the differing fingerprint fields.
- [ ] **After a clean replay:** a difference in the steps, tool calls or finish event (for example a changed nudge text) is listed in `differences`, `identical` is false, and unused recorded calls are reported.
- [ ] **Version notes:** a changed prompt version, system prompt hash or tools version is reported as a note before the first call.
- [ ] **Partial and damaged recordings:** a partial recording is refused without `allow_partial` and, with it, replays up to its end and reports that it ended; a damaged recording raises `RecordingError`; a manifest with a retry policy is refused with a clear message.
- [ ] **Golden recording:** the committed golden recording replays identically with its fixed system prompt and test tool set.
- [ ] **Command line:** prints a readable summary; exit code 0 for identical, 1 for a difference or divergence, 2 for a recording that cannot be replayed; `--json` prints the same facts as data.
- [ ] **create_adapter:** `provider_adapter=` replaces the provider and skips the key check; the order of the other layers is unchanged; without it nothing changes.
- [ ] **Loop timing:** tool durations in events now come from the injected clock; runs that inject no clock still work as before.
- [ ] **No model names or environment reads** in the new code (the earlier scans still pass).
- [ ] **Mutation check:** each of these breakages makes at least one test fail: no fingerprint check, responses served out of order, tool arguments not compared, not-executed entries counted as tool calls, the clock not advanced, the clock allowed to go backwards, the after-replay comparison skipped, the recording modified, the sensitivity ignored, prices not rebuilt, the first difference not stopping the replay, wrong exit codes.

## Manual checks

- [ ] Read the report of a divergence caused by a changed tool description: does it tell you what changed and where, in plain words?
- [ ] `git grep -nE "os.environ|getenv|socket|subprocess" src/bugbite/replayer` returns nothing.
- [ ] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [ ] `specs/decisions.md` has AD-121 to AD-124 with reasons.
- [ ] `specs/roadmap.md` has P23 ticked.
- [ ] README explains how to replay, what it compares, what a difference means, and what is not covered.
- [ ] Commits are small and logical on branch `2026-11-02-p23-replayer`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no per-adapter replay, no runner wiring, no recorder format change).

## Definition of done

All boxes ticked, tests green locally (run in the foreground) with Docker both running and unreachable, and the branch ready for review and merge into `main`.
