# Validation: Read-only Agent Tools (Roadmap P14)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable: only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Definitions:** each tool has a valid `ToolDefinition` (schema type object, required fields, no extra properties allowed); the three names are `read_file`, `list_directory`, `search_code`; the registry rejects duplicate names.
- [x] **Path safety:** absolute paths, `..`, NUL/newline, backslash tricks, and anything touching `.git` are rejected; valid relative paths resolve under `/workspace/repo`; a seeded property test finds no input that resolves outside it.
- [x] **read_file:** numbered lines; line ranges inclusive and 1-based; caps of 200 lines and 20,000 characters with the continuation hint; missing, directory, binary and over-large files give clear error results; invalid ranges are errors.
- [x] **list_directory:** directories first with `/`, sorted, `.git` hidden, 200-entry cap with a count of what was left out; file or missing path gives an error result.
- [x] **search_code:** fixed-string by default, regex only when asked; `--` precedes the pattern and path; excluded directories; 50-match cap and 200-character line cap with a notice; no matches is a non-error result; grep failure and timeout are error results; unsafe `glob` is rejected.
- [x] **No shell from model input:** a test captures the commands the tools send to the sandbox and asserts they are argument lists containing the model's text only as separate elements.
- [x] **Registry:** unknown tool, schema-invalid arguments, and an exception inside a tool each return an error result (never raise); results convert to `ToolResultBlock`.
- [x] **Read-only:** a test asserts the tools never call anything that writes (the fake sandbox raises on `write_file` or any non-listed command).
- [x] **Adapter fit:** the definitions pass `validate_request` and work through `TextActionAdapter` argument validation.
- [x] **Mutation check:** each of these breakages makes at least one test fail: path escape allowed, `.git` visible, the line cap removed, the pattern placed before `--`, a shell string used, regex on by default.

## Docker tests (opt-in; run once before merge)

- [x] Against a real sandbox with a small repo: listing, reading, and searching give the expected text; a file with spaces and quotes in its name works; a binary file is refused; a symlink pointing outside the repo is not followed out; no leftover labelled containers or volumes.

## Manual checks

- [x] Read each tool description once as if you were a small model: is it clear what to pass and what comes back?
- [x] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-082 to AD-086 with reasons.
- [x] `specs/roadmap.md` has P14 ticked.
- [x] README explains the tools, their caps, and the path rules.
- [x] Commits are small and logical on branch `2026-11-01-p14-read-only-tools`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no edit/run tools, no loop, no storage).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
