# Plan: Embeddings search (Roadmap P27, FR3.2)

## Goal
Given a question in plain words ("where do we retry after a timeout?"), return the code chunks of a repository whose meaning is closest, with path and line range. Library only: no agent tool yet (wiring comes with the runner, P45, and the tool with a later tools-version bump).

## Decisions from the questions
- **Local embeddings (Chroma's default model, ONNX MiniLM).** Free, no key, code never leaves the machine, so private repos are safe (privacy rule intact).
- **Built per job, in a temp directory, deleted after.** No persistence, no stale data, no cache rules.
- **Chunks are symbols from the P25 index** (class, function, method), each with path and line range. Top 10 results, rendered in about 2 000 characters like P26.
- **Library only.** The agent, prompt, tools version and golden/replay fixtures stay unchanged.

## Design
- `bugbite.retrieval.semantic`:
  - `Embedder` protocol: `embed(texts) -> list[list[float]]`, plus a `name`.
  - `ChromaDefaultEmbedder`: wraps Chroma's default function; imported lazily so the package works without chromadb installed; a clear error if it is missing or the model cannot load.
  - `HashEmbedder`: deterministic, offline, test-only stand-in (hashed word features), so tests need no download.
- **Chunking** (`chunks_from_index`): for each symbol, text = qualified name + signature + docstring/first lines of the source read through the sandbox, cut to a fixed size; files with no symbols get one chunk from their head. Binary, huge and unparsed files are skipped. Caps on chunk count and chunk size, with a note when hit.
- **Reading source:** host reads file text through the sandbox in batches (the sandbox has no chroma and no network); the index is built on the host in a temp dir.
- **`SemanticIndex`:** `build(sandbox, index, embedder, limits)` -> object with `search(query, max_results=10) -> SemanticResults` and `close()` (deletes the temp dir; also a context manager). Query text is cut to a limit.
- **Results:** `SemanticHit(path, qualname, kind, line, end_line, score, preview)`; score is similarity in 0..1; stable tie-break by path then line. `render_semantic(results, max_chars=2000)` cuts only between whole lines and says how many were left out.
- **Honest:** empty query or empty index gives no hits and a note; truncated index adds a note; a model that fails to load raises a clear `RetrievalError`, never returns silent empty results.
- **Dependency:** add `chromadb` to `pyproject.toml` only after the user agrees to install it (install is a separate step; the model download is one-time and needs the network). Tests never download anything.

## Out of scope
Persistent stores, other languages, hosted embeddings, hybrid merging with the P26 ranking, the agent tool, incremental updates.

## Steps
1. Specs, then `Embedder`, `HashEmbedder`, chunking.
2. `SemanticIndex` over Chroma with temp-dir lifecycle.
3. Results, rendering, JSON round trip.
4. Tests (fake embedder; one optional test with the real model, skipped if not installed).
5. Mutation check, docs (README, AD entries, roadmap tick).
