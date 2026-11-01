# Requirements: Cheap Pre-steps (Roadmap P19)

## Goal

Do the cheap, obvious work in plain code before the first model call, so the model starts with facts instead of spending paid steps to find them (README FR5.7): read the tracebacks, file paths and test names out of the issue, check which of them exist in the repository, show the code at the traceback locations, run the failing test the issue names, and hand all of it to the model as context. Record plainly what this did and cost, so a later comparison can measure the real saving.

## Scope

**In:**
- Parsers for issue text (pure functions): Python tracebacks, `file.py:LINE` references, file paths, pytest test ids and test function names
- Mapping a path from the reporter's machine to a file in the repository
- `run_prestep(sandbox, context, ...)`: code snippets around traceback locations, the list of mentioned files that exist, and one test run of the named tests, all in the sandbox
- A labelled, quoted "Checks Bugbite ran before you started" section added to the task text (`format_issue_task(context, checks=...)`)
- A `PrestepReport` of plain numbers, one log line (counts only), and an on/off switch
- Never failing the job: any problem becomes a note and the job goes on

**Out (later phases):**
- Working out how much it saves: that needs the same issues run with and without pre-steps (the on/off switch is for the eval harness)
- Writing or checking a reproduction test (FR4), the baseline run of the whole suite (FR6.2)
- Ranking candidate files, symbol index, semantic search (FR3, later retrieval phases)
- Running code or commands that appear in the issue
- Wiring it into the CLI (P45) and recording the report in the trace store (P21, P22)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Delivery | A labelled section added to the task text, with repository content and issue text quoted line by line | One honest user message; works for every adapter; plainly data (AD-105) |
| Safety | Only files tracked by git, resolved inside the sandbox; test ids restricted to a safe character set; explicit test targets only; nothing from the issue is ever run as a command | The issue is untrusted input steering code that runs (AD-106) |
| Measuring | Log the certain facts and keep an on/off switch; claim no saving until a with/without comparison exists | A single run cannot show what did not happen (AD-107) |
| Failure | Pre-steps never raise for repository or issue problems; they have their own time budget | They are a convenience; they must not be able to break or stall a job (AD-108) |

See `specs/decisions.md` AD-105 to AD-108.

## Behaviour

- **Text examined:** the issue title, body and comments, in that order, up to 30,000 characters.
- **Tracebacks:** blocks that start with `Traceback (most recent call last):` give a list of frames (file, line, function) and the final exception line (shortened to 300 characters). Pytest-style `path.py:LINE: in function` lines also give frames. At most 5 tracebacks are used.
- **Mapping to the repository:** the list of files comes from `git ls-files` in the sandbox. A relative path that is in the list is used as is; otherwise the longest tail of the path that matches exactly one tracked file is used. Frames that match nothing (standard library, installed packages) or match several files are dropped.
- **Snippets:** for the innermost (last) frames that map to repository files, at most 3 distinct locations, the lines around the traceback line (10 before and 10 after, numbered) are read through the sandbox, resolving symlinks first. Files over 1 MB and binary files are skipped.
- **Mentioned files:** other `.py` paths in the text that exist in the repository are listed by name, at most 10.
- **Named tests:** pytest ids (`tests/test_a.py::TestX::test_y`, including a parametrisation in square brackets) and `FAILED <id>` lines whose file is tracked, plus bare `test_something` names that match exactly one `def test_something` in the repository (found with `git grep`, at most 5 names tried). At most 3 targets are run, in a single pytest call, with a timeout of the smaller of the sandbox's test timeout and the pre-step time left.
- **Summary of the run:** the same compact summary the `run_tests` tool gives (counts, failing tests with a one-line reason, a capped output tail).
- **The section:** only parts that have content appear; if nothing was found there is no section and the task is unchanged. Everything that came from the issue or the repository is quoted with `| ` on every line. The section says it was computed by code and is data, not instructions.
- **Report:** whether it ran, counts (tracebacks, mapped frames, snippets, mentioned files, tests named, tests run), the test status, characters and estimated tokens added to the prompt, the number of operations done in code (snippet reads, the test run, `git grep` lookups), seconds spent, and notes about anything that failed. One log line with the counts, never any content.
- **Switch:** `enabled=False` returns an empty result without touching the sandbox.
- **Time:** `time_limit_s` (default 180) is the pre-step's own budget; the caller subtracts the time used from the job's wall-clock limit.

## Context

- README: FR5.7, FR3.4 (small context), non-functional cost rules ("develop against failing tests locally before spending API money").
- Builds on P3 (`JobContext`, issue text is untrusted), P6 (`run_tests`), P14 (the symlink-safe resolver), P15 (`summarise`), P16 (`format_issue_task`, the quoting convention).
- Issue text can be written by anyone. A path, a test id or a traceback in it is a claim, not a fact, until the code has checked it against the repository.

## Constraints

- Nothing from the issue is run as a command or used as a path without being matched against the tracked file list first.
- Test ids reach pytest only as separate arguments after `--`, inside the character set `[A-Za-z0-9_./\-\[\],:=]` plus the `::` separator, and never start with `-`.
- Bounded work: at most 5 tracebacks, 3 snippets, 10 listed files, 5 name lookups, 3 test targets, 30,000 characters of issue text, 50,000 listed files.
- No model call, no network, no environment access, no logging of issue or repository content.
- Default `uv run pytest` needs no Docker, internet or key (a folder-backed fake sandbox with real `git`); Docker and internet tests are opt-in.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Whether pre-steps lower tokens and cost, and by how much, is not known. The eval harness must run the same issues with `enabled=True` and `enabled=False`.
- Only Python (`.py`) paths and pytest ids are understood. Other kinds of trace (JavaScript, Java) are out of scope for a Python-only project.
- A test that needs the network fails in the sandbox; its failure is then shown to the model as a failure, which can mislead. The existing note about network-dependent tests applies.
- Quoted snippets and test output cost prompt tokens on every step; the caps are first guesses.
- The pre-step report is not stored anywhere yet (P21, P22).

## Findings from the build

- The plan's `compose_task(issue_task, result)` became a `checks=` argument of `format_issue_task`, so the section lands before the final "Your job" instruction instead of after it. With `checks=""` the task is byte-for-byte what it was.
- Bare test names need their class to be run (`path::Class::test_x`): the pre-step reads the file and walks up the indentation to find the enclosing classes (nested classes too); a function nested inside another function is not run.
- Choosing which locations to show first and reading them afterwards let unreadable ones (a symlink, a binary file) use up the three snippet slots. A review of the tests showed a hostile traceback could crowd out real code, so locations are now tried in turn (up to 10) until three are readable; a test covers it.
- A frame whose path maps to a tracked symlink counts in `mapped_frames` (it matched by name) but is not read (it resolves outside the repo), so `mapped_frames` can be larger than `snippets`.
- `tool_calls_done_in_code` counts snippet reads, name lookups and the test run. It is a count of operations, not a count of model steps saved: a model can make several calls in one reply.
- The first test for estimated tokens passed only because that section's length divided by four; the mutation check caught it. The test now covers every remainder.
- Mutation check: 22 breakages (an unmapped path used, ambiguous mapping, snippet window, reading without the symlink-safe resolver, ids not matched to tracked files, the target cap, quoting, a section when empty, the switch, a runner or git exception escaping, the time budget, ambiguous bare names, lost class names, frame order, token rounding, the listed-file cap, snippet slots, binary files, exception cut, control characters, the section not placed in the task) are all caught.
- A realistic section for a small issue is about 1,000 characters, roughly 260 estimated tokens, and takes two operations in code.
- Not measured: the real effect on tokens, cost and success. That needs the eval harness (switch on and off).
- Full suite (foreground): 2097 passed and 124 skipped with Docker unreachable; 2215 passed and 6 skipped with Docker running (including the real clone and the real pytest run); no leftover containers or volumes.
