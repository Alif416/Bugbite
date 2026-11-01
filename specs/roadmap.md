# Roadmap

High-level implementation order in very small phases. Each phase ends with something runnable or testable. Build the agent and evals first, dashboard second. Develop on free models; spend on Haiku only at the marked points. Do not cut replay or cheating guards.

FR numbers refer to README.md section 5.

## Foundation

- [x] **P1. Project skeleton** — repo layout, module folders, pytest runs, config loading, CI stub.
- [ ] **P2. Input validation** — parse issue URL + repo URL offline; reject non-GitHub and malformed input with clear messages (FR1.1). Python-only check moved to P3 (AD-011).
- [ ] **P3. Issue fetch** — title, body, labels, comments via GitHub API; public/token access check; reject non-Python repos (FR1.2, FR1.3, FR1.4).
- [ ] **P4. Sandbox: run a command** — start a limited Docker container, run one command, clean up (FR2.1, FR2.3, FR2.4, FR2.5).
- [ ] **P5. Sandbox: clone + install** — clone repo, auto-install from requirements/setup/pyproject (FR2.2).
- [ ] **P6. Sandbox: run tests** — run pytest in the container, parse pass/fail/skip per test.
- [ ] **P7. Orphan-proof cleanup** — crashed jobs leave no containers; test it (reliability).

## Model adapter

- [ ] **P8. Adapter interface + model config file** (FR14.1, FR14.3).
- [ ] **P9. OpenAI-compatible adapter** — working against a free model (Ollama or free tier) (FR14.2).
- [ ] **P10. Claude adapter** — Haiku, prompt caching on (FR14.2).
- [ ] **P11. Usage and cost tracking per call** — free models log cost 0 (FR14.6).
- [ ] **P12. Text action fallback** — JSON action parse, validate, one repair attempt (FR14.4).
- [ ] **P13. Privacy gate** — private code blocked for providers not marked allowed (FR14.9).

## Agent loop

- [ ] **P14. Tools** — `read_file`, `list_directory`, `search_code` (grep) in the sandbox (FR5.2).
- [ ] **P15. Tools** — `edit_file`, `run_tests`, `run_command` (FR5.2).
- [ ] **P16. Minimal loop** — think, call tool, read result, repeat; no caps yet (FR5.3).
- [ ] **P17. Hard caps** — max steps, cost, wall-clock; tested (FR5.4).
- [ ] **P18. Loop detection** — repeated failed edits change strategy or stop (FR5.5).
- [ ] **P19. Cheap pre-steps** — parse tracebacks/paths from issue, run named failing test, feed as context; log token savings (FR5.7).
- [ ] **P20. First end-to-end fix** — one hand-picked issue, free model, patch printed locally (no PR yet).

## Trace and record/replay (early, so everything after is cheap to test)

- [ ] **P21. Trace store** — save every model call, tool call, result, tokens, cost, time to Postgres (FR8.1).
- [ ] **P22. Recorder** — structured on-disk recording with model, prompt version, config, commit hash (FR10.1, FR10.4).
- [ ] **P23. Replayer** — deterministic offline replay; same recording twice gives same result (FR10.2, FR10.5).
- [ ] **P24. Replay works for both adapters** (FR14.7).

## Retrieval and reproduction

- [ ] **P25. File tree + symbol index** with `ast` (FR3.1).
- [ ] **P26. Candidate file ranking with reasons**, small context only (FR3.3, FR3.4).
- [ ] **P27. Embeddings search** — Chroma index + `semantic_search` (FR3.2).
- [ ] **P28. Context trimming** — drop old tool output first for small-window models (FR14.8).
- [ ] **P29. Reproduction step** — agent writes a failing test (FR4.1).
- [ ] **P30. Reproduction check** — confirm it fails for the right reason; retry limit; low-confidence flag on give-up (FR4.2, FR4.3).

## Verifier and guards

- [ ] **P31. Baseline test run** before the fix; store results (FR6.2).
- [ ] **P32. Post-fix verification** — repro test passes, full suite compared to baseline, regressions detected (FR6.1–6.3).
- [ ] **P33. Verifier-owned repro check** — fails on original code, passes on fixed code, checked outside the agent (FR6.5).
- [ ] **P34. Guard: protect existing tests** — block edits/deletes of existing test files.
- [ ] **P35. Guard: no skip/xfail/mark hiding.**
- [ ] **P36. Guard: patch size cap.**
- [ ] **P37. Guard: no test config / CI / dependency-pin changes** unless the issue is about them.
- [ ] **P38. Guard unit tests** — at least 5 cheating attempts (edit tests, add skips, oversized patch) (acceptance).
- [ ] **P39. Linter/formatter run** if configured (FR6.4).
- [ ] **P40. Status + confidence** — solved / partially solved / failed / aborted; any violation never "solved" (FR8.3).

## Pull requests

- [ ] **P41. Branch, commit, push** to a sandbox repo (FR7.1).
- [ ] **P42. PR evidence builder** — description assembled from collected output only, with AI-generated notice (FR7.3).
- [ ] **P43. Open PR via API** (FR7.2).
- [ ] **P44. Draft PR + failure report logic** — "partially solved" draft; no PR when nothing useful (FR7.4, FR7.5).
- [ ] **P45. CLI single job** — `bugbite fix <issue> <repo>` end to end.

## Spend control and Haiku spike

- [ ] **P46. Spend counter + per-issue, per-batch, per-model caps** enforced in code.
- [ ] **P47. Haiku spike (~0.50 USD)** — 3 easy issues, learn real cost per issue.

## Evaluation

- [ ] **P48. Choose and freeze the SWE-bench Lite subset** (20–30) — answer open question 2; commit the list.
- [ ] **P49. Eval runner** — one instance at a time, official SWE-bench scoring (FR9.2).
- [ ] **P50. Parallel workers** with a worker limit (FR9.1).
- [ ] **P51. Rate limits, backoff, queue, resume without repeating finished issues** (FR14.5).
- [ ] **P52. Report v1** — resolve rate (raw counts), cost per issue, cost per resolved issue, avg steps (FR9.3).
- [ ] **P53. Result storage + A/B compare** on the same subset (FR9.4, FR9.5).
- [ ] **P54. Failure classifier** — rule-based labels from the trace, one primary label each (FR11.1, FR11.2).
- [ ] **P55. Failure table** in the report with top-two-causes comment (FR11.3).
- [ ] **P56. Baseline run** — simple loop on the full subset (Haiku, ≈ part of 2.50 USD).

## Experiments (replay where possible)

- [ ] **P57. Reproduce-first on/off.**
- [ ] **P58. Retrieval: grep+tree vs +embeddings.**
- [ ] **P59. Prompt caching on/off** (cost).
- [ ] **P60. Loop detection and step-cap tuning.**
- [ ] **P61. Pre-step token savings** measured and reported.

## Model comparison

- [ ] **P62. Run harness per model**, results stored under model name (FR13.1).
- [ ] **P63. Free model full-subset run(s)**; record integration method and hardware/tier (FR13.8, FR13.9).
- [ ] **P64. Comparison report** — solved counts, cost per issue, cost per solved issue, steps, time, failure labels, guard triggers (FR13.5, FR13.7).
- [ ] **P65. Optional stronger model** — 2-issue cost probe, project total, stop if over budget, then ~10 issues (FR13.4). Skip if it does not fit.

## Dashboard (keep it simple)

Design rule for every UI phase below: flat, solid colors only, **no gradients** (stakeholder input). See `tech-stack.md`.

- [ ] **P66. API endpoints** — submit job, job status, trace, results.
- [ ] **P67. React: submit job page.**
- [ ] **P68. React: live job progress.**
- [ ] **P69. React: trace and cost view.**
- [ ] **P70. React: PR evidence preview.**
- [ ] **P71. React: eval results page with spend counter vs 5 USD** (FR8.4).
- [ ] **P72. React: model comparison page** — table, simple chart, spend per model (FR13.6).

## Trigger, demo, and wrap-up

- [ ] **P73. Docker Compose** to run everything locally.
- [ ] **P74. GitHub label trigger** (`ai-fix`) with owner allow list and issue comment (FR12). *Cut first if time runs short.*
- [ ] **P75. Live demo on a sandbox repo** — answer open question 1.
- [ ] **P76. Manual check of PR evidence accuracy** (30 PRs where available) and hand-check of eval failure labels.
- [ ] **P77. README** — architecture diagram, setup, results table, limitations and failure analysis.
- [ ] **P78. Architecture doc with tradeoffs; final eval report.**
- [ ] **P79. Demo video (2–3 min) and write-up.** *Polish is cut second.*
- [ ] **P80. Resume bullets** filled with real numbers only.

## Rough timeline (from README milestones)

| Week | Phases |
|---|---|
| 1 | P1–P7 |
| 2 | P8–P20 |
| 3 | P21–P30 |
| 4 | P31–P45 |
| 5 | P46–P56 |
| 6 | P57–P72 |
| 7 | P73–P80 |
