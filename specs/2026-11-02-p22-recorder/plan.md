# Plan: Recorder (Roadmap P22)

Branch: `2026-11-02-p22-recorder` (from `main`; the P20 branch is on hold). See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-117 onward).

## 1. Codec (`src/bugbite/recorder/codec.py`)

1. Block, message, response and error converters to and from plain dicts (`block_to_dict`, `block_from_dict`, `response_to_dict`, `response_from_dict`, `error_to_dict`, `error_from_dict`), strict about unknown keys and types.
2. `request_to_dict(request)` (full) and `request_fingerprint(request) -> dict` (canonical JSON, SHA-256, byte size, counts). Canonical form: `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

## 2. Writer (`src/bugbite/recorder/writer.py`)

`RunWriter(root, manifest, *, record_requests=False, scrub=identity, clock, monotonic, max_bytes=200 MB)`:
1. Creates `<root>/<run_id>` (0700; refuses an existing folder) and writes the manifest atomically with `status: "recording"`.
2. `write(event: dict)` assigns `seq` and `t`, scrubs, serialises, appends one line, flushes; thread-safe; failures counted, never raised; the size cap stops further writing and marks the recording incomplete.
3. `finish(outcome)` closes the events file, hashes it, and replaces the manifest atomically with `status: "complete"`, outcome, counts, hash and size. `abort(reason)` does the same with `status: "incomplete"`.
4. Files 0600, folder 0700; `errors` and `last_error` (kind only).

## 3. Recording adapter and observer (`recorder/adapter.py`, `recorder/observer.py`)

1. `RecordingAdapter(inner, writer)`: records each call as a `model_call` event (fingerprint; response, error or exception) and returns/raises the original.
2. `RunRecorder(writer)`: the loop observer. It keeps the count of provider calls already assigned and writes `step`, `tool_call` and `finish` events, then finishes the writer.
3. `create_adapter(..., recorder=None)`: `PrivacyGuardAdapter(RecordingAdapter(factory(...), recorder), sensitivity)` when a recorder is given.

## 4. Start helper and commit facts (`recorder/start.py`)

`start_recording(root, info, *, scrub, record_requests, commit_info=bugbite_commit_info) -> Recording` with `.writer`, `.observer`, `.path`, `.close()` and `.abort(reason)`. `bugbite_commit_info()` runs `git rev-parse HEAD` and `git status --porcelain` in the package's directory with a short timeout, returning `(None, None)` when it is not a git checkout or git is missing.

## 5. Reader (`recorder/reader.py`)

`load_recording(path) -> LoadedRecording` with `manifest`, `events`, `complete`, `warnings`, and helpers `model_calls()` (decoded request fingerprint, response or error), `tool_calls()`, `steps()`. Raises `RecordingError` for damage as described.

## 6. Tests

1. Codec: seeded random round trips for every block and stop reason, usage with cache tokens, errors with retry-after and status, fingerprint stability and sensitivity (each field changed separately), canonical form independent of key order.
2. Writer: layout, permissions, no overwrite, seq contiguity, atomic manifest (no half-written file visible), scrubbing in events and manifest, 8 threads writing, size cap, unwritable folder (errors counted), abort, a crash (no finish) loads as partial, a torn last line is ignored.
3. Adapter: same object returned, same error raised, exception recorded by type only, fingerprint equals an independent computation, full requests only on demand, a failing writer never breaks a call, the guard stays outside (a refused call leaves no event).
4. Integration: `run_agent` with a scripted raw adapter in the real chain (guard, recording, metering, test-only retry layer, text-action) and a loop observer: the recording holds exactly the raw calls (including failed attempts and repairs), every tool call and the outcome, and matches the `AgentResult`.
5. Manifest: every field from `requirements.md`; commit and dirty flag against a real temporary git repository; null outside git; no key anywhere.
6. Reader: each kind of damage (bad version, missing manifest, gap, unknown type, tampered events, counts mismatch) raises with the file named; partial recordings load with warnings.
7. A small golden recording committed under `tests/fixtures/recordings/golden-v1/`, generated with fixed clocks: the loader reads it and the hash matches, so an accidental format change fails a test.
8. Mutation check: seq gap, request fingerprint ignoring a field, response field dropped, the error not re-raised, secret not scrubbed, manifest not atomic, wrong permissions, the guard order (recording outside the guard), the hash not checked, the torn line not tolerated, calls assigned to the wrong step, an exception swallowed.

## 7. Docs

README section "Recording a run"; roadmap P22 ticked; `.gitignore` gets `recordings/`; findings; validation ticked; AD-117 to AD-120.
