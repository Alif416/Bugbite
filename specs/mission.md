# Mission

**Bugbite takes a GitHub issue, fixes it in a sandbox, and brings back a PR with proof.**

## Purpose

Maintainers have more small, well-described bugs than time. Bugbite works like a junior developer: it understands the issue, finds the code, reproduces the bug with a failing test, fixes it, verifies the fix, and opens a pull request a human can review quickly.

It is not an "LLM call and hope" demo. It proves its work with real test output and says honestly when it could not fix something.

## Users

| User | Wants |
|---|---|
| Maintainer | Fewer small bugs in the backlog; PRs that are easy to review and trust |
| Contributor | A quick first draft of a fix to improve on |
| Project owner | A measurable, benchmarked system to show in interviews and on a resume |

## Principles (the constitution)

1. **Evidence over opinion.** PR text is built from collected test output, never written freely by the model.
2. **Honesty over success.** Failures, low confidence, and flagged results are reported plainly. If nothing useful was produced, no PR is opened.
3. **Enforce in code, not in prompts.** Cheating guards, caps, and sandbox rules are code. The model cannot talk its way past them.
4. **Sandbox always.** Untrusted code runs only in Docker. Keys and host access never reach the agent or container.
5. **Model-agnostic.** The model and provider are config values behind an adapter. No model name is hard coded in the agent.
6. **Budget is a hard limit.** Total API spend is 5 USD. Caps stop runs, not the credit card. Develop on free models first.
7. **Reproducible.** Every run is recorded (model, prompt version, config, commit hash) and can be replayed deterministically at no API cost.
8. **Measured claims only.** Report raw counts ("7 of 25"), state the subset size, and never claim a general SWE-bench score.
9. **Transparent.** Every PR states it is AI generated and shows its evidence.
10. **Minimal edits.** Smallest patch that fixes the bug. No unrelated changes.
11. **Flat UI.** The dashboard uses solid colors only. No gradients.

## Scope (version 1)

**In:** Python repos with an existing test suite; issue URL + repo URL input; Docker sandbox; branch/commit/PR creation; evidence-based PR description; SWE-bench Lite evaluation on a fixed 20–30 issue subset; web dashboard; batch CLI; model adapter and one-by-one model comparison; record and replay; cheating guards; failure analysis; GitHub label trigger on owner-controlled repos; demo video and write-up.

**Out:** other languages; repos without tests; feature requests and large refactors; auto-merging PRs; third-party repos without permission; multi-repo changes.

## Success

- Resolve rate on the fixed subset clearly beats the simple-loop baseline (raw counts reported).
- Cost per issue stays under 0.10 USD; total spend under 5 USD.
- Zero regressions in PRs marked "solved".
- 100% of unsolved runs carry a failure label.
- Every experiment is repeatable through replay.
- Full acceptance checklist: README section 10.

## Stakeholder decisions already made

Web dashboard plus batch CLI; Haiku default with comparison against other models; free models allowed for dev and comparison; 5 USD budget; Python only.

## Open questions (owner to answer)

1. Sandbox repos for the live demo?
2. Which 20–30 SWE-bench Lite instances? (Suggest fast-installing repos with fast tests.)
3. Where is the demo hosted: local or free tier?
4. Which free models, and is there a GPU or enough RAM for a local one?
5. Is a stronger paid model wanted, and can the budget rise if needed?
6. Is a custom set of ~25 small Python bugs acceptable if Haiku solves almost nothing on SWE-bench Lite?
