# Validation: Hard Caps (Roadmap P17)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [x] `uv run pytest` passes with Docker unreachable: only Docker, internet and opt-in live tests are skipped, none fail, and all earlier tests still pass.
- [x] **Limits:** invalid values (zero or negative steps, bools, floats for steps, negative cost, zero or negative time, margin below 1, non-numbers) raise `ValueError`; costs are exact `Decimal`s (0.1 stays 0.1); `run_agent` rejects anything that is not a `Limits`.
- [x] **Config helper:** Haiku's limits are 30 steps, $0.10, 600 s; the cost cap is the lower of the app and model caps in both directions; a free model gets cap 0; zero steps or zero time in the config give an error naming the field.
- [x] **Steps:** the P16 behaviour is unchanged (counts model calls; the last reply's tools are not run), now through `Limits`.
- [x] **Cost before a call:** a call is made when `spent + worst_case` equals the cap and is not made when it is one unit above; the run ends `cost_cap` with no model call, no ledger entry and no tool run; earlier spend in the same job counts; spend that was already in a shared ledger does not.
- [x] **Worst case:** uses the margin; is multiplied by `max_calls_per_step` for a text-action model; uses the adapter's estimate, pricing and output limit.
- [x] **Cost after a call:** a reply that pushed spending over the cap and wants tools ends `cost_cap` and its tools are not run; a final answer over the cap is `finished` and `limit_detail` says the cap was exceeded.
- [x] **Free and zero caps:** a free model with a cap of 0 completes normally; a paid model with a cap of 0 is stopped before its first call.
- [x] **Ledger checks:** a cost cap without a ledger, or with a ledger that is not the one in the adapter chain, raises `ValueError` before any call; the chain is searched through the guard, metering and text-action wrappers; no cost cap needs no ledger.
- [x] **Time:** with a fake clock the run ends `time_cap` before the first call when no time is left, between steps, and before a later tool call in a multi-call reply; skipped calls are answered with a "not run" result, recorded with `executed=False`, and the conversation stays valid (every call has one result); tools receive the time left; with no wall-clock cap they receive `None`.
- [x] **Tool clamps:** `run_command` and `run_tests` use the smaller of their own limit and the time left and are not started with under one second left; the read-only tools are unaffected.
- [x] **Order:** when several limits are reached at once, time wins over cost and cost over steps, and `limit_detail` names the winner with the limit and the amount used.
- [x] **Result:** `cost_usd` is the job's own spend (None without a ledger); `elapsed_s` comes from the injected clock; the new statuses are exported; the result stays immutable.
- [x] **No model names, no environment access** in the agent code (the P16 scan still passes).
- [x] **Mutation check:** each of these breakages makes at least one test fail: cost check removed, `>` changed to `>=` at the boundary, margin ignored, repair doubling ignored, baseline spend not subtracted, post-call check removed, time check before tools removed, skipped calls left unanswered, tool time clamp removed, ledger check removed, checks in the wrong order.

## Docker test (opt-in; run once before merge)

- [x] With a 6 s wall clock a scripted model starts `sleep 60`; the command is stopped at the time left, the run ends `time_cap`, the whole run takes only a few seconds more than the cap, and no labelled containers or volumes are left.

## Manual checks

- [x] Read the `limit_detail` sentences once as the person who sees them in a report: do they say which limit, its value and what was used?
- [x] Compute by hand the worst case for one Haiku step with a 20,000-token prompt and check the code agrees; note how many steps $0.10 allows.
- [x] `git grep -nE "os.environ|getenv" src/bugbite/agent` returns nothing.
- [x] No new dependencies in `pyproject.toml` or `uv.lock`.

## Docs and process

- [x] `specs/decisions.md` has AD-097 to AD-100 with reasons.
- [x] `specs/roadmap.md` has P17 ticked.
- [x] README explains the limits, the worst-case rule and what can still overshoot.
- [x] Commits are small and logical on branch `2026-11-01-p17-hard-caps`, with no co-author trailer.
- [x] No files outside this phase's scope were changed (no batch or project budget, no loop detection, no storage).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
