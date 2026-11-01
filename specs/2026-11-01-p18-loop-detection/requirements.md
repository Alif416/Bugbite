# Requirements: Loop Detection (Roadmap P18)

## Goal

Notice when the agent is going round in circles and do something about it before the step, cost and time limits run out (README FR5.5: "detect loops, such as repeating the same failed edit, and change strategy or stop"). The README's risk table lists "agent loops forever" with "step, cost and time limits plus loop detection" as the answer; P17 added the limits, this phase adds the detection.

## Scope

**In:**
- `LoopDetector`: a small, exact, easily tested detector that looks at each tool run in order
- Rule 1, **repeated call**: the same tool with the same arguments returning the same result again and again while the repository has not changed
- Rule 2, **repeated failed edits**: failed `edit_file` calls to the same file piling up with no successful edit in between, even when the text differs
- `LoopPolicy`: the thresholds, with defaults, and a way to switch detection off
- Nudge once, then stop: a note to the model first, a `loop_detected` ending if it keeps going
- Results that show what happened (the nudge text, how many nudges, why the run stopped)

**Out (later phases):**
- Tuning the thresholds with real traces (P60)
- Fuzzy or alternating patterns (A, B, A, B), and "similar but not identical" calls
- Streaks of invalid actions from a text-action model, or of tool errors in general
- Restarting the run with a different strategy, or changing the model
- Any use of the model to judge whether it is stuck

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| What counts | Two exact rules, with counting restarted by any successful edit | Simple, explainable, no false alarms from edit-then-retest cycles (AD-101) |
| Response | One nudge, then stop at a higher count | Gives a small model one chance to recover at no extra cost; still ends a stuck run (AD-102) |
| Stopping | Status `loop_detected`; time wins over it; the conversation stays valid | Same ordering idea as P17 (AD-103) |
| Shape | A pure detector class, separate from the loop, fed one tool run at a time | Testable without a model; the loop only acts on its verdicts (AD-104) |

See `specs/decisions.md` AD-101 to AD-104.

## Behaviour

- The detector sees every tool run that was actually executed, in order. Calls answered without running (invalid actions, calls skipped for time) are not counted.
- A **call key** is the tool name, the arguments in a fixed order, whether it was an error, and the exact output text (kept as a hash).
- **Rule 1:** each time a call key is seen, its count goes up. At `repeat_nudge` (default 3) the model gets a nudge; at `repeat_stop` (default 5) the run stops.
- **Rule 2:** each failed `edit_file` adds one to the count for its `path` (protected-file refusals count too). At `edit_fail_nudge` (default 4) the model gets a nudge; at `edit_fail_stop` (default 6) the run stops.
- **Reset:** a successful `edit_file` (a replace or a create) clears every count and every nudge, because the repository changed and earlier results may no longer apply. So edit, run the tests, see the same failure, edit again, run the tests again is not a loop.
- A nudge fires once per rule and call key (or file) when the count reaches the threshold. If one tool run triggers several signals, the most serious wins (stop over nudge) and one note is sent.
- **Nudge delivery:** the note is added to the end of the last tool result of that step, so the model reads it with the results. It states the tool or file and the count, says what to try instead, and quotes none of the output or arguments beyond the tool name and a shortened file path. The recorded `ToolRun` keeps the original output; the step records the nudge text.
- **Stop:** the tool results of the step are still sent into the conversation (it stays valid), then the run ends with `loop_detected`, `limit_detail` naming the rule, the tool or file and the count. If the time limit was also reached, `time_cap` wins.
- `loop_policy=None` turns detection off. Thresholds must be integers of at least 2, with each stop threshold higher than its nudge threshold.

## Context

- README: FR5.5, section 11 risk "Agent loops forever", section 9 metric hints (failure classes include "agent loop detected", line 158 in the failure analysis list).
- Builds on P15 (`edit_file` results and errors), P16 (loop, `Step`, `ToolRun`), P17 (limits and the ordering of stop reasons).
- Small free models are the likely loopers: they quote the wrong `old_text` again and again, or re-run the same command hoping for a different answer.

## Constraints

- Detection is exact and deterministic: same run, same verdicts. No randomness, no model calls, no timing.
- Memory stays small: output text is stored only as a hash.
- A nudge never repeats tool output or issue text back; it names only the tool, a shortened path and a count.
- The loop never reads the environment and never logs task, tool or model text.
- Default `uv run pytest` needs no Docker, internet or key.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- The thresholds (3/5 and 4/6) are first guesses. A model that re-reads the same file three times without editing is nudged although it may have a reason; P60 should tune them with real traces.
- Streaks of invalid actions (text-action models) and of ordinary tool errors are not detected here; they are likely with small models and may need a rule in P60.
- A nudge costs a few tokens in the next prompt; there is no measure yet of how often a nudge rescues a run.
- `run_command` can change files without a successful `edit_file`; an identical command repeated is treated as stuck anyway, since repeating it changes nothing the second time.

## Findings from the build

- The detector returns a fourth kind of signal, `reset`, for a successful edit (the plan said `ok`). The loop uses it to drop signals raised earlier in the same reply: a stop caused by the fifth identical call is cancelled if a real edit comes later in the same reply. A test covers it.
- Identical failing edits trigger both rules: the third repeat nudges (repeated call), the fourth nudges again (failed edits to one file) and the fifth stops (repeated call). That is two notes for one behaviour; the notes are different and the second names the file. Left as is; P60 may merge them.
- Tool names chosen by the model (an unknown tool is still "executed" and returns an error) and file paths are shown in notes and stop sentences only after control characters are replaced and the text is shortened; tests use a name containing a newline and a 300-character path.
- Path spellings (`a.py`, `./a.py`, `a.py/`) count as one file; paths the tools reject are counted by their stripped text.
- Existing P16 and P17 tests needed no change: none of them repeated a call with the same result three times in a way they asserted on.
- Mutation check: 19 breakages (both thresholds off by one, stop comparison, no reset, reset on failure, unsorted arguments, error flag, output, not-executed runs, rule 2 across files, path spellings, unsafe names, nudge not delivered or on the first result, stop not ending the run, results missing after a stop, time not winning, earlier signals not cancelled, policy `None` ignored) are all caught.
- Not measured: how often a nudge rescues a run, and how often it fires wrongly. Both need real traces.
- Full suite (foreground): 2002 passed and 122 skipped with Docker unreachable; 2118 passed and 6 skipped with Docker running; no leftover containers or volumes.
