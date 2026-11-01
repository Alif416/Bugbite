# Requirements: Usage and Cost Tracking per Call (Roadmap P11)

## Goal

Know, exactly and for every model call, what it cost: tokens by kind, the rate card that applied, the dollars, and the running total per job and per model. This delivers FR14.6 (usage and cost tracked per call for every model; free models log tokens and time with cost 0), and it is the measuring layer under every cost claim and every spend cap the README promises (budget 5 USD, 0.10 USD per issue, cost per resolved issue).

## Scope

**In:**
- A `pricing` block in the model config, in dollars per million tokens, with cache prices, an optional long-prompt rate card, and provenance (`as_of`, `source`)
- Exact (`Decimal`) cost computation for one call, including the tier rule
- A worst-case projection function for later cap enforcement
- `CostLedger`: thread-safe running totals per job and per model, failed calls recorded, JSON-safe snapshot
- `MeteredAdapter`: wraps any adapter, records every call, changes nothing else
- Migration of the existing config entries, tests, and helpers
- Staleness check for price data (reporting only)

**Out (later phases):**
- Enforcing caps: per issue, per batch, per model, and stopping a job (P17, P46)
- Persisting calls and totals to the database (P21), the spend counter and dashboard (P71), recordings (P22)
- Calibrating a safety margin for token estimates (decided with real runs, P46/P47)
- Batch API discounts, 1-hour cache writes, regional price multipliers, and any pricing that is not per token
- Fetching prices from the internet automatically
- Refusing to run on stale prices (the eval harness, P49)

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Price format | Nested `pricing` block in dollars per million tokens; old flat fields replaced | Matches how providers publish prices; checkable by eye; room for cache and tier prices; the owner's choice (AD-065) |
| Tier rule | Rate card chosen per call by prompt length, counting cache tokens | That is how the provider bills (AD-066) |
| Where cost lives | `MeteredAdapter` wrapper plus `CostLedger`; responses unchanged | Works for every adapter; recordings stay free of price data; the owner's choice (AD-067) |
| Caps | Measure only; offer `worst_case_cost` | Enforcement belongs to P17 and P46; the owner's choice (AD-068) |
| Money type | `Decimal` | Exact sums and exact comparisons against caps (AD-069) |

See `specs/decisions.md` AD-065 to AD-069.

## Context

- README: FR14.6 (usage and cost per call, free models log tokens and time with cost 0), FR14.3 (price per token, 0 for free models), section 6 cost rules (5 USD total, 0.10 USD per issue for Haiku, caps per issue, batch, and model, prompt caching on), section 9 (cost per issue and per resolved issue, token reduction, the budget plan), FR8.4 (spend counter on the dashboard, later), FR13.5 (cost per issue and per solved issue per model), risks ("High API cost during evals").
- The official prices read on 2026-11-01 (see P10): Haiku 5.5 is $0.10 / $0.50 per million input / output tokens for prompts up to 100,000 tokens, with cache hits $0.01 and 5-minute cache writes $0.125; for prompts over 100,000 tokens it is $0.50 / $2.50 with cache hits $0.05 and writes $0.625. A request's prompt length counts all its input tokens including cache reads and writes, and each request is priced on its own.
- `Usage` (P8) already separates input, output, cache-read, and cache-write tokens, and carries `usage_estimated` through responses (P9).
- Rough scale for sanity: a 20,000-token prompt with most of it cached costs about a tenth of a cent per call on Haiku, so a 20-step run is well under the 0.10 USD per-issue cap.
- Prices change. The config records `as_of`, and the README requires re-checking before each paid run.

## Constraints

- Cost arithmetic uses `Decimal` only; no binary floating point in money.
- A response object returned through the wrapper is the same object the inner adapter returned.
- A failed call is recorded but never given an invented cost.
- The ledger and wrapper never read the environment and never log request or response content.
- Default `uv run pytest` needs no network, no Docker, and no key for these tests.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- Whether a failed call that timed out was billed by the provider is unknown; such calls are recorded as failed with no cost, and the real provider invoices remain the final check on spend.
- The estimate behind `worst_case_cost` is the rough four-characters-per-token heuristic; newer Claude tokenizers produce more tokens than that, so a margin above 1 is likely right and is calibrated later.
- 1-hour cache writes cost more than the 5-minute writes the pricing block holds; the adapters only use 5-minute caching today.
- A cost report format for the eval harness (P52) and the dashboard is not defined here.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-065 to AD-069).

## Findings from the build (2026-11-01)

- All figures were checked by hand against the Haiku 5.5 rate card; the golden example (1000 input, 200 output, 5000 cache-read, 400 cache-write tokens) is exactly $0.0003.
- My first tier tests priced a one-million-token prompt at the standard rate. The code was right (a prompt that long is far over the 100,000-token threshold and costs $0.50 per million on the long card) and the test expectation was wrong; the tests now stay on one card per case and state the long-card figures separately.
- `Decimal` printed the same amount with different trailing zeros depending on how it was summed, so stored money uses one canonical text form.
- Local refusals are not recorded as calls (see the AD-067 note).
- Six properties were broken on purpose to check the tests catch them: the strict "greater than" threshold, cache tokens counting toward prompt length, the long card being used at all, cache writes priced at their own rate, the worst case using the larger of the input and cache-write rates, and local refusals staying out of the ledger. Each made at least one test fail.
- No paid call has been made, so none of this has been compared to a real invoice. The first real Haiku run (P47) is where the ledger total should be compared with the provider's usage page.
