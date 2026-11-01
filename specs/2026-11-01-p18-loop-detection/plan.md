# Plan: Loop Detection (Roadmap P18)

Branch: `2026-11-01-p18-loop-detection`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-101 onward).

## 1. Policy and detector (`src/bugbite/agent/loopguard.py`)

1. `LoopPolicy(repeat_nudge=3, repeat_stop=5, edit_fail_nudge=4, edit_fail_stop=6)`, frozen; every value an integer of at least 2 (not a bool), each stop threshold greater than its nudge threshold; otherwise `ValueError`. `DEFAULT_LOOP_POLICY`.
2. `Signal(kind, rule, detail, note)`: `kind` is `ok`, `nudge` or `stop`; `rule` is `repeated_call` or `repeated_failed_edit`; `detail` is a sentence for the result; `note` is the text for the model (empty unless a nudge).
3. `LoopDetector(policy).observe(run: ToolRun) -> Signal`: updates counts and returns the most serious signal for that run. Counts per call key (name, canonical JSON of the arguments with sorted keys, error flag, SHA-256 of the output) and per edited path (a shortened, stripped string). A successful `edit_file` clears all counts and all nudge records and returns `ok`. Runs with `executed=False` are ignored.
4. Notes are fixed templates with the tool name or the shortened path and the count only.

## 2. Types

Add `LOOP_DETECTED = "loop_detected"` to the statuses; `Step.nudge: str | None = None`; `AgentResult.nudges: int = 0`.

## 3. The loop

1. New keyword `loop_policy: LoopPolicy | None = DEFAULT_LOOP_POLICY` on `run_agent` (None disables).
2. After the tools of a step have run, feed each executed run to the detector. The step keeps the strongest signal. For a nudge, append the note (after a blank line and a fixed "[Bugbite note]" prefix) to the content of the last tool result in the results message; the `ToolRun` objects keep the original output. For a stop, send the results message as usual, then end: `time_cap` if the time is out, otherwise `loop_detected` with the signal's detail.
3. Export `LoopPolicy`, `LoopDetector`, `LOOP_DETECTED` from `bugbite.agent`.

## 4. Tests

1. Policy validation table.
2. Detector, unit level, with hand-built runs: rule 1 thresholds (2 repeats ok, 3 nudge, 4 ok, 5 stop); different arguments, different output or different error flag are different keys; argument order does not matter; counts survive other calls in between; successful edit resets everything including nudge records (the nudge can fire again afterwards); a failed edit does not reset; rule 2 thresholds per path with changing text; two paths counted separately; protected-file refusals count; create (a successful edit_file without `old_text`) resets; not-executed runs ignored; both rules on one run give the stronger signal; determinism (same input, same signals); very long output stored as a hash only.
3. Loop level with scripted models and the folder-backed fake sandbox: a model repeating `list_directory` gets one nudge in the tool result it sees and the run stops at the stop threshold with `loop_detected`; the conversation is valid and the original `ToolRun` output is unchanged; a model repeating a failing `edit_file` is nudged at 4 and stopped at 6; a model that obeys the nudge, reads the file and edits correctly finishes (`nudges == 1`, status `finished`); edit, run tests, same failure, edit again is not flagged; `loop_policy=None` never nudges; time wins over a loop stop; several tool calls in one reply give one note, in the last result; the note contains no output or arguments.
4. Existing tests adjusted only where an identical repeated call now triggers a nudge.
5. Mutation check: a threshold off by one, no reset on a successful edit, reset on a failed edit, arguments compared unsorted, error flag ignored in the key, output ignored in the key, not-executed runs counted, nudge not delivered, stop not ending the run, results message missing after a stop, nudge placed on the first result, time not winning, rule 2 counting across files, a creating edit not resetting.

## 5. Docs

README section "Loop detection"; roadmap P18 ticked; findings in `requirements.md`; validation ticked; AD-101 to AD-104.
