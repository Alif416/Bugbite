# Requirements: Privacy Gate (Roadmap P13)

## Goal

Make it impossible for private code to reach a model that is not marked as allowed to receive it. The README states this as a rule (FR14.9) and as an acceptance criterion ("Private code is never sent to a provider that is not marked as allowed in the model config"), but until now `allow_private_code` has been a config value that nothing checks. This phase turns it into a rule enforced in code at two independent places.

## Scope

**In:**
- Classification of a job's data as public, sandbox, or private
- `sandbox_repos`: the owner's list of repos any model may see
- A job-start check that refuses a job whose data a chosen model may not receive, with a clear message
- `PrivacyGuardAdapter`: the last gate before the network, refusing every call that is not allowed
- `create_adapter` takes the data's sensitivity and fails closed when it is not given
- An architecture test that stops later code building an unguarded adapter
- `PrivacyError`, kept separate from provider and input errors
- Documentation of the rule and the instruction for entry points

**Out (later phases):**
- Calling the job-start check from the CLI and API (P45, P66); this phase delivers the function and the instruction
- Stopping private code from reaching logs, traces, dashboards, or recordings (a storage concern for P21, P22, P71); noted below as an open item
- Any override or "I accept the risk" flag: there is none by design
- Checking what a provider actually does with data (terms of service): that is a human decision recorded in the config
- Detecting private content inside a public repo (for example a committed secret)
- Network-level controls such as blocking all hosts except the configured one

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Where | Job start and, independently, at the model boundary | Early clear message plus a lock that cannot be bypassed; the owner's choice (AD-076) |
| Classification | Public on GitHub, or on the owner's `sandbox_repos` list; everything else, including unknown, is private | Matches FR14.9 ("public repos and sandbox issues"); fail closed (AD-077) |
| On violation | Refuse with a clear message; no switching, no override | Honest comparisons and costs; the rule is enforced in code; the owner's choice (AD-078) |
| Errors | `PrivacyError`, its own family | Cannot be swallowed, retried, or repaired by accident (AD-079) |
| Haiku | `allow_private_code` stays `false` | The owner's choice; a policy decision about Anthropic's terms that is theirs to change (AD-080) |
| No bypass | Concrete adapters may only be built through `create_adapter` | Architecture test enforces it (AD-081) |

See `specs/decisions.md` AD-076 to AD-081.

## Context

- README: FR14.9 ("free hosted tiers may use prompts for training, so they only receive public repos and sandbox issues; private code only goes to local models or providers marked as allowed in the config"), FR14.3 (the `allow private code` field in the model config), section 10 acceptance ("Private code is never sent to a provider that is not marked as allowed in the model config"), section 11 risks ("Free models send prompts to a provider that may train on them"), FR12.2 (an owner-controlled allow list of repos, which `sandbox_repos` is also the natural home for), section 16 question 1 (which sandbox repos for the live demo; still unanswered, so the list starts empty).
- Builds on P1 (`ModelConfig.allow_private_code`), P3 (`RepoInfo.private` and the canonical `full_name` from GitHub, and the redirect check that stops a job from working on a different repo than requested), P8 to P12 (the adapter stack: raw adapter, metering, text-action wrapper).
- Current settings: `haiku` is `false`, `groq-free` is `false` (a free hosted tier), `local-free` is `true` (runs on the owner's machine).
- Everything sent in a prompt (issue text, file contents the agent reads, test output) can come from the repository, so the gate is about the whole job, not only the issue.
- Terminology: in this project "sandbox" also means the Docker container. `sandbox_repos` refers to the owner's demo and test repositories (FR14.9's wording) and the config comment says so.

## Constraints

- Fail closed: unknown visibility, a missing classification, or an unlisted repo is treated as private.
- The guard decides before it looks at the request, and never logs or echoes request content.
- No flag, environment variable, or argument turns the rule off. The only way to change who may receive private code is to edit `allow_private_code` in the model config, which is visible in version control.
- A refused call is not a model call: it is not recorded in the cost ledger and not retried.
- Default `uv run pytest` needs no network, no Docker, and no key.
- Commits carry no co-author trailer.
- No UI work, so the no-gradient rule does not apply.

## Open items

- The CLI and API (P45, P66) must call `check_job_privacy` after fetching the issue and pass the result to `create_adapter`. Until they exist nothing calls it; the guard's fail-closed default means forgetting is safe for models that cannot take private code, but would not stop a job from being refused late.
- Private code can also leak through storage: traces, recordings, and the dashboard will hold prompts and file contents. Where they are stored and who can read them is decided when those phases are built; this phase does not address it.
- A config mistake can defeat the rule: setting `allow_private_code: true` on a model whose `base_url` points to a remote host. A load-time warning for non-local hosts is worth adding but needs a decision about what counts as local.
- The GitHub trigger (P74) must check the sandbox list and classify before running.
- Whether a repo that is public today but was private when the job started could change class mid-job is ignored; classification happens once per job.

## Decision log

Architectural decisions for this phase are recorded in `specs/decisions.md` (AD-076 to AD-081).
