# Validation: Loop Detection (Roadmap P18)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable: only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [ ] **Policy:** defaults are 3/5 and 4/6; values below 2, bools, floats, and a stop threshold not above its nudge threshold raise `ValueError`.
- [ ] **Rule 1:** the second sighting of a call is `ok`, the third a nudge, the fourth `ok`, the fifth a stop; arguments in a different order are the same call; a different argument, output or error flag is a different call; other calls in between do not reset the count.
- [ ] **Rule 2:** failed edits to one file nudge on the fourth and stop on the sixth even when the edit text changes each time; two files are counted separately; protected-file refusals count.
- [ ] **Reset:** a successful edit (replace or create) clears all counts and nudge records, so a nudge can fire again afterwards; a failed edit resets nothing; edit, run tests, same failure, edit, run tests is never flagged.
- [ ] **Executed only:** runs with `executed=False` are ignored.
- [ ] **Strongest signal:** when both rules apply to one run, a stop beats a nudge and only one note is produced.
- [ ] **Determinism and size:** the same sequence always gives the same signals; a 1 MB output adds only a hash to the detector's memory.
- [ ] **Nudge in the loop:** the note is appended to the last tool result of the step, after the original text; it names only the tool or the shortened path and a count; the `ToolRun` still holds the original output; `Step.nudge` and `AgentResult.nudges` record it; a nudge costs no extra model call.
- [ ] **Stop in the loop:** the run ends `loop_detected` with a `limit_detail` naming the rule and the count; the step's tool results are in the conversation and every tool call has exactly one result; `time_cap` wins when the time is also out.
- [ ] **Recovery:** a scripted model that obeys the nudge finishes normally with `nudges == 1`.
- [ ] **Off switch:** `loop_policy=None` never nudges or stops.
- [ ] **Exports and no model names:** new names are exported; the no-hard-coded-model scan and the no-environment scan still pass.
- [ ] **Mutation check:** each of these breakages makes at least one test fail: a threshold off by one, no reset on a successful edit, reset on a failed edit, unsorted arguments, error flag ignored, output ignored, not-executed runs counted, nudge not delivered, stop not ending the run, results message missing after a stop, nudge on the first result, time not winning, rule 2 counting across files, a creating edit not resetting.

## Manual checks

- [ ] Read the two nudge texts once as a small model would: is it clear what to do next?
- [ ] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [ ] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [ ] `specs/decisions.md` has AD-101 to AD-104 with reasons.
- [ ] `specs/roadmap.md` has P18 ticked.
- [ ] README explains the two rules, the reset, the nudge, the stop and the defaults.
- [ ] Commits are small and logical on branch `2026-11-01-p18-loop-detection`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no threshold tuning, no new tools, no storage).

## Definition of done

All boxes ticked, tests green locally (run in the foreground) with Docker both running and unreachable, and the branch ready for review and merge into `main`.
