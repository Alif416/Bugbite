# Requirements: Candidate file ranking with reasons (Roadmap P26)

Branch: `2026-11-02-p26-candidate-file-ranking` (from `main` at `7dbf49a`). Covers FR3.3 (rank candidate files for the issue and show why they were chosen) and FR3.4 (keep the context sent to the model small; never dump the whole repo).

## Decisions made with the owner

1. **Signals:** text and structure only, no model call, no embeddings (those are P27), no git history. Everything is plain, deterministic code.
2. **Output:** at most 10 files (configurable), each with a score, named reasons, and the matched symbols with line ranges. The rendered text is capped at about 2 000 characters.
3. **Agent:** library only. The pre-step, prompt, tools version and golden and replay fixtures do not change; wiring comes with the runner (P45), as with P25.

## Inputs

The issue text (title and body, untrusted) and a `RepoIndex` from P25. Nothing else: no sandbox access, no network, no environment.

## Signals (each produces named reasons, each capped, so no one signal can drown the others)

1. **Traceback frames:** a frame whose path maps to a repo file (existing `parse_tracebacks` and `map_to_repo`); the innermost repo frame counts most, frames in libraries outside the repo are ignored.
2. **Named paths:** a path written in the issue that maps to a repo file.
3. **Named tests:** a test id or file mentioned in the issue; the test file counts, and so does the source file it most plausibly covers (name pairing such as `tests/test_cache.py` and `cache.py`).
4. **Named symbols:** identifiers in the issue (in backticks, dotted, `CamelCase`, `snake_case`, `name()`) that match a symbol name or qualified name in the index. A name found in few places weighs more than a common one; very short or common names are ignored.
5. **Word overlap:** lowercase words of the issue (split on `_` and camel case, stop-words removed) against path words, symbol-name words and docstring words, weighted by how rare each word is in the repo, with a small cap.
6. **Kind adjustment:** test files rank below source files unless the issue names them; files the index could not parse still rank on path signals.

## Output

`rank_files(issue_text, index, max_results=10) -> Ranking` with `candidates` (best first; ties broken by path), each having `path`, `score`, `reasons` (kind, human text, points) and `symbols` (name, qualified name, line range, why matched); plus `considered` (files looked at) and `notes` (for example "index incomplete", "no signals found"). `render_ranking(ranking, max_chars=2000)` gives the bounded text, ending with a line saying how many more were left out. Same inputs always give the same output.

## Behaviour on odd input

An empty or useless issue returns no candidates and a note, not a guess. A huge issue text is cut to a limit before use. An incomplete index adds a note. Hostile text (very long lines, regex-like or binary junk, thousands of identifiers) cannot make the ranker slow or large: work is bounded and linear in the text and index size.

## Out of scope

Embeddings and semantic search (P27), trimming context (P28), snippets of code in the result, git history, any model call, wiring into the pre-step or runner, learning weights from data.

## Constraints that still hold

No new dependencies; no network; no environment reads; no `Co-Authored-By` trailer on commits.

## Findings

- **Weights changed during the build (AD-132):** the first weights put a named test file above the source it covers, let four common words outscore the one rare word `scanner`, and missed `LRUCache` as an identifier. Each was fixed by a general rule, not a special case.
- **Fixture mistakes worth knowing:** `def lambda()` is not valid Python, so a test file silently had no symbols until the test checked it; a traceback line number that fell on a blank line named the class instead of the method. Tests now use literal weights and line numbers so such changes are visible.
- **Result on real code:** for four issues written for this repository (a replay divergence, a cost cap, the text-action parser, the symbol scanner) the known file is in the top three each time, and the traceback case puts the failing method in the symbol hits.
- **Mutation check:** 20 deliberate breakages. Eight survived the first set of tests and were closed with targeted tests (traceback floor, tie-break by path, the three-strongest-words rule, the test-file symbol discount, the 8-places rule, the minimum score, the 40 % word-share filter, symbol-hit dedupe). One of those needed a better fixture (the traceback line had to be inside the method). All 20 are now caught.
- **Dependency direction:** retrieval imports the agent's issue parser (AD-133); a later pre-step caller needs a lazy import or a move.
