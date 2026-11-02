# Requirements: Embeddings search (P27)

- FR3.2: semantic search over a repository by meaning.
- Local only: no code sent to any service; no API key; works for private repos.
- Temp storage only: nothing persists after `close()`, including after errors.
- Bounded: max chunks, max chunk characters, max query characters, max results; hostile input stays small and fast.
- Deterministic with a deterministic embedder; ties break by path and line.
- Strict: damaged results or a failing embedder produce a `RetrievalError`, not silent empty output.
- No secrets read from the environment; no network at import or in tests.
- Dependency added only with the user's approval; the library imports it lazily.
- Agent, prompt, tools version, golden and replay fixtures unchanged.
- Decisions logged as AD entries; no `Co-Authored-By` trailers.
