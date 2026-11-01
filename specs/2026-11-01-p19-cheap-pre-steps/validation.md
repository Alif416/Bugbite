# Validation: Cheap Pre-steps (Roadmap P19)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable (run in the foreground): only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Traceback parser:** standard, chained, multiple, truncated, Windows-path, `SyntaxError` and pytest-style forms give the right frames and exception line; text that only looks like a traceback gives nothing; the caps (5 tracebacks, 40 frames) hold; a 1 MB hostile input is handled in well under a second.
- [x] **Mentions:** `.py` paths with and without line numbers, pytest ids with classes and parametrisation, `FAILED` lines and bare test names are found in order without duplicates; ids outside the safe character set or starting with `-` are not accepted.
- [x] **Mapping:** exact paths, tails of absolute paths from another machine, and unique suffixes map; ambiguous and unknown paths, standard library and `site-packages` frames, `..` and `.git` paths do not.
- [x] **Snippets:** correct numbered lines around the traceback line, including line 1, the last line and a line past the end; at most 3 distinct locations, innermost first; symlinks to outside the repo, binary files and files over 1 MB are skipped.
- [x] **Mentioned files:** only files that exist and are tracked are listed, at most 10.
- [x] **Named tests:** only tracked test files count; at most 3 targets run in one call; targets reach the runner as separate arguments; a bare name is used only when exactly one definition matches; the timeout is the smaller of the sandbox test timeout and the time left.
- [x] **Safety:** nothing from the issue is run as a command; every file read comes from the tracked list; hostile issues (traversal paths, `.git`, option-like test ids, shell characters, control characters, thousands of mentions) leave the repository untouched and never reach pytest as an option.
- [x] **Never fails the job:** `git` failing, a read error, a runner exception, a timeout and an empty repository each give notes and still produce whatever else was found; no exception escapes for them; argument mistakes still raise.
- [x] **The section:** present only when something was found; every issue or repository line is quoted with `| `; labelled as computed by code and as data; hostile issue text cannot create an unquoted line; `format_issue_task(..., checks="")` leaves the task unchanged when the section is empty.
- [x] **Report and log:** counts, test status, characters, estimated tokens (characters divided by four, rounded up), operations done in code and seconds are correct; the one log line holds counts only (a secret placed in the issue never appears in the log); `to_dict()` is plain JSON-ready data.
- [x] **Switch:** `enabled=False` makes no sandbox call and returns an empty result with a report saying it was disabled.
- [x] **Integration:** the section appears in the first user message of every request in a scripted `run_agent` call.
- [x] **No model names, no environment access, no network** in the new code (the earlier scans still pass).
- [x] **Mutation check:** each of these breakages makes at least one test fail: an unmapped path used, ambiguous mapping accepted, snippet window off by one, a file outside the tracked list read, a test id starting with `-` accepted, the test cap removed, quoting removed, a section added when empty, the switch ignored, an exception escaping, `--` missing before the test targets, the time budget ignored.

## Docker tests (opt-in; run once before merge)

- [x] In a real sandbox clone, an issue with a traceback produces the right snippet from the tracked file and ignores a symlink pointing at `/etc/passwd`.
- [x] With internet (pytest is installed from PyPI), the failing test named in the issue is run for real and appears as failed in the section; no labelled containers or volumes are left.

## Manual checks

- [x] Read one complete generated section for a realistic issue: is it short, clearly labelled and useful?
- [x] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-105 to AD-108 with reasons.
- [x] `specs/roadmap.md` has P19 ticked.
- [x] README explains what is parsed and run, the safety rules, the report, the switch, and that no saving is claimed yet.
- [x] Commits are small and logical on branch `2026-11-01-p19-cheap-pre-steps`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no CLI, no retrieval ranking, no reproduction test, no storage).

## Definition of done

All boxes ticked, tests green locally (run in the foreground) with Docker both running and unreachable, and the branch ready for review and merge into `main`.
