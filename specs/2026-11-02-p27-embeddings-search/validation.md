# Validation: Embeddings search (Roadmap P27)

The work can be merged when every item below is true.

## Automated (no Docker needed for most, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable (foreground) and with Docker running; no leftovers. (2708 passed, 157 skipped; with Docker 2859 passed, 6 skipped; no leftover containers, volumes or `bugbite-semantic-*` temp folders.)
- [x] **Chunking:** one chunk per symbol with path and line range; symbol-less files get a head chunk; binary, huge and unparsed files skipped; caps respected with a note.
- [x] **Search:** with the fake embedder, the expected chunk is first for realistic queries on a fixture repo.
- [x] **Small:** at most `max_results` hits; rendered text never exceeds `max_chars`, never cuts mid-line, says how many were left out.
- [x] **Deterministic:** same input, same output; ties break by path and line.
- [x] **Honest:** empty query or empty index gives no hits and a note; truncated index adds a note; a failing or missing embedder raises a clear error.
- [x] **Clean up:** the temp directory is gone after `close()`, after an error, and when used as a context manager.
- [x] **Hostile input:** huge query, huge files, odd paths and thousands of symbols stay bounded.
- [x] **No network or environment reads** in the module (source scan); chromadb imported lazily.
- [x] **Real model test** runs when chromadb and the model are present (skipped otherwise) and finds the right chunk for a plain-words query.
- [x] **Mutation check (24 breakages, all caught after six tests were added):** each listed breakage fails at least one test.

## Manual

- [x] README "Semantic search" section; AD entries; roadmap P27 ticked; no `Co-Authored-By`.
- [x] User approved installing `chromadb` and the model download; `pyproject.toml` gained only `chromadb>=1.5.9` and `uv.lock` the resolved tree.

## Findings

- Real model on the toy repository: "seconds to wait before the next attempt" gives `backoff_delay` first (0.55); "load settings from a yaml file" gives `ConfigParser.load` (0.78); "remove the oldest item" gives `Cache.evict` (0.64). The vaguer "how long to wait before trying again" put `retry_after_timeout` (0.49) above `backoff_delay` (0.42): right file, not the best function. The real-model test asserts exactly this, rather than a stronger claim.
- Unrelated chunks score near 0 (0.04), related ones 0.3 to 0.8 on this toy; a score threshold would be guesswork, so only scores at or below 0 are dropped.
- Six mutation survivors led to tests for: the query being cut before embedding, over-fetching from the store so ties break the same way, test files ranked last even when they sort first, ragged vectors checked on their own, an embedder's own `RetrievalError` passing through unchanged, and Chroma telemetry being off.
- Model download: 79 MB, about 20 seconds; `~/.cache/chroma` is 167 MB afterwards.
