# Validation: Recorder (Roadmap P22)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable (run in the foreground): only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [ ] **Codec exactness:** for thousands of seeded random responses (text, tool-call and tool-result blocks, every stop reason, usage with cache tokens, estimated usage, request ids, latency) and every `AdapterError` shape (retry-after, status code), decoding what was encoded gives an equal object; unknown keys or types in the data are rejected.
- [ ] **Fingerprints:** the same request gives the same fingerprint, independent of dict order; changing any one of a message, a block, a tool name, a tool description, a tool schema, the system prompt, temperature, output limit or stop sequences changes it; size and counts are right.
- [ ] **Writer:** the folder is created 0700 and its files 0600; an existing folder is refused; `seq` runs 1 to n with no gaps even with 8 threads writing; the manifest is replaced atomically (a reader never sees a half-written one); `finish` records counts, the events hash and size; `abort` gives `incomplete` with the reason.
- [ ] **Scrubbing:** with a sentinel secret in the task, a model reply, a tool argument, a tool output, an error message and the configuration, no byte of the recording contains it.
- [ ] **Failure isolation:** an unwritable folder or a full disk is counted in `writer.errors`, raises nothing, and `run_agent` returns the same result as without a recorder; the size cap stops recording cleanly and marks it incomplete.
- [ ] **RecordingAdapter:** returns the very same response object, re-raises the very same error, records any other exception by type name only and re-raises it, and a failing writer never breaks the call.
- [ ] **Position in the chain:** `create_adapter(..., recorder=...)` builds guard, recording, raw provider adapter from the outside in; a call the privacy guard refuses leaves no event; metering, retry and text-action layers sit above the guard.
- [ ] **Integration:** a scripted run through the real chain leaves exactly the raw provider calls (failed and retried attempts and text-action repairs included) as `model_call` events, each tool call as a `tool_call` event, the steps with the right call numbers, and a `finish` that matches the `AgentResult` (status, usage, cost, nudges).
- [ ] **Manifest:** every field in `requirements.md` is present and correct; the model section holds no key; the commit and dirty flag are right against a real temporary git repository and null outside one.
- [ ] **Reader:** a bad format or version, a missing manifest or events file, a gap in `seq`, an unknown event type or field, a tampered events file (hash mismatch) and a counts mismatch each raise `RecordingError` naming the file; a partial recording loads with `complete` false and warnings; a torn last line is ignored and reported.
- [ ] **Golden recording:** the committed `golden-v1` recording loads, its hash matches the manifest, and its decoded contents equal the expected values written in the test, so a change to the format fails a test.
- [ ] **No model names, no environment reads, no network** in the new code (the earlier scans still pass).
- [ ] **Mutation check:** each of these breakages makes at least one test fail: a gap in `seq`, a fingerprint that ignores a field, a response field dropped, an error not re-raised, a secret not scrubbed, a non-atomic manifest, wrong permissions, recording placed outside the guard, the events hash not checked, a torn last line not tolerated, calls assigned to the wrong step, an exception swallowed.

## Manual checks

- [ ] Open a real recording of a scripted run in an editor: can you read how the run went, event by event, without any tool?
- [ ] `git grep -nE "os.environ|getenv" src/bugbite/recorder` returns nothing.
- [ ] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [ ] `specs/decisions.md` has AD-117 to AD-120 with reasons.
- [ ] `specs/roadmap.md` has P22 ticked.
- [ ] README explains the format, how to record a run, where recordings go and what is not covered yet.
- [ ] Commits are small and logical on branch `2026-11-02-p22-recorder`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no replayer, no runner wiring, no trace store changes).

## Definition of done

All boxes ticked, tests green locally (run in the foreground) with Docker both running and unreachable, and the branch ready for review and merge into `main`.
