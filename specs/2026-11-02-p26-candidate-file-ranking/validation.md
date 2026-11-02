# Validation: Candidate file ranking with reasons (Roadmap P26)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable (foreground) and with Docker running; no leftovers.
- [ ] **Signals:** each of the five signals works alone as listed in the plan, and gives a named reason with its evidence.
- [ ] **Right file first:** for six realistic issues on a fixture repo, and four on this repository, the expected file is first (fixture) or in the top 3 (this repository).
- [ ] **Reasons add up:** every candidate has at least one reason; reason points sum to the score; texts name the evidence.
- [ ] **Small:** at most `max_results` candidates; rendered text never exceeds `max_chars`, never cuts mid-line, and says how many were left out.
- [ ] **Deterministic:** same input gives the same output, independent of file order and run; ties break by path.
- [ ] **Honest:** an empty or useless issue gives no candidates and a note; an incomplete index adds a note; test files rank below source files unless named.
- [ ] **Hostile and large input:** 1 MB of text, thousands of identifiers, junk and odd paths stay bounded in time and size.
- [ ] **No model, network, environment or new dependency;** the agent, prompt, tools version and the golden and replay fixtures are unchanged.
- [ ] **JSON round trip** of a `Ranking` is exact.
- [ ] **Mutation check:** each listed breakage fails at least one test.

## Manual

- [ ] README has a "Ranking candidate files" section; decisions recorded as AD entries; roadmap P26 ticked; no `Co-Authored-By` on any commit.
