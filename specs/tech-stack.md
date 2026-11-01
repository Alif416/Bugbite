# Tech Stack

## Core

| Area | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Whole backend, agent, evals |
| API | FastAPI | Job submission, status, traces |
| Sandbox | Docker via Docker SDK for Python | All agent code and tests run here only |
| Database | PostgreSQL | Jobs, traces, eval results, spend |
| Queue / rate limiting | Redis | Job queue, provider rate limits, resume after interruption |
| GitHub | PyGithub or direct REST | Fetch issues, branch, push, open PR, comment |
| Frontend | React | Submit, live progress, traces, PR preview, eval and comparison pages, spend counter |
| Testing | pytest | Unit tests per module |
| CI | GitHub Actions | Tests on push |

## Models

- **Model adapter** (one interface): input = messages + tool defs + config; output = normalized text, tool calls, token usage, stop reason.
- **Claude adapter**: Claude API with tool use; **Haiku is the default paid model**; prompt caching on from day one.
- **OpenAI-compatible adapter**: covers Ollama, Groq, OpenRouter, vLLM, Gemini/GitHub Models via compatible endpoints.
- **Text action fallback**: for models without reliable tool calling, one JSON action per turn, validated, one repair attempt, then a failed step.
- **Model config file** per model: provider, base URL, model name, context window, native tool calling (y/n), price per token (0 for free), per-issue cap, may-receive-private-code flag.
- **Free models**: local open-weight coder model (e.g. Qwen coder via Ollama or llama.cpp) and/or free hosted tiers. Record date, terms, and hardware/tier with every run.

## Retrieval

- Symbols: `ast` (or tree-sitter)
- Text search: ripgrep
- Semantic search: embeddings in Chroma (or pgvector)
- Context sent to the model is always small snippets, never the whole repo.

## Agent tools

`read_file`, `search_code`, `edit_file`, `run_tests`, `run_command`, `list_directory`

## Cross-cutting modules

Clear boundaries, each with unit tests: `sandbox`, `retrieval`, `agent`, `adapter`, `verifier` (includes cheating guards), `pr_writer`, `recorder/replayer`, `failure_classifier`, `evals`, `trace_store`.

## UI design rules

- **No gradients anywhere** (backgrounds, buttons, cards, charts, headers). Use flat, solid colors only. (Stakeholder input, 2026-11-01.)
- Charts (e.g. model comparison) use solid fills and flat lines.
- Keep the dashboard simple and plain; the agent and evals matter more than visual polish.

## Constraints

- Secrets only in environment variables or a secrets manager; never in code, logs, the agent, or the container.
- Per-container limits: CPU, memory, per-command timeout, no host access.
- Hard caps: steps, cost, wall-clock per job; per-batch and per-model spend caps.
- Free hosted tiers receive public repos and sandbox issues only.
- Benchmark: fixed SWE-bench Lite subset (20–30), chosen once, never changed; official SWE-bench scoring.
- Budget: 5 USD total (≈0 dev, ≈0.50 spike, ≈2.50 Haiku evals, ≈1.50 optional stronger model, ≈0.50 reserve).

## Decisions to confirm

Chroma vs pgvector; hosting for the demo (local vs free tier); which free models; PyGithub vs raw HTTP. Default to Chroma, local hosting, and PyGithub until decided.
