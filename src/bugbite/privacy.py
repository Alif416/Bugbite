"""The privacy rule: private code may only go to models marked as allowed to receive it.

A job's data is `PUBLIC` when GitHub says the repo is public, `SANDBOX` when the repo is on the
owner's `sandbox_repos` list, and `PRIVATE` otherwise, including whenever that is unknown
(fail closed). A model that does not allow private code may receive only `PUBLIC` and
`SANDBOX` data. There is no override: the only way to change who may receive private code is to
edit `allow_private_code` in the model config.

Enforced twice: `check_job_privacy` when a job starts, and the guard around the model adapter
on every call (see `bugbite.adapter.privacy_guard`).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Iterable, Mapping

from bugbite.config import ModelConfig
from bugbite.errors import PRIVATE_CODE_BLOCKED, PrivacyError

if TYPE_CHECKING:  # imported only for type checking, so this module stays free of the GitHub package
    from bugbite.github.models import JobContext


class Sensitivity(str, Enum):
    PUBLIC = "public"
    SANDBOX = "sandbox"
    PRIVATE = "private"


def _normal(name: str) -> str:
    return name.strip().lower()


def classify(full_name: str | None, private: bool | None, sandbox_repos: Iterable[str] = ()) -> Sensitivity:
    """What kind of data a repo's code is. Anything uncertain is private."""
    if isinstance(full_name, str) and _normal(full_name) in {_normal(r) for r in sandbox_repos}:
        return Sensitivity.SANDBOX
    if private is False:  # only an explicit "public" counts; None and anything odd are private
        return Sensitivity.PUBLIC
    return Sensitivity.PRIVATE


def classify_context(context: "JobContext", sandbox_repos: Iterable[str] = ()) -> Sensitivity:
    """Classify a fetched job by the repository name and visibility GitHub reported."""
    return classify(context.repo.full_name, context.repo.private, sandbox_repos)


def may_receive(model: ModelConfig, sensitivity: Sensitivity) -> bool:
    """The whole rule, in one place."""
    if not isinstance(sensitivity, Sensitivity):
        raise TypeError(f"sensitivity must be a Sensitivity, got {sensitivity!r}")
    return bool(model.allow_private_code) or sensitivity is not Sensitivity.PRIVATE


def allowed_model_names(models: Mapping[str, ModelConfig]) -> list[str]:
    return sorted(name for name, model in models.items() if model.allow_private_code)


_HOW_TO_CHANGE = (
    "To change which models may see private code, edit allow_private_code for the model in "
    "config/models.yaml, after checking the provider's current data terms."
)


def check_job_privacy(
    model: ModelConfig,
    context: "JobContext",
    sandbox_repos: Iterable[str] = (),
    models: Mapping[str, ModelConfig] | None = None,
) -> Sensitivity:
    """Run when a job starts. Returns the data's sensitivity, or raises `PrivacyError` before any work."""
    sensitivity = classify_context(context, sandbox_repos)
    if may_receive(model, sensitivity):
        return sensitivity
    allowed = allowed_model_names(models or {})
    choice = (
        f"Models that may receive private code: {', '.join(allowed)}. "
        if allowed
        else "No configured model is allowed to receive private code. "
    )
    raise PrivacyError(
        PRIVATE_CODE_BLOCKED,
        f"Model '{model.name}' is not allowed to receive private code, and the repository "
        f"{context.repo.full_name} is private (or its visibility is unknown). {choice}{_HOW_TO_CHANGE}",
    )


def refusal_for(model: ModelConfig, sensitivity: Sensitivity) -> PrivacyError:
    """The error the guard raises on a call that the rule forbids."""
    return PrivacyError(
        PRIVATE_CODE_BLOCKED,
        f"Refused to send {sensitivity.value} code to model '{model.name}': it is not allowed to receive "
        "private code (allow_private_code is false). The job should have been refused when it started; "
        f"{_HOW_TO_CHANGE}",
    )
