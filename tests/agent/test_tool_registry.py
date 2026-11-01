import pytest
from tool_helpers import LocalSandbox

from bugbite.adapter import GenerationRequest, Message, validate_request
from bugbite.adapter.types import ToolDefinition, ToolResultBlock
from bugbite.agent.tools import TOOLS_VERSION, Tool, ToolOutput, ToolRegistry, build_read_only_tools
from bugbite.errors import EXEC_FAILED, SandboxError


@pytest.fixture
def sb(tmp_path):
    (tmp_path / "r").mkdir()
    box = LocalSandbox(tmp_path / "r")
    box.write("a.py", "needle\n")
    return box


class Boom(Tool):
    definition = ToolDefinition("boom", "Always fails.", {"type": "object", "properties": {}, "additionalProperties": False})

    def __init__(self, exc):
        self.exc = exc

    def _run(self, arguments, time_limit_s=None):
        raise self.exc


def test_definitions_are_valid_and_named(sb):
    registry = build_read_only_tools(sb)
    assert registry.names == ("read_file", "list_directory", "search_code")
    for definition in registry.definitions():
        assert definition.parameters["type"] == "object" and definition.parameters["additionalProperties"] is False
        assert len(definition.description) > 40 and "Example" in definition.description
    assert TOOLS_VERSION == "2"


def test_definitions_are_accepted_by_request_validation(sb):
    registry = build_read_only_tools(sb)
    request = GenerationRequest(messages=(Message.user("hi"),), tools=registry.definitions())
    validate_request(request)


def test_duplicate_names_are_rejected(sb):
    registry = build_read_only_tools(sb)
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([Boom(ValueError()), Boom(ValueError())])
    assert len(registry.definitions()) == 3


def test_execute_runs_the_named_tool(sb):
    assert build_read_only_tools(sb).execute("search_code", {"pattern": "needle"}) == ToolOutput("a.py:1:needle")


@pytest.mark.parametrize("name, args, fragment", [
    ("nope", {}, "Unknown tool 'nope'. Available tools: read_file, list_directory, search_code"),
    (None, {}, "Unknown tool"),
    ("read_file", {}, "path"),
    ("read_file", {"path": 5}, "Argument 'path'"),
    ("read_file", {"path": "a.py", "extra": 1}, "extra"),
    ("read_file", {"path": "a.py", "start_line": 0}, "start_line"),
    ("read_file", {"path": "a.py", "start_line": True}, "start_line"),
    ("read_file", {"path": "a.py", "start_line": "1"}, "start_line"),
    ("search_code", {"pattern": ""}, "pattern"),
    ("search_code", {"pattern": "x", "regex": "yes"}, "regex"),
    ("list_directory", {"path": None}, "path"),
    ("read_file", "a.py", "must be an object"),
    ("read_file", None, "must be an object"),
])
def test_bad_calls_come_back_as_error_results(sb, name, args, fragment):
    out = build_read_only_tools(sb).execute(name, args)
    assert out.is_error and fragment in out.text


@pytest.mark.parametrize("exc, fragment", [
    (RuntimeError("secret internals"), "failed unexpectedly (RuntimeError)"),
    (SandboxError(EXEC_FAILED, "container hiccup"), "container hiccup"),
    (TimeoutError("too slow"), "timed out"),
    (KeyError("k"), "KeyError"),
])
def test_exceptions_inside_a_tool_never_escape(exc, fragment):
    out = ToolRegistry([Boom(exc)]).execute("boom", {})
    assert out.is_error and fragment in out.text
    assert "secret internals" not in out.text  # unexpected errors do not leak their message to the model


def test_outputs_convert_to_tool_result_blocks():
    block = ToolOutput("oops", True).to_block("call_1")
    assert block == ToolResultBlock("call_1", "oops", True)
    assert ToolOutput("fine").to_block("c").is_error is False
    with pytest.raises(TypeError):
        ToolOutput(5)  # type: ignore[arg-type]


def test_the_tools_work_through_the_text_action_wrapper(sb):
    from bugbite.adapter.testing import ScriptedAdapter, text_response
    from bugbite.adapter import TextActionAdapter
    from bugbite.config import ModelConfig, Pricing

    cfg = ModelConfig("m", "fake", "http://x", "m", 100_000, False, Pricing.free(), 0, True)
    registry = build_read_only_tools(sb)
    reply = '{"tool": "read_file", "arguments": {"path": "a.py", "start_line": 0}}'  # invalid on purpose
    good = '{"tool": "read_file", "arguments": {"path": "a.py"}}'
    adapter = TextActionAdapter(ScriptedAdapter(cfg, [text_response(reply), text_response(good)]))
    response = adapter.generate(GenerationRequest(messages=(Message.user("go"),), tools=registry.definitions()))
    call = response.tool_calls[0]
    assert call.name == "read_file" and adapter.stats.repaired_steps == 1  # the schema is enforced, and a repair worked
    assert registry.execute(call.name, call.arguments).text == "     1| needle"


def test_the_full_tool_set(sb):
    from bugbite.agent.tools import build_agent_tools

    registry = build_agent_tools(sb)
    assert registry.names == ("read_file", "list_directory", "search_code", "edit_file", "run_tests", "run_command")
    for definition in registry.definitions():
        assert definition.parameters["additionalProperties"] is False and "Example" in definition.description
    validate_request(GenerationRequest(messages=(Message.user("hi"),), tools=registry.definitions()))
    for name in ("edit_file", "run_tests", "run_command"):
        assert registry.execute(name, {"bogus": 1}).is_error
    assert registry.execute("edit_file", {"path": "a.py", "old_text": "needle", "new_text": "thread"}).text.startswith("Edited a.py")
