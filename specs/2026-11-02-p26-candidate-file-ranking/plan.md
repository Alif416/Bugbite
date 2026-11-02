# Plan: Candidate file ranking with reasons (Roadmap P26)

Branch: `2026-11-02-p26-candidate-file-ranking`. See `requirements.md` and `validation.md`. Decisions: `specs/decisions.md` (AD-131 onward).

## 1. Code (`src/bugbite/retrieval/`)

1. `ranking_types.py`: frozen `Reason(kind, text, points)`, `SymbolHit(name, qualname, line, end_line, why)`, `Candidate(path, score, reasons, symbols)`, `Ranking(candidates, considered, notes)`; JSON round trip.
2. `words.py`: `split_words(text)` (snake, camel, digits, lowercase), a small English plus programming stop-word list, `identifiers(text)` that finds backticked, dotted, CamelCase, snake_case and call-style names with a length and count cap.
3. `signals.py`: one function per signal, each returning `{path: [Reason, ...]}` with its own cap: traceback, paths, tests, symbols, words. Weights are named constants at the top of the file, each with a one-line reason.
4. `ranker.py`: `rank_files(issue_text, index, *, max_results=10, max_chars_in=30_000)` builds a `TrackedIndex` from the index's files (reusing `map_to_repo`), runs the signals, adds the kind adjustment, sorts by (-score, path), cuts to `max_results`, and attaches symbol hits and notes.
5. `render.py`: `render_ranking(ranking, max_chars=2000)`.
6. Exports in `__init__.py`.

## 2. Tests

1. Each signal alone on a small built repo: traceback innermost frame first, library frames ignored, named path, named test and its source pairing, symbol names (backtick, dotted, camel, snake, call), rare beats common, word overlap with rarity, stop-words and short names ignored.
2. Whole ranking: the right file first for a set of realistic issues written for a small fixture repo (6 cases); ties by path; same result every time and regardless of dict or file order; `max_results` honoured; test files below source files unless named.
3. Reasons: every candidate has at least one reason, points add up to the score, texts are readable and mention the evidence (frame number, symbol, line range).
4. Odd input: empty, whitespace, only stop-words, binary junk, 1 MB of text, 5 000 identifiers, a path with `..`, an index with parse errors or truncated; each is bounded and gives notes not crashes; time-bounded test on a large synthetic index.
5. Render: stays under `max_chars`, says what was left out, never cuts mid-line.
6. Real code: rank this repository for 4 real-looking issues (written for known past bugs, e.g. a replay divergence, a cost cap) and require the known file in the top 3.
7. No model, network or environment use (source scan like earlier phases); no new dependencies; JSON round trip.
8. Mutation check: traceback order reversed, library frames counted, rarity ignored, stop-words kept, test-file penalty removed, cap removed on one signal, tie-break removed, notes dropped, max_results ignored.

## 3. Docs

README section "Ranking candidate files"; decisions AD-131 onward (weights and caps, why plain code, why library only); roadmap tick; findings.

## 4. Commits (small, logical)

1. Specs. 2. Types and words. 3. Signals. 4. Ranker and render. 5. Tests. 6. Docs and ticks.
