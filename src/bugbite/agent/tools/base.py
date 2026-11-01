"""The shape every agent tool shares: a definition for the model and a run method that never raises."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from bugbite.adapter.types import ToolDefinition, ToolResultBlock

TOOLS_VERSION = "2"  # bump when any tool's description or schema changes, so recordings can say which text a run used


@dataclass(frozen=True)
class ToolOutput:
    """What a tool hands back to the loop: text for the model, and whether the call failed."""

    text: str
    is_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("ToolOutput.text must be a string")

    def to_block(self, tool_call_id: str) -> ToolResultBlock:
        return ToolResultBlock(tool_call_id, self.text, self.is_error)


def error(message: str) -> ToolOutput:
    return ToolOutput(message, True)


class Tool:
    """Subclasses set `definition` and implement `_run` with arguments already checked against the schema."""

    definition: ToolDefinition

    @property
    def name(self) -> str:
        return self.definition.name

    def run(self, arguments: Mapping[str, Any], *, time_limit_s: float | None = None) -> ToolOutput:
        """`time_limit_s` is how long this call may take at most (the time left for the job); None means no limit."""
        problem = check_arguments(self.definition, arguments)
        if problem:
            return error(problem)
        return self._run(dict(arguments), time_limit_s)

    def _run(self, arguments: dict[str, Any], time_limit_s: float | None = None) -> ToolOutput:  # pragma: no cover - abstract
        raise NotImplementedError


def check_arguments(definition: ToolDefinition, arguments: Any) -> str | None:
    """None if the arguments fit the tool's schema, else a message saying what is wrong."""
    if not isinstance(arguments, Mapping):
        return f"Arguments for {definition.name} must be an object."
    found = best_match(Draft202012Validator(definition.parameters).iter_errors(dict(arguments)))
    if found is None:
        return None
    where = ".".join(str(part) for part in found.absolute_path)
    prefix = f"Argument '{where}': " if where else ""
    return f"Invalid arguments for {definition.name}. {prefix}{found.message}"
