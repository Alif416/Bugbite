"""Docker sandbox: clone, install, and run code and tests in isolation."""

from bugbite.sandbox.container import CommandResult, Sandbox, list_sandbox_containers
from bugbite.sandbox.image import SANDBOX_IMAGE
from bugbite.sandbox.setup import (
    InstallStep,
    SetupResult,
    StepResult,
    plan_install,
    repo_clone_url,
    select_groups,
    setup_repo,
    setup_workspace,
    validate_ref,
)

__all__ = [
    "SANDBOX_IMAGE",
    "CommandResult",
    "InstallStep",
    "Sandbox",
    "SetupResult",
    "StepResult",
    "list_sandbox_containers",
    "plan_install",
    "repo_clone_url",
    "select_groups",
    "setup_repo",
    "setup_workspace",
    "validate_ref",
]
