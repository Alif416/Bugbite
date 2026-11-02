# Validation: Embeddings search (Roadmap P27)

The work can be merged when every item below is true.

## Automated (no Docker needed for most, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable (foreground) and with Docker running; no leftovers.
- [ ] **Chunking:** one chunk per symbol with path and line range; symbol-less files get a head chunk; binary, huge and unparsed files skipped; caps respected with a note.
- [ ] **Search:** with the fake embedder, the expected chunk is first for realistic queries on a fixture repo.
- [ ] **Small:** at most `max_results` hits; rendered text never exceeds `max_chars`, never cuts mid-line, says how many were left out.
- [ ] **Deterministic:** same input, same output; ties break by path and line.
- [ ] **Honest:** empty query or empty index gives no hits and a note; truncated index adds a note; a failing or missing embedder raises a clear error.
- [ ] **Clean up:** the temp directory is gone after `close()`, after an error, and when used as a context manager.
- [ ] **Hostile input:** huge query, huge files, odd paths and thousands of symbols stay bounded.
- [ ] **No network or environment reads** in the module (source scan); chromadb imported lazily.
- [ ] **Real model test** runs when chromadb and the model are present (skipped otherwise) and finds the right chunk for a plain-words query.
- [ ] **Mutation check:** each listed breakage fails at least one test.

## Manual

- [ ] README "Semantic search" section; AD entries; roadmap P27 ticked; no `Co-Authored-By`.
- [ ] User approved installing `chromadb`, and `pyproject.toml` and `uv.lock` show only that change.
