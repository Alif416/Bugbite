"""Shared pieces for the text-action tests: the six planned tool shapes and small builders."""

import json

from bugbite.adapter import ToolDefinition

OBJ = "object"


def tool(name, description, properties, required=(), extra=False):
    schema = {"type": OBJ, "properties": properties, "additionalProperties": extra}
    if required:
        schema["required"] = list(required)
    return ToolDefinition(name, description, schema)


READ_FILE = tool(
    "read_file", "Read a file from the repository.",
    {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}},
    ["path"],
)  # fmt: skip
SEARCH_CODE = tool(
    "search_code", "Search the code for text or a pattern.",
    {"query": {"type": "string"}, "path": {"type": "string"}, "regex": {"type": "boolean"}},
    ["query"],
)  # fmt: skip
EDIT_FILE = tool(
    "edit_file", "Replace text in a file.",
    {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
    ["path", "old", "new"],
)  # fmt: skip
RUN_TESTS = tool("run_tests", "Run tests.", {"targets": {"type": "array", "items": {"type": "string"}}})
RUN_COMMAND = tool("run_command", "Run a shell command.", {"command": {"type": "string"}}, ["command"])
LIST_DIRECTORY = tool("list_directory", "List a directory.", {"path": {"type": "string"}}, ["path"])
MODE = tool("set_mode", "Set a mode.", {"mode": {"enum": ["fast", "safe"]}, "level": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}}, ["mode"])

TOOLS = (READ_FILE, SEARCH_CODE, EDIT_FILE, RUN_TESTS, RUN_COMMAND, LIST_DIRECTORY)


def action(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def final(text):
    return json.dumps({"final": text})
