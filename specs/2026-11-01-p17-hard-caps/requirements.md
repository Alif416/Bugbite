# Requirements: Hard Caps (Roadmap P17)

## Goal

Make the three per-job limits in FR5.4 real and tested: a job stops by itself when it reaches its maximum number of steps, its maximum cost in dollars, or its maximum wall-clock time. The README says the spend cap "must stop the run, not the credit card", so cost is checked before money is spent, not after.

## Scope

**In:**
- `Limits`: `max_steps`, `max_cost_usd` (optional), `max_wall_clock_s` (optional), and the margin used for the worst-case estimate
- `limits_from_config(app, model)`: builds the limits from `config/app.yaml` and the model's `per_issue_cap_usd`
- `run_agent(..., limits=..., ledger=...)`: replaces the P16 `max_steps` argument
- Cost cap checked before every model call, using the worst case for that call, and again after it
- Wall-clock cap checked before every model call and before every tool call; `run_tests` and `run_command` get at most the time left
- New stop reasons `cost_cap` and `time_cap`, and a result that reports the job's cost, elapsed time and what was hit
- Fail-closed checks: a cost cap without a matching ledger is refused up front

**Out (later phases):**
- Per-batch and per-model caps, the project-wide 5 USD budget and the spend counter (P46)
- Spend that persists between runs (storage phases)
- Tuning the step limit with real runs (P60), loop detection (P18)
- Retrying or continuing after a cap is hit
- Cancelling a model call that is already in flight (the adapter's own timeout bounds it)
- Calibrating the worst-case margin against real usage (needs real runs)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Configuration | A `Limits` object; a helper builds it from config; cost cap is the lower of the app cap and the model's `per_issue_cap_usd` | One place combines the two config values; callers cannot get it wrong (AD-097) |
| Cost cap | Never exceeded: before each call add the worst case for that call to what is spent; stop if it could pass the cap; also check after the call | "Hard cap" means the real money; checking only afterwards lets a job overshoot (AD-098) |
| Time cap | Checked before every model call and tool call; tools get the time left as their own limit | A 300 s test run must not overshoot a 600 s cap that is nearly used up (AD-099) |
| Stop reasons | New `cost_cap` and `time_cap`; result reports cost, elapsed time and a plain-language detail | Failure analysis and the dashboard need to know which limit stopped a job (AD-100) |

See `specs/decisions.md` AD-097 to AD-100.

## Behaviour

- **Order of checks** at the start of each step: time, then cost, then (as in P16) the step count. Whichever is hit first ends the run.
- **max_steps** counts model calls, as in P16. The final allowed reply is recorded and its tool calls are not run.
- **Cost:** `spent` is what the job's ledger entries have cost since the job started (the ledger may be shared, so the start value is subtracted). Before a call the loop computes the worst case: the estimated prompt (scaled by the margin, default 1.25) at the dearest input rate for the size, plus the largest allowed output at the output rate, multiplied by the number of model calls one step can make (2 for a model run through the text-action wrapper, because of its repair). If `spent + worst` is more than the cap, the run ends with `cost_cap` and no call is made. A cap exactly equal to `spent + worst` is allowed. After a call, if `spent` is already above the cap and the reply wants tools, the tools are not run and the run ends with `cost_cap`; if the reply is a final answer the run is `finished` and the result says the cap was exceeded and the estimate was too low.
- **Free models:** their calls cost 0, so a cost cap of 0 never stops them. A paid model with a cap of 0 is stopped before its first call.
- **Time:** the clock starts when `run_agent` is called. If no time is left, the run ends with `time_cap` before the next model call. Before each tool call the loop checks the time again: tool calls it cannot start are answered with "not run: the time limit was reached" (so the conversation stays valid) and the run ends. Each tool gets the time left (`time_limit_s`): `run_command` and `run_tests` use the smaller of their own limit and the time left, and are not started if less than one second is left. The read-only tools keep their fixed 30 s limit.
- **Ledger:** if there is a cost cap, `ledger` must be given and must be the ledger of a `MeteredAdapter` in the adapter chain; otherwise `run_agent` raises `ValueError` before any call.
- **Result:** adds `cost_usd` (the job's spend, or None without a ledger), `elapsed_s` and `limit_detail` (one sentence naming the limit, its value and the amount used).

## Context

- README: FR5.4 (hard limits), non-functional "Cost" row (hard cap per issue, default 0.10 USD for Haiku, set per model; stop automatically), section 9 and 11 (budget is 5 USD, "hard spend cap enforced in code").
- Builds on P11 (`CostLedger`, `worst_case_cost`, `MeteredAdapter`), P12 (`max_calls_per_step`), P15 (`run_tests`, `run_command` timeouts) and P16 (the loop).
- `config/app.yaml` already has `max_steps: 30`, `max_cost_usd: 0.10`, `max_wall_clock_s: 600`; models have `per_issue_cap_usd`.

## Constraints

- The worst case is computed from the adapter's own estimate and pricing; the loop knows no provider or model names.
- A cap that cannot be checked fails closed: no ledger, or a ledger not attached, is an error before any call.
- Time uses a monotonic clock; tests inject a fake clock and never sleep.
- The loop never reads the environment and never logs task, tool or model text.
- Default `uv run pytest` needs no Docker, internet or key. Docker tests are opt-in.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- The 1.25 margin on the prompt estimate is a guess: the estimate is characters divided by four. Real runs (P20, P46) should show how far it is from the provider's counts. Until then the margin errs towards stopping early.
- The worst case prices every prompt token at the dearest rate and allows the whole output limit, so jobs stop earlier than a "typical" estimate would. With the default Haiku numbers this still leaves many steps within $0.10, but that is calculated, not measured.
- A model call in flight cannot be stopped, so a job can run over the time cap by up to one model call (bounded by the adapter's timeout) or one read-only tool call (30 s).
- The caps are per job; one job cannot see another's spend. Batches and the 5 USD project budget are P46.

## Findings from the build

- `TextActionAdapter` got a public `inner` property so the ledger can be found by walking the chain (it was the only wrapper without one).
- The pre-check and the post-check are both needed: tests show a reply that costs far more than estimated is caught after the call (its tools are not run), and a final answer over the cap is kept with a note.
- The time gate after a model call can find the clock already out: the tool calls are then answered "not run" and the run ends at the top of the loop (or after the last step, where time wins over steps). Every call in the history has exactly one result in all these cases.
- A hand check of one Haiku step with a 20,000-token prompt gives a worst case of $0.005173 (the code agrees), against a typical $0.00225, so about 44 such steps fit in $0.10 and the 30-step limit comes first. Over 80,000 prompt tokens the 1.25 margin pushes the estimate into the long-prompt price tier, which makes the worst case jump; long conversations are therefore stopped early. Not measured against real usage.
- The Docker test showed the clamp working with a real sleeping command: a 6 s cap and `sleep 60` ended in about 6 s.
- Mutation check: 18 breakages (cost check removed, boundary, margin, repair doubling, baseline spend, post-call check, tool time check, skipped calls unanswered, both tool clamps, ledger checks, check order, config helper, bool steps, time not passed to tools) are all caught.
- Tests need distinct tool-call ids per scripted reply; a Docker test that reused `call_1` ended as `model_error` because the request validator rejects duplicate ids.
- Running the whole suite as a background shell job made two or three signal-related tests fail (`test_nothing_is_installed_on_import` among them), because a background job starts with some signals ignored. The same tests pass in a normal foreground run, so the final runs for this phase were done in the foreground: 1923 passed and 122 skipped with Docker unreachable, 2039 passed and 6 skipped with Docker running, no leftover containers or volumes. Run the suite in the foreground.
