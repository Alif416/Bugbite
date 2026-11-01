# Plan: Usage and Cost Tracking per Call (Roadmap P11)

Branch: `2026-11-01-p11-cost-tracking`. See `requirements.md` for scope and decisions, `validation.md` for merge criteria. Decisions are logged in `specs/decisions.md` (AD-065 onward).

## 1. Prices become a `pricing` block (AD-065)

1. In `src/bugbite/config.py` add a frozen `Pricing` dataclass holding exact decimal rates in **US dollars per million tokens**: `input`, `output`, `cache_read`, `cache_write`, an optional `long_prompt` rate card (`over_tokens` plus its own `input`, `output`, `cache_read`, `cache_write`), and the provenance fields `as_of` (an ISO date) and `source` (a URL or note). Provide `Pricing.free()`, `Pricing.is_free`, and `Pricing.age_days(today)`.
2. Replace the two flat fields `price_per_input_token` and `price_per_output_token` on `ModelConfig` with `pricing: Pricing`, in the same position. Add `ModelConfig.is_free`. Read-only helpers `price_per_input_token` and `price_per_output_token` (dollars per single token) stay available so nothing that only reads them breaks.
3. Loading rules: the `pricing` block is required (free models write explicit zeros); rates are finite numbers that are not negative and not booleans; floats are read through their text form so `0.10` is exactly one tenth; `long_prompt.over_tokens` is a positive integer and `long_prompt` must give `input` and `output`; `as_of` is required for any model with a non-zero rate and must be a real date; models on the `claude` provider must state `cache_read` and `cache_write` (Anthropic bills them); omitted cache rates otherwise default to the input rate. The old flat fields are rejected with a message that points to `pricing`.
4. Migrate `config/models.yaml`: `haiku` gets the verified figures, the long-prompt card, `as_of: 2026-11-01`, and the pricing page as `source`; `local-free` and `groq-free` get explicit zeros.
5. `pricing_is_stale(pricing, today, max_age_days=30)` reports old price data. Nothing refuses to run on it yet (the eval harness will).

## 2. Cost computation (pure, no I/O)

Create `src/bugbite/adapter/cost.py`:

1. `CallCost` (frozen): `tier` (`standard` or `long_prompt`), `prompt_tokens`, the four component amounts, `total`, `estimated`, `free`; all money as `Decimal`.
2. `compute_cost(pricing, usage, estimated=False) -> CallCost`: choose the rate card by the call's **prompt length**, which counts input, cache-read, and cache-write tokens together (AD-066); a prompt over the threshold, not equal to it, uses the long-prompt card. Each component is tokens times rate divided by one million, in exact decimals.
3. `worst_case_cost(pricing, prompt_tokens, max_output_tokens, margin=1) -> Decimal` (AD-068): the most a call could cost, pricing every prompt token at the larger of the input and cache-write rates and every allowed output token at the output rate, with the rate card chosen from the projected prompt size. `margin` scales the token estimate; calibrating it from real runs is left to the cap phases.
4. Money is `Decimal` everywhere; a helper formats it for display without scientific notation (AD-069).

## 3. The ledger and the metering wrapper (AD-067)

1. `CallRecord` (frozen): sequence number, model name, request id, stop reason, `Usage`, `CallCost` (or none for a failed call), `latency_s`, UTC timestamp, `error_code` for a failed call.
2. `CostLedger` (thread-safe): `record(...)`, `calls`, `total` (exact `Decimal`), `by_model()`, token totals, counts of calls, failed calls, and estimated calls, total latency, and `snapshot()` returning a JSON-safe dictionary (money as strings) for later storage by the trace store. It enforces nothing.
3. `MeteredAdapter(inner, ledger)` in `src/bugbite/adapter/metered.py`: itself a `ModelAdapter` with the inner adapter's config and name. It calls the inner adapter, computes the cost with the inner model's pricing, records it, and returns the **same response object** unchanged. On an `AdapterError` that involved the provider it records a failed call (error code, no cost, measured latency) and re-raises the same error; a request refused locally before anything was sent is not a call and is not recorded (AD-067 note). Other exceptions pass through unrecorded. It delegates `estimate_tokens`, exposes `ledger`, `last_call`, and `worst_case_cost(request)`.
4. `create_adapter(model, api_key=..., ledger=None)` returns a `MeteredAdapter` when a ledger is given, so entry points get metering in one argument.

## 4. Tests

1. **Pricing config:** valid blocks (free, paid, long-prompt, all fields), exact decimal reading of values like `0.10` and `0.125`, every rejection (missing block, negative, non-finite, boolean, text, missing `as_of` for a paid model, bad date, `claude` without cache rates, long-prompt without input/output, zero or negative threshold, unknown keys, old flat fields with the hint), defaults, `age_days`, `pricing_is_stale`, the shipped `models.yaml` including Haiku's long-prompt card.
2. **Cost computation:** hand-checked golden figures for Haiku (a full four-component call, a pure output call, a pure cache-read call), the tier boundary at exactly the threshold and one token over, cache tokens counting toward prompt length, free models costing exactly zero, estimated usage flagged, exact sums over thousands of calls with no drift, and `worst_case_cost` including the tier switch and margin.
3. **Ledger:** totals, per-model totals, token sums, failed and estimated counts, snapshot content and JSON round-trip, thread safety under concurrent recording, no caps enforced.
4. **Metering wrapper:** records every success and every failure, returns the identical response object, re-raises the identical error, does not record non-adapter exceptions, shares one ledger across two models, passes the shared adapter contract, and `create_adapter(..., ledger=...)` wraps.
5. **A realistic scenario:** a 20-step agent-like run on the Haiku card with a mostly cached prompt stays well under the 0.10 USD per-issue cap, and the same run uncached costs more, which documents what caching is worth.
6. Update every existing test and helper that builds a `ModelConfig` or reads the old price fields.
7. Opt-in live tests (P9, P10) print cost with the same function instead of their own price table.

## 5. Docs and wrap-up

1. Add AD-065 to AD-069 to `specs/decisions.md` (written with the specs). Tick P11 in `specs/roadmap.md`.
2. README: the `pricing` block, how a call's cost is computed (including the long-prompt rule), the metering wrapper and ledger, and the reminder to re-check prices before each paid run.
3. Commit in small logical commits, then merge into `main` with `--no-ff` and push when asked. Commit messages carry no co-author trailer.
