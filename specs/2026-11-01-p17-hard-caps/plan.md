# Plan: Hard Caps (Roadmap P17)

Branch: `2026-11-01-p17-hard-caps`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-097 onward).

## 1. `Limits` and the config helper (`src/bugbite/agent/limits.py`)

1. `Limits(max_steps, max_cost_usd=None, max_wall_clock_s=None, cost_margin=Decimal("1.25"))`, frozen. `max_steps` is an integer of at least 1 (not a bool); `max_cost_usd` is None or a non-negative number turned into a `Decimal` through `str` (no float noise); `max_wall_clock_s` is None or greater than zero; `cost_margin` is a number of at least 1. Bad values raise `ValueError`.
2. `limits_from_config(app, model) -> Limits`: steps and time from the app config; cost is the lower of `app.max_cost_usd` and `model.per_issue_cap_usd`. Values the config allows but `Limits` does not (zero steps, zero time) give a `ValueError` that names the config field.

## 2. Tools get the time left

1. `Tool.run(arguments, *, time_limit_s=None)` and `ToolRegistry.execute(name, arguments, *, time_limit_s=None)` pass the number to `_run`, which receives it as a second argument.
2. `RunCommand` uses `min(requested or default, sandbox limit, time left)`, rounded up to whole seconds, and does not run if less than one second is left. `RunTests` passes `timeout=min(test timeout, time left)` to the runner only when a limit is given, and refuses likewise. Read-only tools ignore it.
3. `TOOLS_VERSION` becomes "3" if descriptions change (they do not), otherwise stays "2".

## 3. The loop (`src/bugbite/agent/loop.py`)

1. New signature `run_agent(adapter, tools, task, *, limits, ledger=None, system_prompt=..., observer=None, max_output_tokens=None, clock=time.monotonic)`. `limits` must be a `Limits`.
2. Up front: if `limits.max_cost_usd` is set, `ledger` must be given and found in the adapter chain (walking `.inner`; `TextActionAdapter` gets a public read-only `inner` property for this, as the guard and metering wrappers already have); else `ValueError`.
3. Per step, in this order: time check, request building, cost pre-check (worst case times `max_calls_per_step` found on the adapter, default 1), step count handled as in P16.
4. After the call: post-cost check before running tools; per tool call: time check, then run with `time_limit_s`; calls that cannot be started are answered with a "not run" error and recorded with `executed=False`.
5. The result gets `cost_usd`, `elapsed_s` and `limit_detail`; statuses `COST_CAP` and `TIME_CAP` are added and exported.

## 4. Update P16 code and tests

Replace every `max_steps=` argument with `limits=Limits(max_steps=...)`. Move the `max_steps` argument tests to the `Limits` tests. `FakeTools.execute` accepts `time_limit_s`. README example updated.

## 5. Tests

1. `Limits`: validation table, Decimal handling, `limits_from_config` for Haiku, a free model, an app cap lower than the model cap, zero values.
2. Cost pre-check with a metered scripted adapter: allowed when `spent + worst` equals the cap, blocked one unit above; no call made when blocked; spent accounts for earlier calls and for a shared ledger's earlier spend; the text-action wrapper doubles the worst case; a paid model with cap 0 is blocked at once; a free model with cap 0 runs.
3. Cost post-check: a reply that cost more than estimated with tool calls ends `cost_cap` without running tools; a final answer over the cap is `finished` with a detail sentence.
4. Ledger checks: missing ledger, a ledger not in the chain, a ledger inside a text-action and guard chain (found), no cap with no ledger (fine).
5. Time: fake clock; blocked before the first call, between steps, and before a later tool call in a multi-call reply (skipped calls answered, conversation valid); tools receive the time left; `run_command` and `run_tests` clamp; under one second left means not run; no wall cap means `time_limit_s=None`.
6. Order and combinations: time beats cost beats steps; each reported in `limit_detail` with the numbers.
7. Result: `cost_usd` and `elapsed_s` correct; immutable.
8. Opt-in Docker test: a scripted model starts `sleep 60` with a 6 s wall clock; the command is stopped at the time left, the run ends `time_cap`, total elapsed is a few seconds more than the cap at most.
9. Mutation check: cost check removed, `>` changed to `>=` at the boundary, margin ignored, repair doubling ignored, baseline spend not subtracted, post-check removed, time check before tools removed, skipped calls left unanswered, clamp removed, ledger check removed, wrong order of checks.

## 6. Docs

README: a "Limits" section (what each cap does, the worst-case rule, what can still overshoot); roadmap P17 ticked; findings in `requirements.md`; validation ticked; AD-097 to AD-100.
