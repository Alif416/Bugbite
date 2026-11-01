"""Small stand-ins for loop tests."""

from bugbite.adapter import ToolDefinition
from bugbite.adapter.testing import ScriptedAdapter, text_response, tool_call_response
from bugbite.agent.tools import ToolOutput

ECHO = ToolDefinition("echo", "Echo text back.", {"type": "object", "properties": {"text": {"type": "string"}}, "additionalProperties": False})
BOOM = ToolDefinition("boom", "Always breaks.", {"type": "object", "properties": {}, "additionalProperties": False})


class FakeTools:
    """Same two methods the loop uses on a ToolRegistry, with a record of what was run."""

    def __init__(self, outputs=None, raises=None):
        self.outputs = outputs or {}
        self.raises = raises
        self.executed = []

    def definitions(self):
        return (ECHO, BOOM)

    def execute(self, name, arguments):
        self.executed.append((name, dict(arguments)))
        if self.raises:
            raise self.raises
        if name in self.outputs:
            return self.outputs[name]
        return ToolOutput(f"echo: {arguments.get('text', '')}")


def adapter(*script):
    return ScriptedAdapter(None, list(script))


__all__ = ["FakeTools", "adapter", "text_response", "tool_call_response", "ECHO", "BOOM"]
