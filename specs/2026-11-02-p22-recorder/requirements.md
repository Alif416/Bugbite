# Requirements: Recorder (Roadmap P22)

## Goal

Write every run to disk in a structured, readable, verifiable format: each model response, tool call and tool result (README FR10.1), together with the facts that make a recording traceable: the model, prompt version, configuration and Bugbite commit (FR10.4). It is the input of the replayer (P23, FR10.2 and FR10.5), which re-runs a recorded run with no API calls, and of replay for both adapters (P24, FR14.7). This phase records and reads recordings; replaying is the next phase.

## Scope

**In:**
- The recording format: a folder per run with `manifest.json` and an append-only `events.jsonl`
- A codec between the neutral model types (requests, responses, blocks, adapter errors) and JSON, exact in both directions
- `RunWriter`: creates the folder, writes events as they happen, finishes the manifest atomically with counts and a hash of the events file
- `RecordingAdapter`: wraps the raw provider adapter and records every call, response or error
- `RunRecorder`: an agent-loop observer that records steps, tool calls and results, and the outcome
- `start_recording(...)`: one helper that builds the manifest facts (model config, prompt and tools versions, limits, loop and retry settings, task, Bugbite commit and whether it is dirty, platform)
- `create_adapter(..., recorder=...)`: puts the recording layer directly above the provider adapter
- `load_recording(path)`: reads and validates a recording, complete or partial
- Request fingerprints always; full requests only on demand
- Scrubbing of secrets, owner-only file permissions, and failure isolation (a recording problem never affects a run)

**Out (later phases):**
- Replaying a recording (P23), the per-adapter replay checks (P24), a virtual clock for replay
- Wiring into the single-job runner (`bugbite.local_run`, on hold with P20) and the CLI (P45)
- Importing recordings into the trace store (P21), compression, encryption, retention, a recordings browser

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Layout | A folder per run: `manifest.json` plus append-only `events.jsonl`; manifest finished atomically; owner-only permissions | A crashed run leaves a readable partial recording; files are plain text, diffable and usable as test fixtures (AD-117) |
| Where model calls are recorded | At the raw provider boundary, inside the privacy guard and below metering, retries and the text-action wrapper | Replay can swap the provider adapter and re-run the whole stack above it, for any adapter (AD-118) |
| Requests | A fingerprint (SHA-256, size, counts) of every request; full requests only with a flag | The fingerprint is enough for replay to detect changed behaviour; full requests grow with the square of the run length (AD-119) |
| Safety | A recording problem is counted and never raised; full content for every job with its sensitivity in the manifest; secrets scrubbed | Same reasoning as the trace store (AD-120) |

See `specs/decisions.md` AD-117 to AD-120.

## The format (version 1)

A recording is the folder `<root>/<run_id>/`, `run_id` being a sortable UTC timestamp plus 8 random hex digits. The folder is created with mode 0700 and refuses to exist already; files are 0600.

**`manifest.json`**, written when the run starts with `status: "recording"` and replaced atomically (temporary file, then rename) when it ends:
- `format` (`"bugbite-recording"`), `format_version` (1), `run_id`, `created_at`, `finished_at`
- `status`: `recording` (not finished: the process died or has not ended yet), `complete`, or `incomplete` (aborted, with `reason`)
- `bugbite`: `commit` (full hash or null), `dirty` (true if the working tree had uncommitted changes, null if unknown), `version`, `python`, `platform`
- `model`: name, provider, base URL, model name, context window, native tool calling, output limit, prompt caching mode, pricing (money as text), per-issue cap, `allow_private_code`. Never a key.
- `prompt`: `version` (the system prompt version), `system_prompt_sha256`, `tools_version`
- `task`: `text` and `sha256`
- `source`: `issue_url`, `repo`, `ref`, `sensitivity`
- `settings`: limits (steps, cost, wall clock, margin), the loop-detection policy, the retry policy, `record_requests`
- at the end: `outcome` (the agent's status, error code and message, limit detail, steps, nudges, usage, cost, elapsed seconds), `counts` (events, model calls, tool calls), and `events_sha256` and `events_bytes` of the finished events file

**`events.jsonl`**: one JSON object per line, each with `seq` (1, 2, 3 ...), `type` and `t` (seconds since the recording started, monotonic). Types:
- `model_call`: `call` (1-based number of the provider call), `request` (the fingerprint: `sha256`, `bytes`, `messages`, `system_blocks`, `tools`, `max_output_tokens`, `temperature`, `stop_sequences`; plus `full` when full requests are on), and either `response` (every field of `GenerationResponse`) or `error` (code, message, retry-after, HTTP status) or `exception` (the type name only, for a bug)
- `step`: `step` (the loop's step number), `model_calls` (the provider call numbers that belong to it)
- `tool_call`: `step`, `position`, the call (`id`, `name`, `arguments`), the output (`text`, `is_error`), `executed`, `duration_s`
- `finish`: the outcome, and each step's nudge text

## Behaviour

- **Exactness:** a response or an error decoded from a recording equals the original (every field, including usage, latency, request id and the raw stop reason), checked with seeded random inputs.
- **Fingerprints:** the SHA-256 is of a canonical JSON form (sorted keys, no extra spaces) of the full request, so it does not depend on dict order and changes if anything the model would see changes: a message, a tool definition or its schema, the system prompt, temperature, output limit or stop sequences.
- **Adapter:** `RecordingAdapter` returns the very same response object, re-raises the very same error, and writes the event before returning. A bug in the provider adapter (any other exception) is recorded by type name and re-raised.
- **Loading:** `load_recording` checks the format and version, that sequence numbers run 1 to n without gaps, that every event type and its fields are known, and, for a complete recording, that the events file matches the manifest's hash and counts. A partial recording (status `recording` or `incomplete`) loads and says so; a last line cut off by a crash is ignored and reported. Any other damage raises `RecordingError` naming the file and the problem.
- **Failure isolation:** a write that fails (disk full, permissions) is counted in `writer.errors` and never raised; recording continues if it can, and the manifest says `incomplete` with the reason. A size cap (200 MB for the events file) stops recording the same way.
- **Scrubbing:** a caller-supplied function is applied to every string in every event and in the manifest before it is written.
- **Traceability:** the Bugbite commit comes from `git` in the directory of the Bugbite code; when that is not a git checkout the commit is null (never a made-up value).

## Context

- README: FR10.1 to FR10.5, FR14.7 (replay for every adapter), FR8.1 (the trace store is the queryable twin of this file record).
- Builds on P8 (neutral types), P11 (metering), P12, P13 (the privacy guard stays outside the recording layer, so a refused call is never recorded because it is never sent), P16 to P19 (events, versions, limits), P21 (same policy for private content).
- Replay needs, in order: the provider responses and errors, the tool outputs by call, the task and the system prompt; and fingerprints to notice divergence. All of it is in the format.

## Constraints

- Nothing is recorded below the provider adapter's neutral types: no HTTP bodies, no headers, no keys.
- The recording layer sits inside the privacy guard (a call the guard refuses is not a provider call) and outside nothing else.
- Default `uv run pytest` needs no Docker, internet or key.
- Recordings of private jobs contain private code on local disk, readable only by the owner; the sensitivity is in the manifest.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Nothing enforces who may read a recording beyond file permissions; export or sharing must check `sensitivity`.
- Time-dependent behaviour (wall-clock caps, retry waits) depends on a clock; recordings keep the timings (`t`, latencies, durations) so P23 can drive a virtual clock, but P22 does not.
- `events.jsonl` is flushed per event but not fsynced; a power cut can lose the last events (a process crash cannot).
- Full requests, when enabled, can make a recording several megabytes.
- The format is version 1; any change to it needs a new version and a migration note.
