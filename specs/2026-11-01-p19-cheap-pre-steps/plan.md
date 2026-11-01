# Plan: Cheap Pre-steps (Roadmap P19)

Branch: `2026-11-01-p19-cheap-pre-steps`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-105 onward).

## 1. Parsers (`src/bugbite/agent/issue_parse.py`), pure functions

1. `parse_tracebacks(text) -> list[Traceback]`: `Frame(path, line, function)` and `Traceback(frames, exception)`. Recognises the standard format (including chained tracebacks, `SyntaxError` caret lines, Windows-style paths) and pytest-style `path.py:LINE: in function` lines. Bounded: 5 tracebacks, 40 frames each, one linear pass, no backtracking regexes.
2. `find_path_mentions(text) -> list[str]`: `.py` paths, with or without `:LINE`, in order, without duplicates, at most 30.
3. `find_test_mentions(text) -> list[TestMention]`: `TestMention(node_id, file, name)` for pytest ids and `FAILED` lines, and `name` only for bare `test_...` identifiers. The id character set is restricted as in `requirements.md`.
4. `map_to_repo(path, tracked) -> str | None`: exact match, else the longest tail that matches exactly one tracked file; ambiguous or no match gives None.

## 2. The pre-step (`src/bugbite/agent/prestep.py`)

1. `PrestepReport` and `PrestepResult(text, report)`, both frozen; `report.to_dict()`.
2. `run_prestep(sandbox, context, *, enabled=True, time_limit_s=180, runner=run_tests, clock=time.monotonic) -> PrestepResult`:
   - list tracked files with `git ls-files -z` (argument list, repo as the working directory, capped);
   - parse the issue text, map frames, read snippets through the P14 resolver and `Sandbox.read_file`;
   - list mentioned files that exist;
   - resolve test mentions (tracked file check, `git grep -n -F -e "def NAME" -- "*.py"` for bare names), choose up to 3 targets, run them once with the time left, summarise with the P15 `summarise`;
   - build the quoted section, the report, the log line;
   - every step is wrapped: an exception or a failed command becomes a note and the other steps still run; only argument mistakes raise.
3. `compose_task(issue_task, result) -> str`: the issue task, a blank line, then the section; unchanged when the section is empty.

## 3. Test helpers

Extend the folder-backed fake sandbox so `git` can run (working directory support), and add a helper that turns a temporary folder into a real git repository with a commit.

## 4. Tests

1. Parsers: standard, chained, multiple, truncated, Windows paths, `SyntaxError`, pytest-style, exceptions with odd text, non-traceback text that looks similar, hostile and huge inputs (a time bound), all caps.
2. Mapping: exact, tail suffix, absolute path from another machine, ambiguous dropped, standard library and `site-packages` dropped, `..` and `.git` paths never mapped.
3. `run_prestep` on a real temporary git repo: snippets with correct line numbers and edges (line 1, last line, line past the end), files that exist and do not, a symlink to outside the repo skipped, a binary file skipped, a named test run through an injected runner (targets as separate arguments, `--` safety, cap of 3), bare names (one match, several matches, none), a test id that starts with `-` or contains shell characters never reaches the runner.
4. Failure handling: `git` failing, a read failing, the runner raising, a timeout, an empty repository, none of these raise; notes explain; other parts still appear.
5. The section: quoting of every issue or repository line, labelled as computed by code, empty when nothing is found, caps respected, hostile issue text cannot add an unquoted line.
6. Report: counts and numbers correct, estimated tokens equal to the characters divided by four rounded up, the log line holds counts only (checked with a secret in the issue).
7. Switch: `enabled=False` makes no sandbox call and returns an empty result.
8. Integration: `compose_task` then `run_agent` with a scripted model: the section is in the first user message and in every request.
9. Opt-in Docker test: a real sandbox clone with a traceback issue; the section holds the right snippet; with internet, the named failing test is run for real and appears as failed.
10. Mutation check: unmapped path used, ambiguous mapping accepted, snippet window off by one, a path outside the tracked list read, test id with `-` accepted, test cap removed, quoting removed, section added when empty, switch ignored, an exception escaping, `--` missing before test targets, time budget ignored.

## 5. Docs

README section "Cheap pre-steps"; roadmap P19 ticked; findings in `requirements.md`; validation ticked; AD-105 to AD-108.
