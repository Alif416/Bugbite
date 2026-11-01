# Validation: Sandbox Clone and Install (Roadmap P5)

The work can be merged when every item below is true.

## Automated (no Docker, no internet)

- [x] `uv run pytest` passes with Docker **unreachable** (e.g. a dead `DOCKER_HOST`): docker and internet tests are skipped with visible reasons, none fail, and all earlier tests still pass.
- [x] `plan_install` covers and passes: pyproject only; setup.py only; setup.cfg only; requirements.txt only; packaging file plus requirements.txt (packaging wins, requirements not installed as required); optional test requirements files are best effort; nothing to install; pytest step is always last.
- [x] Ref validation accepts 7 to 40 character hex commits, simple branch names, tags, and `release/1.2`; rejects empty, leading `-`, spaces, `;`, `$`, backticks, newlines, `..`, and over-long values.
- [x] Dependency groups: `select_groups` prefers test-like groups and falls back to `dev`; `plan_install` adds `pip-upgrade` and one step per group only when groups are given, ignores non-whitelisted names, and keeps pytest last.
- [x] `repo_clone_url` builds `https://github.com/<owner>/<name>.git` only from a `RepoRef`.
- [x] `SandboxConfig` defaults: image `bugbite-sandbox:py3.11-1`, `workspace_mb` 2048, `setup_timeout_s` 900; loader accepts and validates `setup_timeout_s`; the shipped `config/app.yaml` loads.
- [x] New error code `workspace_full` is covered in `tests/test_errors.py`.

## Automated (Docker running)

- [x] The image builds from `docker/sandbox.Dockerfile`, contains `git`, and is reused (not rebuilt) on the next start.
- [x] `/workspace` is a disk-backed volume (not tmpfs), owned by uid 1000, and the volume is gone after `close()` (no dangling volumes created by the tests).
- [x] `disconnect_network()` removes `eth0` and routes, is safe to call twice, and a connection attempt fails afterwards; `has_network` reflects Docker's state.
- [x] Workspace soft cap: usage above `workspace_mb` raises `workspace_full`; usage below does not.
- [x] Setup on a local test repo (built inside the container): clone, venv, install, pytest present, `git rev-parse HEAD` recorded, `git diff` works, network cut afterwards.
- [x] Failure cases give the right `failure_reason` and a useful `output_tail`, and the network is cut in each: clone of a missing repo (`clone_failed`), bad requirement (`install_failed`), install timeout (`setup_timeout`), workspace over the cap (`workspace_full`).
- [x] Pinned ref: setup at an older commit checks out exactly that commit.
- [x] After setup, an outbound connection from the container fails.
- [x] All Docker tests leave no labelled containers.

## Automated (Docker and internet)

- [x] Install paths pass against real PyPI: packaging repo with extras, extras-fallback case, requirements-only repo, repo with nothing to install, pytest installed only when missing (a repo that pins its own pytest keeps its version).
- [x] A PEP 735 `tests` group is installed (other groups such as `docs` are not), and a failing group is a warning, not a failure.
- [x] `setup_repo` on `octocat/Hello-World` at its pinned commit clones over HTTPS and reports that commit.

## Manual checks

- [x] `docker ps -a --filter label=bugbite.sandbox=1` and `docker volume ls -f dangling=true` show nothing left by the test run.
- [x] `git grep -nE "GITHUB_TOKEN|ghp_|Authorization" src/bugbite/sandbox` returns nothing (no credentials handled in the sandbox code).
- [x] No `shell=True`, and no f-string built from user text passed to a shell, in the clone code (`git grep -n "sh -c" src/bugbite/sandbox/setup.py` reviewed by hand).
- [x] One real end-to-end setup of a small public Python repo with a test suite, run by hand (2026-11-01, pallets/itsdangerous: setup ok in 10.9 s, 50 MB, network cut; its 297 tests pass offline afterwards; clone 1.3 s, venv 1.6 s, pip-upgrade 2.0 s, project 1.6 s, dependency-group 3.8 s, pytest 0.2 s). This run found the missing dependency-group support, now fixed (AD-035).
- [x] Error and failure messages read clearly to a non-developer (spot check).

## Docs and process

- [x] `specs/decisions.md` has AD-030 to AD-035, and AD-026 is marked superseded in part.
- [x] `specs/roadmap.md` has P5 ticked and P7 mentions pruning dangling workspace volumes.
- [x] README explains first-use image build and the `internet` marker.
- [x] CI builds the sandbox image before the tests.
- [x] Commits are small and logical on branch `2026-11-01-p05-sandbox-clone-install`.
- [x] No files outside this phase's scope were changed (no test running or result parsing, no agent code).

## Definition of done

All boxes ticked, tests green locally with Docker and internet available, and also green with Docker unreachable, and the branch is ready for review and merge into `main`.
