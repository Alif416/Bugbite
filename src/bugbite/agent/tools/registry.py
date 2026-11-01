"""Look up and run tools by name. Nothing a tool does, or a model asks for, raises out of `execute`."""

from __future__ import annotations

from typing import Any, Callable, Collection, Iterable

from bugbite.adapter.types import ToolDefinition
from bugbite.errors import SandboxError

from .base import Tool, ToolOutput, error
from .edit_run import EditFile, RunCommand, RunTests
from .read_only import ListDirectory, ReadFile, SearchCode


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())

    def execute(self, name: str, arguments: Any, *, time_limit_s: float | None = None) -> ToolOutput:
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return error(f"Unknown tool '{name}'. Available tools: {', '.join(self._tools)}.")
        try:
            return tool.run(arguments, time_limit_s=time_limit_s)
        except SandboxError as exc:
            return error(f"The sandbox could not run {name}: {exc.message}")
        except TimeoutError as exc:
            return error(f"{name} timed out: {exc}.")
        except Exception as exc:  # a tool bug must come back as an error result, not stop the job
            return error(f"{name} failed unexpectedly ({type(exc).__name__}).")


def build_read_only_tools(sandbox: Any) -> ToolRegistry:
    return ToolRegistry([ReadFile(sandbox), ListDirectory(sandbox), SearchCode(sandbox)])


def build_agent_tools(sandbox: Any, *, allowed_edit_paths: Collection[str] = (), test_runner: Callable[..., Any] | None = None) -> ToolRegistry:
    """All six tools. `allowed_edit_paths` is for the calling code only, for an issue that is about a protected file."""
    tests = RunTests(sandbox) if test_runner is None else RunTests(sandbox, test_runner)
    return ToolRegistry([
        ReadFile(sandbox), ListDirectory(sandbox), SearchCode(sandbox),
        EditFile(sandbox, allowed_edit_paths), tests, RunCommand(sandbox),
    ])
