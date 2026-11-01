from adapter_contract import AdapterContract
from claude_helpers import adapter_for, message, text, tool_use


class TestClaudeAdapterContract(AdapterContract):
    """The Claude adapter passes the same contract every adapter must pass."""

    def adapter_for_text(self):
        adapter, _ = adapter_for(message([text("Hello there!")]))
        return adapter

    def adapter_for_tool_call(self):
        adapter, _ = adapter_for(message([tool_use("read_file", {"path": "a.py"})], stop_reason="tool_use"))
        return adapter
