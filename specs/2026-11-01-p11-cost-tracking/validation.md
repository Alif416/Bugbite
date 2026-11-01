# Validation: Usage and Cost Tracking per Call (Roadmap P11)

The work can be merged when every item below is true.

## Automated (no Docker, no internet, no key)

- [ ] `uv run pytest` passes with Docker unreachable and no internet: only Docker, internet, and opt-in live tests are skipped, none fail, and all earlier tests still pass after the config migration.
- [ ] **Pricing config:**
  - [ ] valid free, paid, long-prompt, and cache-priced blocks load; values read from YAML like `0.10` and `0.125` are exact decimals (`Decimal("0.10")`, not binary floats)
  - [ ] rejected with a message naming the field: missing `pricing` block; negative, infinite, NaN, boolean, and text rates; a paid model without `as_of`; an `as_of` that is not a real date; a `claude` model without `cache_read` or `cache_write`; `long_prompt` without `input` or `output`; a zero or negative `over_tokens`; unknown keys inside the block
  - [ ] the old flat fields are rejected with a hint that points to `pricing`
  - [ ] omitted cache rates default to the input rate for non-Claude models
  - [ ] `Pricing.free()`, `is_free`, `ModelConfig.is_free`, `age_days`, and `pricing_is_stale` behave as specified, including the exact 30-day boundary
  - [ ] the read-only per-token helpers return the per-million rate divided by one million
  - [ ] the shipped `config/models.yaml` loads; `haiku` has input 0.10, output 0.50, cache read 0.01, cache write 0.125, a long-prompt card of 100000 / 0.50 / 2.50 / 0.05 / 0.625, `as_of` 2026-11-01 and a source; the two free models are explicit zeros
- [ ] **Cost computation:**
  - [ ] hand-checked golden figures on the Haiku card: a call with input 1000, output 200, cache reads 5000, cache writes 400 costs exactly $0.0003; a pure output call; a pure cache-read call; a zero-usage call costs exactly zero
  - [ ] **Tier boundary:** a prompt of exactly 100,000 tokens uses the standard card; 100,001 uses the long-prompt card; cache-read and cache-write tokens count toward prompt length (for example 60,000 input + 40,001 cache reads is long-prompt)
  - [ ] free models cost exactly zero for any usage, and the cost is flagged free
  - [ ] estimated usage gives a cost flagged `estimated`
  - [ ] summing 10,000 calls gives the exact expected total (no drift)
  - [ ] `worst_case_cost` prices the prompt at the larger of input and cache-write rates, the full output allowance at the output rate, switches tier on the projected prompt size, applies `margin`, and rejects negative inputs
- [ ] **Ledger:** records successes and failures; total, per-model totals, token sums, call, failed-call, and estimated-call counts, and total latency are right; `snapshot()` is JSON-serialisable with money as strings and round-trips through `json`; concurrent recording from many threads loses nothing; the ledger enforces no cap whatever the total.
- [ ] **Metering wrapper:**
  - [ ] returns the identical response object the inner adapter returned and raises the identical error object
  - [ ] records a success with the right tokens, tier, cost, request id, stop reason, and latency; records an `AdapterError` as a failed call with its code and no cost
  - [ ] a non-adapter exception (a bug) passes through and is not recorded
  - [ ] one ledger shared by two different models keeps separate per-model totals
  - [ ] it passes the shared `AdapterContract` tests when wrapping the scripted, OpenAI-compatible, and Claude adapters
  - [ ] `create_adapter(..., ledger=ledger)` returns a metered adapter and `create_adapter(...)` without a ledger returns the plain one
  - [ ] `name`, `config`, and `estimate_tokens` are the inner adapter's
- [ ] **Realistic scenario:** a 20-step run on the Haiku card with a mostly cached 20,000-token prompt stays under the 0.10 USD per-issue cap, and the same run without cache hits costs more (the difference is asserted).
- [ ] Every test and helper that built a `ModelConfig` or read the old price fields is updated; the live tests use the shared cost function.

## Manual checks

- [ ] `git grep -nE "float\(|round\(" src/bugbite/adapter/cost.py src/bugbite/adapter/metered.py src/bugbite/adapter/ledger.py` shows no binary float arithmetic on money (conversions for display only).
- [ ] `git grep -nE "price_per_(input|output)_token" -- config src tests` shows the old names only inside the compatibility helpers and their tests, never in `config/models.yaml`.
- [ ] `git grep -nE "os.environ|getenv" src/bugbite/adapter` returns nothing new.
- [ ] No new dependencies in `pyproject.toml` or `uv.lock`.
- [ ] A snapshot printed from a small scripted run reads clearly (looked at once).
- [ ] Prices in `config/models.yaml` still match the official pages read on 2026-11-01 (compared once against the P10 record).

## Docs and process

- [ ] `specs/decisions.md` has AD-065 to AD-069 with reasons.
- [ ] `specs/roadmap.md` has P11 ticked.
- [ ] README explains the `pricing` block, how cost is computed, the metering wrapper and ledger, and the re-check reminder.
- [ ] Commits are small and logical on branch `2026-11-01-p11-cost-tracking`, with no co-author trailer.
- [ ] No files outside this phase's scope were changed (no cap enforcement, persistence, dashboard, or agent code).

## Definition of done

All boxes ticked, tests green locally with Docker both running and unreachable, and the branch ready for review and merge into `main`.
