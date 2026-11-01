# Bugbite

An autonomous issue-fixing agent that opens evidence-backed pull requests.

Tagline: Bugbite takes a GitHub issue, fixes it in a sandbox, and brings back a PR with proof.

Requirements document, written from the stakeholder side.

## 1. Background

Open source maintainers and engineering teams get more issues than they can fix. A large share of them are small, well described bugs that a developer could fix in an hour, but they sit in the backlog for weeks. We want a system that takes one of these issues, works on it like a junior developer, and hands back a pull request that a human can review quickly.

We do not want a demo that "calls an LLM and hopes". We want a system that proves its work with real test output, and that tells us honestly when it could not fix something.

## 2. Goal

Given a GitHub issue and a repository link, the system must:

1. Understand the issue.
2. Find the relevant code.
3. Reproduce the bug with a failing test.
4. Fix it.
5. Verify the fix with tests.
6. Open a pull request with an evidence-based description.

## 3. Users

| User | What they want |
|---|---|
| Maintainer | Fewer small bugs in the backlog, PRs that are easy to review and trust |
| Contributor | A quick first draft of a fix that they can improve |
| Developer (project owner) | A measurable, benchmarked system to show in interviews and on a resume |

## 4. Scope

### In scope

- Python repositories with an existing test suite (first version)
- Input: GitHub issue URL plus repository URL (or issue text plus repo URL)
- Sandboxed code execution
- Automatic branch creation, commit, and pull request
- Evidence-based PR description
- Benchmark evaluation on SWE-bench Lite
- A web dashboard to submit jobs, watch progress, and view traces and results
- A CLI for batch evaluation runs
- Claude Haiku as the default model, with the model set by config so other models can be swapped in
- A model adapter so any model behind a Claude or OpenAI-compatible API can be used (Claude, Ollama, Groq, OpenRouter, vLLM)
- A one by one model comparison (Haiku, one or two free models, and optionally one stronger paid model) on the same issues, same tools, and same limits
- Free models for development and comparison, so the 5 USD is spent on Haiku eval runs
- Total API budget is 5 USD unless the owner raises it (see section 6 and section 16)
- Record and replay of agent runs so experiments can be repeated without API cost
- Guards that stop the agent from "passing" by cheating
- Failure analysis of every unsolved issue
- A GitHub trigger (label or Action) that works on repositories the owner controls
- A short demo video and a write-up

### Out of scope for version 1

- Languages other than Python
- Repositories with no tests
- Feature requests and large refactors (bug fixes only)
- Merging PRs automatically
- Running on third party repos without the owner's permission
- Multi-repo changes

## 5. Functional Requirements

### FR1. Input handling
- FR1.1 Accept a GitHub issue URL and repo URL through the web dashboard and a CLI command.
- FR1.4 Accept Python repositories only. Reject anything else with a clear message.
- FR1.2 Fetch the issue title, body, labels, and comments through the GitHub API.
- FR1.3 Validate that the repo is public or accessible with the given token, and reject unsupported repos with a clear message.

### FR2. Sandbox
- FR2.1 Clone the repo into an isolated Docker container.
- FR2.2 Install dependencies automatically (requirements files, setup files, pyproject).
- FR2.3 Run all agent code and tests only inside the container.
- FR2.4 Enforce limits: CPU, memory, run time per command, and no access to the host or to secrets.
- FR2.5 Clean up the container after each job.

### FR3. Code understanding and retrieval
- FR3.1 Build a file tree and a symbol index (functions, classes) for the repo.
- FR3.2 Support text search (grep style) and semantic search (embeddings).
- FR3.3 Rank candidate files for the issue and show why they were chosen.
- FR3.4 Keep the context sent to the model small. It must never dump the whole repo into a prompt.

### FR4. Bug reproduction
- FR4.1 Write a test that fails because of the reported bug.
- FR4.2 Confirm the test fails for the right reason, not because of a syntax error or a missing import.
- FR4.3 If reproduction fails after a set number of attempts, continue with a warning flag and lower the confidence level.

### FR5. Fix generation (agent loop)
- FR5.1 The agent talks to models only through the model adapter (FR14). The model and provider are config values, Haiku is the default, and no model or provider name is hard coded anywhere in the agent.
- FR5.2 Tools available: `read_file`, `search_code`, `edit_file`, `run_tests`, `run_command`, `list_directory`.
- FR5.3 The agent loops: think, call a tool, read the result, decide the next step.
- FR5.4 Hard limits per job: maximum steps, maximum cost in dollars, maximum wall clock time.
- FR5.5 Detect loops, such as repeating the same failed edit, and change strategy or stop.
- FR5.6 Keep edits minimal. No unrelated formatting changes or file rewrites.
- FR5.7 Do cheap work in plain code before calling the model: parse tracebacks and file paths from the issue text, run the named failing test directly if one is mentioned, and pass the results to the model as context. Measure how much this lowers token use and cost.

### FR6. Verification
- FR6.1 Run the new reproduction test and confirm it passes.
- FR6.2 Run the full existing test suite and compare against a baseline run taken before the fix.
- FR6.3 Report any test that passed before and fails now as a regression, and block a "success" status.
- FR6.4 Run the project's linter or formatter if one is configured.
- FR6.5 Cheating guards. The agent must not be able to fake a pass. Enforce all of these in code, not in the prompt:
  - Existing test files cannot be edited or deleted. Only new test files may be added.
  - No skip, xfail, or mark changes that hide failures.
  - Patch size is capped (for example, a maximum number of changed lines and files). Larger patches are flagged for review.
  - No changes to test configuration, CI files, or dependency pins unless the issue is about them.
  - The reproduction test must fail on the original code and pass on the fixed code, checked by the verifier and not by the agent.
  - Any violation downgrades the result to "failed" or "flagged", never "solved".

### FR7. Pull request creation
- FR7.1 Create a new branch, commit the changes with a clear message, and push it.
- FR7.2 Open a PR through the GitHub API.
- FR7.3 The PR description must be built from real evidence collected during the run, not written freely by the model:
  - Issue summary
  - Root cause explanation
  - What changed and why
  - Test failing before the fix (output)
  - Test passing after the fix (output)
  - Full suite results (passed, failed, skipped, compared with baseline)
  - Confidence level (high, medium, low)
  - Known limitations
- FR7.4 If verification fails or confidence is low, open a draft PR labelled "partially solved" with an honest explanation.
- FR7.5 If nothing useful was produced, do not open a PR. Return a failure report instead.

### FR8. Observability
- FR8.1 Save a full trace for every job: each model call, tool call, result, token count, cost, and time.
- FR8.2 Show the trace in the web dashboard so a human can see how the agent reached its fix.
- FR8.4 The dashboard has these views: submit a job, live job progress, job trace and cost, PR evidence preview, and an eval results page with a running spend counter against the 5 USD budget.
- FR8.5 The dashboard must not use gradient colors. Use flat, solid colors only, including in charts, buttons, cards, and headers.
- FR8.3 Record a final status: solved, partially solved, failed, or aborted (with the reason).

### FR9. Evaluation harness
- FR9.1 Run the agent on a small fixed subset of SWE-bench Lite instances (20 to 30, chosen once and never changed) in batch, in parallel with a worker limit.
- FR9.2 Score each instance with the official SWE-bench test criteria.
- FR9.3 Produce a report with resolve rate, average cost per issue, average cost per resolved issue, average steps, and failure categories.
- FR9.4 Support A/B runs so any change can be compared against the baseline on the same subset.
- FR9.5 Store results for every run so progress over time is visible.

### FR10. Record and replay
- FR10.1 Record every model response, tool call, and tool result of a run to disk in a structured format.
- FR10.2 Provide a replay mode that re-executes a recorded run with no API calls, using the saved model responses.
- FR10.3 Use replay for dashboard development, regression tests of the pipeline, and re-scoring old runs after verifier changes.
- FR10.4 Every recorded run stores the model name, prompt version, config, and agent commit hash, so a replay is traceable.
- FR10.5 Replay must be deterministic. Running the same recording twice gives the same result.

### FR11. Failure analysis
- FR11.1 Every unsolved or flagged run gets exactly one primary failure label:
  - wrong file found (retrieval miss)
  - bad or missing reproduction test
  - wrong fix (test fails after the edit)
  - fix breaks other tests (regression)
  - environment or dependency setup failed
  - hit the step, cost, or time cap
  - agent loop detected
  - cheating guard triggered
- FR11.2 Labels are assigned by rules from the trace where possible, and checked by hand for the eval subset.
- FR11.3 The eval report includes a failure table with counts and a short comment on the top two causes and what could fix them.

### FR12. GitHub trigger (owner controlled repos only)
- FR12.1 A GitHub Action or webhook starts a job when an issue gets a label such as `ai-fix`.
- FR12.2 The trigger only works on repositories listed in an allow list controlled by the owner.
- FR12.3 The job comments on the issue with a link to the PR or the failure report.
- FR12.4 Spend caps and all safety rules still apply to triggered jobs.

### FR13. Model comparison
- FR13.1 The harness can run the same eval subset with any configured model, one model at a time, and store each run under the model name.
- FR13.2 For a fair comparison, everything except the model stays identical: same issues, same prompts, same tools, same step, cost, and time caps, same temperature, same verifier and guards.
- FR13.3 Models to compare: Haiku (paid, main model), one or two free models (a local open-weight model such as a Qwen coder model through Ollama, and/or a free hosted API tier), and optionally one stronger paid model. Haiku and the free models run on the full fixed subset. The optional stronger paid model runs on a smaller shared subset (about 10 issues taken from the same fixed subset).
- FR13.4 Before any paid model runs on the comparison subset, run it on 2 issues, measure the real cost per issue, and project the total. Stop if the projection goes over the remaining budget. Free models skip this step but are still subject to rate limits and time limits.
- FR13.5 The comparison report shows, per model: issues solved (raw count out of N), cost per issue, cost per solved issue, average steps, average time, failure label counts, and cheating guard triggers.
- FR13.6 The dashboard has a model comparison page with a table and a simple chart, and the spend counter shows spend per model.
- FR13.7 Findings are written in plain words, for example "Haiku solved 4 of 10, the stronger model solved 6 of 10, at 3.2 times the cost per issue". No general claims about the models beyond the tested subset.
- FR13.8 Report the integration method for every model (native tool calling or the text action fallback from FR14.4), because it can change results and is a known confounder.
- FR13.9 Report the hardware or tier used for free models (for example "7B model, quantized, local GPU" or "free API tier, rate limited"), since it affects speed and results.

### FR14. Model adapter
- FR14.1 One adapter interface for all models. Input: messages, tool definitions, and config. Output: normalized text, tool calls, token usage, and stop reason.
- FR14.2 Two adapters at minimum: a Claude adapter and an OpenAI-compatible adapter (covers Ollama, Groq, OpenRouter, vLLM, and similar).
- FR14.3 A model config file lists, per model: provider, base URL, model name, context window, native tool call support (yes or no), price per token (0 for free models), per issue cap, and whether it may receive private code.
- FR14.4 Text action fallback: for models without reliable native tool calling, the model writes one JSON action per turn and the adapter parses and validates it. Invalid output gets one repair attempt, then counts as a failed step.
- FR14.5 Rate limit handling: respect provider limits, retry with exponential backoff, queue requests, and resume a batch after interruption without repeating finished issues.
- FR14.6 Usage and cost are tracked per call for every model. Free models log tokens and time with cost set to 0.
- FR14.7 Record and replay (FR10) works for every adapter.
- FR14.8 Context handling: when a model has a small context window, the agent trims context using retrieval results and drops old tool output first, without failing the run.
- FR14.9 Privacy rule: free hosted tiers may use prompts for training, so they only receive public repos and sandbox issues. Private code only goes to local models or providers marked as allowed in the config.

## 6. Non-Functional Requirements

| Area | Requirement |
|---|---|
| Safety | Never run untrusted code outside the sandbox. Never expose API keys to the agent or the container. |
| Cost | Total project budget is 5 USD, Haiku is the default paid model. Free models cost 0 but still have time and step limits. Hard cap per issue (default 0.10 USD for Haiku, set per model) and per batch, plus a separate spend cap per model. Stop automatically when a cap is reached. Prompt caching is on for Claude models from day one. |
| Provider limits | Free tiers have request and daily limits. The harness must back off, queue, and resume without losing finished work. |
| Performance | Median job finishes in under 10 minutes. Batch runs can use parallel workers. |
| Reliability | Retry on API rate limits and network errors. A crashed job must not leave orphan containers. |
| Reproducibility | Every eval run records model name, prompt version, config, and commit hash of the agent. |
| Security | Tokens stored in environment variables or a secrets manager, never in code or logs. |
| Maintainability | Clear module boundaries (sandbox, retrieval, agent, verifier, PR writer, evals) with unit tests. |
| Transparency | Every PR states clearly that it was AI generated and shows its evidence. |

## 7. Suggested Architecture

```
Issue + Repo URL
      |
      v
 [Job Manager] ---> [Docker Sandbox]
      |                    |
      v                    v
 [Retrieval]  --->  [Agent Loop (Claude + tools)]
 (index, search)           |
                           v
                    [Verifier]
          (repro test, full suite, linter)
                           |
                           v
                    [PR Writer] ---> GitHub PR (or draft)
                           |
                           v
                    [Trace Store + Dashboard]
```

Cross-cutting: a recorder wraps every model and tool call so any run can be replayed offline, and a failure classifier labels every unsolved run.

## 8. Tech Stack

- Language: Python 3.11 or newer
- API layer: FastAPI
- LLM: model chosen by config through the model adapter. Haiku (Claude API with tool use) is the default paid model
- Free models: Ollama or llama.cpp for local open-weight coder models, and free hosted API tiers (for example Groq, OpenRouter, Google Gemini, GitHub Models). Check each provider's current limits and terms before relying on it
- Adapter protocol: OpenAI-compatible chat API for most non-Claude models
- Sandbox: Docker (Docker SDK for Python)
- Retrieval: tree-sitter or `ast` for symbols, a vector store (Chroma or pgvector), plus ripgrep
- Database: PostgreSQL for jobs, traces, and eval results
- Queue: Redis (job queue and rate limiting)
- GitHub: REST API through PyGithub or direct HTTP
- Frontend: React dashboard (job submission, live progress, traces, eval results, spend counter)
- Testing: pytest
- CI: GitHub Actions

## 9. Success Metrics

These are targets to aim for, not promises. Final numbers must come from real runs.

| Metric | Baseline (simple loop) | Target |
|---|---|---|
| Resolve rate on a fixed SWE-bench Lite subset (20 to 30 issues) | measure first | clear improvement over baseline, reported with the subset size |
| Cost per resolved issue | measure first | reduce by 40% or more, stay under 0.10 USD per issue |
| Total API spend for the whole project | n/a | under 5 USD (or the raised budget if the owner changes it) |
| Model comparison (Haiku versus at least one free model, same issues, optionally one stronger paid model) | n/a | a table with solved count, cost per issue, cost per solved issue, and integration method for each model |
| Token reduction from plain code pre-steps (traceback parsing, direct test run) | measure first | report the percentage saved |
| Runs where the cheating guards triggered | n/a | report the count and what the agent tried |
| Unsolved runs with a failure label | n/a | 100% |
| Experiments re-run through replay at 0 API cost | n/a | all of them where possible |
| Regressions introduced by "solved" PRs | measure first | 0 on the benchmark |
| PRs with accurate evidence (manual check of 30 PRs) | n/a | 100% |
| Median time per issue | measure first | under 10 minutes |

Important: with a 25 issue subset, one extra solved issue moves the rate by about 4 points. Always report the raw count (for example "7 of 25"), never only the percentage, and do not claim a general SWE-bench score. Say "on a fixed 25 issue subset of SWE-bench Lite".

Planned experiments that should each produce a before and after number (pick the cheapest ones first, since the budget allows only a few full runs):

1. Reproduce-first step on or off
2. Retrieval strategy: grep and file tree only versus adding embeddings
3. Prompt caching on or off (measured on cost)
4. Loop detection and step cap tuning

Budget plan for the 5 USD:

- 0 USD for development and debugging: build and test the agent loop on a free model
- About 0.50 USD for a week 1 spike: Haiku on 3 easy issues, to learn the real cost per issue
- About 2.50 USD for Haiku eval runs on the full fixed subset (baseline plus one or two experiments)
- 0 USD for free model comparison runs (limited by time and rate limits, not money)
- About 1.50 USD optional, for a stronger paid model on about 10 issues, only if the measured cost per issue allows it (FR13.4)
- About 0.50 USD kept as a reserve

Free models let the comparison cover more models without touching the budget. If the optional stronger paid model does not fit, drop it and say so in the report.

Cost saving rules: cache the system prompt and repo context, send only the relevant file snippets, keep the step cap low, and develop against failing tests locally before spending API money. If the budget runs out, the dashboard spend counter and the hard cap must stop the run, not the credit card.

## 10. Acceptance Criteria

The project is accepted when all of these are true:

- [ ] A user can submit an issue URL and repo URL and receive either a PR, a draft PR, or a failure report.
- [ ] Every PR description contains real before and after test output.
- [ ] No PR is marked solved if the full suite shows a regression.
- [ ] Jobs never run code outside the sandbox.
- [ ] Cost and step limits are enforced and tested.
- [ ] The eval harness runs a batch on the fixed SWE-bench Lite subset and produces a report with raw counts.
- [ ] At least two experiments are documented with before and after numbers.
- [ ] The web dashboard works end to end: submit a job, watch progress, view the trace, view the PR evidence.
- [ ] Total API spend stays under 5 USD and the dashboard shows it.
- [ ] Any recorded run can be replayed offline with no API calls and gives the same result.
- [ ] Cheating guards are tested with at least 5 unit tests that try to edit tests, add skips, and submit oversized patches.
- [ ] The eval report has a failure analysis table with labels and counts.
- [ ] The GitHub label trigger works on at least one repository the owner controls.
- [ ] A demo video (2 to 3 minutes) and a short write-up are published.
- [ ] The model and provider are config values behind a model adapter, with at least a Claude adapter and an OpenAI-compatible adapter working.
- [ ] The same eval subset has been run with Haiku and at least one free model under identical settings, and the report states how each model was integrated and on what hardware or tier.
- [ ] A batch run interrupted by a rate limit resumes without repeating finished issues.
- [ ] Private code is never sent to a provider that is not marked as allowed in the model config.
- [ ] The comparison report and dashboard page show solved count, cost per issue, cost per solved issue, steps, time, and failure labels for each model.
- [ ] A live demo exists on a sandbox repo that the owner controls.
- [ ] The README contains the architecture diagram, setup steps, results table, and a "limitations and failure analysis" section.

## 11. Risks and Honest Notes

| Risk | Mitigation |
|---|---|
| Low resolve rate, as is common for this task | Focus the story on measured improvement, not on perfection |
| High API cost during evals (budget is only 5 USD) | Haiku only, tiny fixed subset, aggressive caching, low step cap, hard spend cap enforced in code |
| Haiku is weaker than larger models, so the resolve rate will be low | Accept it, report it honestly, and focus the story on measured improvement and on the engineering around the model |
| Free models hit rate limits and batch runs take hours | Backoff, queue, and resume support (FR14.5), run overnight, and use a local model when possible |
| Free models handle tool calling badly | Text action fallback with validation and one repair attempt (FR14.4), and report the integration method |
| Free models send prompts to a provider that may train on them | Public repos and sandbox issues only for free hosted tiers, private code only for local or allowed providers (FR14.9) |
| Local models need a GPU or lots of RAM that the owner may not have | Use a small quantized model locally, or a free hosted tier, and report the hardware used |
| Free model limits and terms change without notice | Record the date and terms used for each run in the report |
| Stronger paid model costs too much to finish the comparison | Measure on 2 issues first (FR13.4), shrink the comparison subset, or raise the budget |
| Comparison is unfair because prompts or tools were tuned for Haiku | Keep prompts and tools identical across models, and say in the report that they were developed on Haiku |
| A comparison on about 10 issues proves little | Report raw counts, say the sample is small, and treat results as indicative only |
| Agent games the tests instead of fixing the bug (reward hacking) | Cheating guards enforced in code, verifier checks the reproduction test on original and fixed code |
| Replay recordings go stale after prompt or tool changes | Store prompt version and agent commit hash with each recording, and re-record only when the change matters |
| GitHub trigger is abused or hits the wrong repo | Allow list of owner controlled repos, spend caps still apply |
| Small subset gives noisy results | Report raw counts, state the subset size, do not overclaim |
| Dashboard takes time away from the core agent | Build the agent and evals first, dashboard second, keep it simple |
| Agent loops forever | Step, cost, and time limits plus loop detection |
| Model claims success without proof | PR text is generated from collected test output, not from model opinion |
| Environment setup fails on many repos | Start with a short list of repos that install cleanly, and log setup failures as their own category |
| Maintainers dislike AI PRs | Test only on own forks and sandbox repos, never open PRs on third party projects without permission |
| Benchmark contamination or leakage | Document the model used and do not tune prompts on the final test subset |

## 12. Milestones (about 7 weeks)

| Week | Deliverable |
|---|---|
| 1 | Sandbox, repo cloning, test running, GitHub issue fetching |
| 2 | Model adapter (Claude plus OpenAI-compatible), basic agent loop with tools, built and debugged on a free model, runs end to end on one hand picked issue |
| 3 | Retrieval (file tree, symbols, grep, embeddings), reproduction test step |
| 4 | Verification against baseline, cheating guards, PR writer with evidence, draft PR logic |
| 5 | Record and replay, eval harness on the fixed subset, trace store, spend cap, first baseline numbers |
| 6 | Web dashboard (submit, progress, traces, eval results, spend counter), failure labelling, model comparison runs (Haiku, free models, optional stronger model) and comparison page |
| 7 | Experiments through replay where possible, GitHub label trigger, failure analysis table, final report, demo video, write-up |

If time runs short, cut in this order: GitHub trigger first, then the write-up polish. Do not cut replay or the cheating guards.

## 13. Deliverables

- Source code in a public GitHub repository
- This README plus an architecture document with tradeoffs
- Docker setup to run everything locally
- Eval report with the results table and failure analysis
- Live demo or a short recorded demo
- Three to five resume bullets backed by the measured numbers
- Failure analysis table in the final report
- Replay recordings for the eval runs (so results can be re-checked)
- Demo video (2 to 3 minutes) and a short blog post, for example "What I learned building an issue-fixing agent on a 5 dollar budget"

## 14. Resume Bullet Templates

Fill these in only with numbers from real runs:

- Built an autonomous agent on Claude Haiku that reads GitHub issues, reproduces bugs, fixes them in a Docker sandbox, and opens evidence-backed PRs; resolved **X of N** issues on a fixed SWE-bench Lite subset.
- Raised resolved issues from **A to B** (out of **N**) by adding a reproduction-test-first step and code retrieval.
- Cut cost per resolved issue by **X%** (to under **$0.0Y**) through prompt caching and a step cap, with a hard spend limit enforced in code.
- Shipped a web dashboard showing live job progress, full agent traces, and running API spend.
- Added cheating guards (test-edit blocking, skip detection, patch size caps) so a "solved" result cannot come from faked passes; guards caught **N** attempts in evals.
- Built deterministic record and replay for agent runs, which let me repeat **N** experiments at 0 API cost on a 5 USD budget.
- Labelled every failure by cause; the top cause was **X** (**Y%** of failures), which guided the next improvement.
- Cut tokens per issue by **X%** by parsing tracebacks and running the failing test in plain code before calling the model.
- Built a model adapter (Claude and OpenAI-compatible APIs) with a text-action fallback for models without tool calling, and benchmarked Haiku against **M** free open-weight and hosted models on the same **N** issues under identical limits: **A vs B vs C** solved, at **X** cost per solved issue.
- Designed verification that compares full test suite results against a pre-fix baseline, with **0** regressions across all PRs marked solved.

## 15. Decisions Made by the Owner

- Interface: web dashboard (plus a CLI for batch runs)
- Model: Claude Haiku as the default paid model, plus a one by one comparison against other models (requested by the owner)
- Free (unpaid) models are allowed and will be used for development and for the comparison
- Total API budget: 5 USD
- Language support: Python only
- UI style: no gradient colors anywhere in the dashboard, flat solid colors only (stakeholder input)

## 16. Open Questions for the Owner

1. Which sandbox repos will be used for the live demo?
2. Which 20 to 30 SWE-bench Lite instances go into the fixed subset? (Suggestion: pick ones from repos that install quickly and have fast test suites, to save time and money.)
3. Where will the dashboard and backend be hosted for the demo (local only, or a free tier host)?
4. Which free models should be compared (a local model through Ollama, a free hosted tier, or both), and does the owner have a GPU or enough RAM to run a local model?
5. Is a stronger paid model wanted at all, or is Haiku plus free models enough? If wanted, can the budget be raised above 5 USD if the spike shows it costs too much?
6. If Haiku solves almost nothing on SWE-bench Lite, is a custom set of about 25 small Python bugs acceptable as the fallback benchmark?
## 17. Development Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.11 is installed automatically).

```bash
uv sync                      # create .venv and install dependencies
uv run pytest                # run the test suite
cp .env.example .env         # then fill in secrets (never commit .env)
```

`GITHUB_TOKEN` is optional: public repos work without it (60 API requests per hour), and a token raises the limit and allows private repos. **Docker tests.** The sandbox tests need a running Docker daemon (Docker Desktop on macOS). If Docker is not reachable they are skipped with a visible reason. Run only them with `uv run pytest -m docker`, or skip them with `uv run pytest -m "not docker"`. The first run builds Bugbite's own sandbox image (`bugbite-sandbox:py3.11-1`, from `docker/sandbox.Dockerfile`) and pulls `hello-world`; this needs the internet and takes a few minutes. Tests marked `internet` also need access to pypi.org and github.com and are skipped when they are unreachable (`-m "not internet"` skips them explicitly). Rebuild the image after editing the Dockerfile by bumping the tag suffix in `src/bugbite/sandbox/image.py`. Sandbox limits are configured in the `sandbox:` section of `config/app.yaml`.

To run the opt-in live GitHub test: `BUGBITE_LIVE_TESTS=1 uv run pytest tests/github/test_live.py`.

Config lives in `config/`: `app.yaml` (limits, default model) and `models.yaml` (one entry per model). Secrets are read only from environment variables.

### How test results are captured

Tests run inside the sandbox with the repo's own pytest configuration. A small Bugbite plugin (`src/bugbite/sandbox/plugin/bugbite_report.py`) is copied into the container for every run, outside the repo, and records the exact ID and outcome of each test. `run_tests` returns one status per run:

| Status | Meaning |
|---|---|
| `ok` | pytest ran; tests passed or failed (see the per-test outcomes) |
| `no_tests` | collection worked and found nothing (repo is rejected by `ensure_has_tests`) |
| `collection_error` | import errors during collection, or pytest could not start (for example `addopts` names a plugin that is not installed); an environment problem |
| `timeout` | the run hit `test_timeout_s`; results for tests that finished are kept |
| `crashed` | internal error, plugin failed to load, report missing, or an unexpected exit code |

Per-test outcomes are `passed`, `failed`, `error`, `skipped`, `xfailed` and `xpassed`. Tests run with the network cut, so tests that need the internet fail; later baseline comparison treats tests that fail both before and after a fix as pre-existing. A test result is only as trustworthy as the code running inside pytest: the verifier (P33) re-checks in a clean container.

### Cleanup of sandboxes

A crashed or killed job must not leave containers behind. Three layers work together:

1. **Docker removes a sandbox itself** when it exits (it is created with auto-remove), including at the end of its `max_lifetime_s`, together with its workspace volume.
2. **`sweep_orphans()`** removes sandboxes whose owner process is gone, or that outlived their lifetime plus a 60-second grace period, and leftover labelled workspace volumes. It runs automatically before every sandbox start (a failure there never blocks a start) and can be called directly. It only touches objects labelled `bugbite.sandbox=1`, and never a sandbox whose owner is alive and within its lifetime.
3. **Exit hooks:** live sandboxes are closed on normal exit. Entry points (CLI, API) should also call `install_signal_cleanup()` once, from the main thread, so that SIGTERM and Ctrl-C close them too. It is never installed on import.

`kill -9` and power loss cannot be caught; those are covered by layers 1 and 2. To check by hand: `docker ps -a --filter label=bugbite.sandbox=1` and `docker volume ls --filter label=bugbite.sandbox=1`.

Workspace volumes created before this cleanup existed carry no label, so Bugbite cannot tell them from other programs' volumes and leaves them alone. List them with `docker volume ls -f dangling=true` and remove the ones that belong to Bugbite with `docker volume rm <name>`.

### Model adapter interface

All models are used through `bugbite.adapter`. A `GenerationRequest` (system prompt, messages made of text, tool-call and tool-result blocks, tool definitions, temperature) goes to `adapter.generate(request)`, which returns a `GenerationResponse` (text and tool calls, token usage, a normalised stop reason). The types are provider-neutral, immutable, and convert to JSON and back exactly, so recorded runs do not depend on any provider. Calls are synchronous and return whole responses.

- Every request is checked locally before anything is sent (alternating roles, every tool call answered by a tool result, unique ids and names, sane temperature), so a malformed conversation cannot cost money.
- Provider failures are raised as `AdapterError` with a stable code (`rate_limited`, `auth_failed`, `context_too_long`, `invalid_request`, `server_error`, `network_error`, `timeout`, `bad_response`). Adapters do not retry.
- Adapters are built with `create_adapter(model_config, api_key=...)`. The caller reads the environment variable named by `api_key_env` and passes the key in; local models need no key.
- `config/models.yaml` fields: `provider` (`claude` or `openai_compatible`), `base_url`, `model_name`, `context_window`, `max_output_tokens`, `native_tool_calling` (reported as the integration method, `native` or `text_action`), prices per token, `per_issue_cap_usd`, `allow_private_code`, `api_key_env`.
- `bugbite.adapter.testing.ScriptedAdapter` returns canned responses, so the agent loop and replay can be built and tested without a provider. `tests/adapter/adapter_contract.py` is the contract every real adapter must pass.

### Using an OpenAI-compatible model

`bugbite.adapter.OpenAICompatibleAdapter` talks to any server that offers the chat completions API (local or hosted). Add an entry to `config/models.yaml` with `provider: openai_compatible`, the server's `base_url` (including `/v1`), and `api_key_env` if it needs a key; `create_adapter(model, api_key=...)` builds it. It sends tools natively, so a model with `native_tool_calling: false` is refused when tools are sent (the text-action fallback is a later phase). The key is sent only in the `Authorization` header and redirects are not followed.

**Free hosted tiers (cautions).** The `groq-free` entry is a placeholder: every Groq-specific value in it is marked `confirm` and was taken from third-party pages on 2026-11-01. Before the first real run, read Groq's own pages for the current model list, tool-calling support, rate limits, and data terms, and note the date. Free tiers can have tight per-minute token limits and may use prompts for training, so only public repos are sent (`allow_private_code: false`).

**Live check (opt-in).** With a free key from console.groq.com:

```bash
BUGBITE_LIVE_TESTS=1 GROQ_API_KEY=... uv run pytest tests/adapter/test_live_openai_compatible.py -s
```

It makes two small calls and counts against the free tier's limits. It has not been run in this repository's history yet.

### Using a Claude model

`bugbite.adapter.ClaudeAdapter` calls Claude through the official `anthropic` SDK, with the SDK's own retries switched off (retry policy lives in one place, later). The default model is `haiku` in `config/models.yaml` (`claude-haiku-5-5`). The key must be passed in (`create_adapter(model, api_key=...)`); the adapter refuses to start without one and never reads the environment itself.

- **Prices (read from the official pages on 2026-11-01; re-check before each paid benchmark run):** Haiku 5.5 costs $0.10 per million input tokens and $0.50 per million output tokens for prompts up to 100,000 tokens, and $0.50 / $2.50 above that; cache hits cost $0.01 per million and 5-minute cache writes $0.125. An earlier placeholder in this repository ($1 and $5) was wrong. The higher tier and the cache prices are modelled in the cost-tracking phase; until then cost estimates ignore them.
- **Temperature:** `temperature` is optional (`None` means the provider's default). Claude Haiku 5.5 only accepts its default, so the Claude adapter rejects any other value instead of silently ignoring it, and model comparisons run all models at the default.
- **Thinking is off** for now, so no thinking blocks enter the conversation. Models that cannot run with thinking disabled fail with the API's own error until the thinking pass-through phase (P10b).
- **Prompt caching:** the `prompt_caching` setting in the model entry is `auto` (default: cache the growing conversation prefix and honour `cache` flags on text blocks), `explicit` (flags only), or `off`. At most four cache markers are sent per request. Read the effect from `cache_read_tokens` and `cache_write_tokens` in the usage.
- **Refusals:** a safety decline comes back as stop reason `refusal` (the category is kept in `raw_stop_reason`); Haiku 5.5 has no server-side fallback.
- **Live check (opt-in).** With a key from console.anthropic.com:

```bash
BUGBITE_LIVE_TESTS=1 ANTHROPIC_API_KEY=... uv run pytest tests/adapter/test_live_claude.py -s
```

It makes a few small calls (a fraction of a cent) and prints usage and cost. It has not been run in this repository's history yet.

### Model pricing and cost tracking

Each model in `config/models.yaml` has a `pricing` block in **US dollars per million tokens**: `input`, `output`, `cache_read`, `cache_write`, an optional `long_prompt` rate card (a call whose prompt is longer than `over_tokens` pays those rates for the whole call), and where the numbers came from (`as_of` date and `source`). Free models write explicit zeros. Paid models must state `as_of`, and Claude models must state their cache rates. Re-read the provider's pricing page and update `as_of` before every paid benchmark run; `pricing_is_stale()` reports prices older than 30 days.

A call's **prompt length** counts input, cache-read and cache-write tokens together, and that length chooses the rate card (a prompt of exactly the threshold is still standard). Cost is exact (`Decimal`), per kind of token. For example, on Haiku 5.5, 1000 input + 200 output + 5000 cache-read + 400 cache-write tokens cost exactly $0.0003.

To track cost, pass a ledger when creating an adapter:

```python
ledger = CostLedger()
adapter = create_adapter(model, api_key=key, ledger=ledger)   # every call is recorded
...
ledger.total_usd, ledger.by_model(), ledger.snapshot()        # exact totals; snapshot is JSON-safe
```

Failed calls that reached the provider are recorded with their error code and no cost; requests refused locally before anything was sent are not calls. The ledger only measures. Spend caps are enforced in later phases (agent loop and spend control); `adapter.worst_case_cost(request)` gives them the most the next call could cost. Estimated token counts (from servers that report none) are flagged. Free models log tokens and time with cost 0.

### Models without native tool calling (text-action fallback)

A model configured with `native_tool_calling: false` (most small local and free models) still gets tools: `create_adapter` wraps it in `TextActionAdapter`, so the agent loop sees the same interface as for any other model. The model is told, in an instruction block added to the system prompt (`PROMPT_VERSION` is recorded for reproducibility), to answer every turn with **one JSON action**:

```json
{"tool": "read_file", "arguments": {"path": "src/app.py"}}
{"final": "The bug was an off-by-one in parse(); fixed and tests pass."}
```

The wrapper finds the action in the reply (prose and code fences around it are ignored), checks the arguments against the tool's JSON Schema, and returns an ordinary tool call or text answer. A reply with no action, two different actions, broken JSON, an unknown tool, or invalid arguments gets **one repair attempt** that tells the model exactly what was wrong. If the repair also fails the step has failed: the response is a tool call named `invalid_action` with empty arguments and an `error`; the loop answers it with that error as the tool result and counts a failed step. Provider errors and refusals are never repaired.

For cost and failure analysis: every model call, including a repair, is its own ledger entry (create the adapter with a ledger), the response carries the summed tokens and time for the step, and `adapter.stats` gives the number of tool steps, repaired steps, and failed steps. `adapter.max_calls_per_step` is 2. The method costs extra tokens (the instruction block on every call, longer history), which shows up in the model comparison; the integration method is reported per model as `text_action`. It has not yet been tried against a real model.

### Privacy: private code and models

Private code may only go to a model whose `allow_private_code` is `true` in `config/models.yaml`. There is no flag, environment variable or argument that overrides this. Today `local-free` (runs on your machine) is `true`; `haiku` and `groq-free` are `false`. Whether a provider may see private code is your decision, made after reading its current data terms; change it by editing that one line.

**How a job's code is classified** (`bugbite.privacy.classify`), using the repository name and visibility GitHub returned:

| Class | When | Goes to |
|---|---|---|
| `sandbox` | the repo is in `sandbox_repos` in `config/app.yaml` (your demo and test repos; case-insensitive, whole `owner/name`) | any model |
| `public` | GitHub says the repo is public | any model |
| `private` | everything else, including unknown visibility | only models with `allow_private_code: true` |

`sandbox_repos` is unrelated to the Docker sandbox. It starts empty.

**Two locks, both always on:**

1. `check_job_privacy(model, context, sandbox_repos, models)` runs when a job starts. If the chosen model may not see the data it raises `PrivacyError` (`private_code_blocked`) before any work, names the model and repo, and lists the models that would be allowed. It never switches models for you.
2. `create_adapter(model, ..., sensitivity=...)` puts a `PrivacyGuardAdapter` directly around the real provider adapter, so every call is checked again just before the network. If you do not pass a sensitivity it assumes `private`. A refused call is not a model call: nothing is sent, nothing is billed or retried.

**For entry points (CLI, API, GitHub trigger):** fetch the issue, call `check_job_privacy`, then pass the returned sensitivity to `create_adapter`. Build adapters only through `create_adapter`; a test fails if code outside `src/bugbite/adapter/` imports a concrete adapter.

Not covered yet: private code stored in traces, recordings or the dashboard (later phases), and a remote endpoint wrongly marked `allow_private_code: true`.

### Agent tools (read-only)

The agent looks at the repository through three tools in `bugbite.agent.tools`. `build_read_only_tools(sandbox)` returns a `ToolRegistry`: `definitions()` gives the schemas to put in a model request (they work with native and text-action models), and `execute(name, arguments)` runs a call and returns a `ToolOutput(text, is_error)`; `.to_block(call_id)` turns it into the `ToolResultBlock` for the next turn. A bad call (unknown tool, wrong arguments, missing file, a tool crash) comes back as an error result for the model to react to and never raises. `TOOLS_VERSION` names the current tool text for recordings.

| Tool | Does | Limits |
|---|---|---|
| `read_file(path, start_line?, end_line?)` | numbered lines | 200 lines and 20,000 characters per call, then says which `start_line` to use next; binary files and files over 1 MB are refused |
| `list_directory(path?)` | one level, folders first (`/`), symlinks marked `@` | 200 entries, says how many were left out |
| `search_code(pattern, path?, glob?, regex?)` | `path:line:text`, plain text unless `regex` | 50 matches of at most 200 characters; skips `.git`, `node_modules`, virtualenvs, caches and binary files |

Paths are relative to the repo root. Absolute paths, `..` and `.git` are refused, and a symlink that leads outside the repo (or into `.git`) is refused too, because the path is resolved inside the container. Nothing is built into a shell string: model text only ever reaches the sandbox as a separate argument. These three tools change nothing. The numbers above are starting values, to be tuned with real runs.

### Agent tools (edit and run)

`build_agent_tools(sandbox)` returns the registry with all six tools: the three above plus the ones below. `TOOLS_VERSION` is "2".

| Tool | Does | Limits |
|---|---|---|
| `edit_file(path, new_text, old_text?)` | replaces `old_text` (which must match **exactly once**) with `new_text`; leave `old_text` out to create a new file | text files up to 1 MB; each text up to 20,000 characters; keeps line endings, the final newline and the file mode; shows the changed lines |
| `run_tests(targets?, keyword?)` | runs pytest and returns a summary: counts, up to 15 failing tests with a one-line reason, up to 5 collection errors, and the last 1,500 characters of output if anything failed | up to 20 targets; a timeout, crash or "no tests" is stated plainly |
| `run_command(command, timeout_s?)` | runs a shell command in the repo folder; returns the exit code and the first 3,000 and last 3,000 characters of output | the sandbox's command timeout; refuses to run if the sandbox has network access; the environment is a fixed `PATH` (the project's virtualenv first) |

**What the agent may not change (README FR6.5), enforced in `edit_file` in code:** existing test files (a `tests/`, `test/` or `testing/` folder, `test_*.py`, `*_test.py`), test configuration (`pytest.ini`, `tox.ini`, `setup.cfg`, `pyproject.toml`, `noxfile.py`, `.coveragerc`, `conftest.py`), CI files (`.github/`, `.gitlab-ci.yml`, `.circleci/`, ...) and dependency pins (`requirements*.txt`, lock files, `Pipfile`, `environment.yml`). New test files can be created, but not with skip, skipif or xfail. The same checks apply to the real file behind a symlink. If an issue really is about one of these files, the **calling code** passes `allowed_edit_paths=` to `build_agent_tools`; no tool argument can do it.

**Known gap:** `run_command` is a real shell inside the sandbox, so it can change a protected file (for example with `sed -i`) or tamper with the test report plugin, and the `edit_file` guards do not see that. They are a first line that keeps an honest model from wasting steps, not a proof. The defence is the verifier (P33 to P36): it must compare the final patch with the original commit, reject changes to protected files, and re-run the tests in a clean container. Until then a result from these tools must not be reported as verified.

### The agent loop

```python
from bugbite.agent import run_agent, format_issue_task, limits_from_config
from bugbite.agent.tools import build_agent_tools

limits = limits_from_config(app_config, model_config)   # steps, cost and time from the config
result = run_agent(adapter, build_agent_tools(sandbox), format_issue_task(context), limits=limits, ledger=ledger)
print(result.status, result.final_text)
```

`adapter` comes from `create_adapter(...)` (which applies the privacy gate and cost tracking); the caller runs `check_job_privacy` first. Each step is one model call with the system prompt (`PROMPT_VERSION`), the whole conversation so far and the tool definitions. Every tool call in a reply is run in order and the results go back in one message. The loop ends when the model replies with plain text and no tool call.

`limits` is required: see "Hard limits per job" below. The result's `status` says how the run ended:

| Status | Meaning |
|---|---|
| `finished` | the model gave a final answer. This is **not** proof that the bug is fixed; only the verifier (P33 to P36) can say that |
| `max_steps` | the step limit was reached; the last reply's tool calls were not run |
| `cost_cap` | the cost limit would be passed by the next step (or was passed); see below |
| `time_cap` | the wall-clock limit was reached |
| `truncated` | a reply hit the output token limit; its tool calls were not run, because they may be cut off mid-edit |
| `refused`, `empty_reply`, `unexpected_stop` | the model refused, said nothing, or stopped for an unknown reason |
| `model_error` | the model call failed (`error_code` holds the adapter code, such as `rate_limited` or `context_too_long`); nothing is retried |
| `privacy_blocked` | the privacy gate refused the call (`private_code_blocked`) |

Nothing raises for these endings; the result keeps every step, the full conversation, summed token usage and the error. Only mistakes in the arguments raise. Pass `observer=` a function to receive `ModelCallEvent`, `ToolCallEvent` and `FinishEvent` as they happen (for the trace store and recorder in P21 and P22); an observer that raises is logged by type only, counted in `result.observer_errors`, and does not stop the job.

`format_issue_task(context)` builds the task text from a fetched issue: the issue title, body and comments are limited in size and every line of them is quoted with `| `, so text written by other people cannot pass itself off as instructions. The system prompt also tells the model that issue text, files and tool output are data. That reduces prompt injection but does not remove it; the real protections are the sandbox, the protected-file guards, the privacy gate and the verifier.

Not there yet: loop detection (P18), running the failing test before the first model call (P19), and trimming a long conversation (a run that outgrows the model's context ends as `model_error` / `context_too_long`). The prompt has not been tried against a real model.

### Hard limits per job

`Limits(max_steps, max_cost_usd=None, max_wall_clock_s=None, cost_margin=1.25)` is required by `run_agent`. `limits_from_config(app, model)` fills it from `config/app.yaml` (steps and time) and takes the cost cap as the **lower** of `max_cost_usd` there and the model's `per_issue_cap_usd`. With the shipped config Haiku gets 30 steps, $0.10 and 600 s. Free models cost nothing, so their cost cap of 0 is never reached.

- **Steps** count model calls. The last allowed reply is recorded and its tool calls are not run.
- **Cost is checked before every model call.** The loop adds the *worst case* for the next call (the whole estimated prompt, scaled by `cost_margin`, at the dearest input rate, plus the full output limit; doubled for a model without native tool calling, because of its repair call) to what the job has spent. If that could pass the cap, the run ends with `cost_cap` and nothing is sent. After a call the loop checks the real spend again: if a reply pushed it over, its tools are not run. A final answer that arrives over the cap is still returned as `finished`, with `limit_detail` saying the estimate was too low. A cost cap needs `ledger=` the ledger of the `MeteredAdapter` in the chain (`create_adapter(..., ledger=ledger)`); without it, or with a different ledger, `run_agent` raises before sending anything, because a cap that cannot be measured cannot be kept.
- **Time is checked before every model call and every tool call.** `run_tests` and `run_command` are given the time left as their timeout (and are not started with under a second left), so a long test run cannot carry a job far past its cap. Tool calls that cannot start are answered with "not run" so the conversation stays valid.
- When limits are reached together, time wins over cost and cost over steps. The result reports `cost_usd` (this job's spend), `elapsed_s` and `limit_detail`, a sentence naming the limit and the amount used.

For one Haiku step with a 20,000-token prompt the worst case is $0.005173 (25,000 tokens at $0.125 per million plus 4,096 output tokens at $0.50 per million), so the pre-check stops a job only once it has spent more than $0.0948 of the $0.10; a typical step of that size costs about $0.00225, so the 30-step limit normally comes first. These figures are calculated, not measured. Because the margin pushes prompts above 80,000 tokens into the over-100,000-token price tier, long conversations are stopped early on purpose.

What can still run over: a model call that has started cannot be cancelled (it is bounded by the adapter's own timeout), and a read-only tool call may take up to 30 s. The 1.25 margin is a guess to be checked against real token counts. Limits are per job; per-batch and per-model caps and the 5 USD project budget come in P46.
