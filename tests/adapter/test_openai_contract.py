from adapter_contract import AdapterContract
from openai_helpers import adapter_for, completion, tool_call


class TestOpenAICompatibleContract(AdapterContract):
    """The OpenAI-compatible adapter passes the same contract every adapter must pass."""

    def adapter_for_text(self):
        adapter, _ = adapter_for(completion("Hello there!"))
        return adapter

    def adapter_for_tool_call(self):
        adapter, _ = adapter_for(completion(None, [tool_call("read_file", '{"path": "a.py"}')], finish="tool_calls"))
        return adapter
