import json
import random

import pytest

from bugbite.adapter import GenerationRequest, GenerationResponse, Message, TextBlock, ToolCallBlock, ToolDefinition, ToolResultBlock, Usage
from bugbite.adapter.codec import (
    CodecError, block_from_dict, block_to_dict, canonical_json, error_from_dict, error_to_dict, request_fingerprint, request_from_dict,
    request_to_dict, response_from_dict, response_to_dict, scrub_value,
)
from bugbite.adapter.types import STOP_REASONS
from bugbite.errors import ALL_ADAPTER_CODES, AdapterError

TEXTS = ["", "plain", "multi\nline\r\ntext", "unicode é中\U0001F642 עברית", "tab\tquote\"back\\slash", "{\"json\": [1, 2]}", "x" * 3000]


def rnd_text(rng):
    return rng.choice(TEXTS)


def rnd_json(rng, depth=0):
    kinds = ["int", "float", "str", "bool", "none"] + (["list", "dict"] if depth < 3 else [])
    kind = rng.choice(kinds)
    return {"int": lambda: rng.randint(-10**9, 10**9), "float": lambda: rng.uniform(-1e6, 1e6), "str": lambda: rnd_text(rng),
            "bool": lambda: rng.random() < 0.5, "none": lambda: None,
            "list": lambda: [rnd_json(rng, depth + 1) for _ in range(rng.randint(0, 3))],
            "dict": lambda: {rnd_text(rng) + str(i): rnd_json(rng, depth + 1) for i in range(rng.randint(0, 3))}}[kind]()


def rnd_block(rng, n, assistant=True):
    if assistant:
        if rng.random() < 0.5:
            return TextBlock(rnd_text(rng), rng.random() < 0.3)
        return ToolCallBlock(f"call_{n}", rng.choice(["read_file", "edit_file", "weird name"]), {"k": rnd_json(rng)}, rng.choice([None, "bad json"]))
    if rng.random() < 0.5:
        return TextBlock(rnd_text(rng))
    return ToolResultBlock(f"call_{n}", rnd_text(rng), rng.random() < 0.5)


def rnd_response(rng):
    blocks = tuple(rnd_block(rng, i) for i in range(rng.randint(0, 4)))
    usage = Usage(*(rng.randint(0, 10**7) for _ in range(4)))
    return GenerationResponse(blocks, rng.choice(sorted(STOP_REASONS)), usage, rnd_text(rng) or "m", rng.choice([None, "raw"]),
                              rng.uniform(0, 100), rng.choice([None, "req_1"]), rng.random() < 0.3)


def rnd_request(rng):
    messages = tuple(Message(["user", "assistant"][i % 2], tuple(rnd_block(rng, i, assistant=i % 2 == 1) for _ in range(rng.randint(1, 3)))) for i in range(rng.randint(1, 5)))
    tools = tuple(ToolDefinition(f"tool_{i}", f"does thing {i}", {"type": "object", "properties": {"a": {"type": "string"}}}) for i in range(rng.randint(0, 3)))
    return GenerationRequest(messages, tuple(TextBlock(rnd_text(rng)) for _ in range(rng.randint(0, 2))), tools,
                             rng.choice([None, 0.0, 0.7, 1]), rng.choice([None, 100, 4096]), tuple(rng.sample(["STOP", "END", "\n\n"], rng.randint(0, 2))))


def through_json(data):
    return json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))


def test_thousands_of_random_responses_round_trip_exactly():
    rng = random.Random(20261102)
    for _ in range(3000):
        response = rnd_response(rng)
        assert response_from_dict(through_json(response_to_dict(response))) == response


def test_random_requests_round_trip_exactly():
    rng = random.Random(7)
    for _ in range(1000):
        request = rnd_request(rng)
        assert request_from_dict(through_json(request_to_dict(request))) == request


@pytest.mark.parametrize("code", sorted(ALL_ADAPTER_CODES))
@pytest.mark.parametrize("retry_after, status", [(None, None), (0, 429), (12.5, 503), (3, None)])
def test_every_error_shape_round_trips(code, retry_after, status):
    error = AdapterError(code, "something é happened", retry_after_s=retry_after, status_code=status)
    back = error_from_dict(through_json(error_to_dict(error)))
    assert (back.code, back.message, back.retry_after_s, back.status_code) == (code, error.message, retry_after, status)


def test_every_block_type_round_trips():
    for block in (TextBlock("a", True), TextBlock(""), ToolCallBlock("c1", "t", {"x": [1, {"y": None}]}, "oops"), ToolResultBlock("c1", "out", True)):
        assert block_from_dict(through_json(block_to_dict(block))) == block


@pytest.mark.parametrize("bad", [
    {"type": "other"}, {"type": "text", "text": "a"}, {"type": "text", "text": "a", "cache": False, "extra": 1}, {"type": "text", "text": 5, "cache": False},
    {"type": "tool_call", "id": "", "name": "n", "arguments": {}, "error": None}, {"type": "tool_result", "tool_call_id": "c", "content": 5, "is_error": False},
    "text", None, [], {},
])
def test_bad_blocks_are_rejected(bad):
    with pytest.raises(CodecError):
        block_from_dict(bad)


def test_bad_responses_and_errors_are_rejected():
    good = response_to_dict(GenerationResponse((TextBlock("a"),), "end_turn", Usage(1, 2), "m"))
    for change in ({"stop_reason": "nonsense"}, {"usage": {"input_tokens": 1}}, {"blocks": "x"}, {"latency_s": -1}, {"extra": 1}, {"model": ""}):
        with pytest.raises(CodecError):
            response_from_dict({**good, **change})
    for key in good:
        with pytest.raises(CodecError):
            response_from_dict({k: v for k, v in good.items() if k != key})
    with pytest.raises(CodecError):
        error_from_dict({"code": "made_up", "message": "x", "retry_after_s": None, "status_code": None})
    with pytest.raises(CodecError):
        error_from_dict({"code": "timeout", "message": "", "retry_after_s": None, "status_code": None})
    with pytest.raises(CodecError):
        request_from_dict({"messages": []})


# -- fingerprints --------------------------------------------------------------------------------------------------------------------------


BASE = GenerationRequest(
    (Message.user("hello"), Message.assistant(ToolCallBlock("c1", "read_file", {"path": "a.py"})), Message.tool_results(ToolResultBlock("c1", "x = 1"))),
    (TextBlock("system"),), (ToolDefinition("read_file", "reads", {"type": "object", "properties": {"path": {"type": "string"}}}),), 0.5, 100, ("STOP",))


def test_the_same_request_has_the_same_fingerprint_whatever_the_dict_order():
    a = request_fingerprint(BASE)
    reordered = GenerationRequest(BASE.messages, BASE.system, (ToolDefinition("read_file", "reads", {"properties": {"path": {"type": "string"}}, "type": "object"}),), 0.5, 100, ("STOP",))
    assert request_fingerprint(reordered) == a and request_fingerprint(BASE) == a
    assert a["messages"] == 3 and a["system_blocks"] == 1 and a["tools"] == 1 and a["max_output_tokens"] == 100 and a["temperature"] == 0.5 and a["stop_sequences"] == ["STOP"]
    assert len(a["sha256"]) == 64 and a["bytes"] == len(canonical_json(request_to_dict(BASE)).encode())


@pytest.mark.parametrize("name, change", [
    ("message text", lambda r: GenerationRequest((Message.user("hellO"),) + r.messages[1:], r.system, r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("an extra message", lambda r: GenerationRequest(r.messages + (Message.assistant("more"),), r.system, r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool call arguments", lambda r: GenerationRequest((r.messages[0], Message.assistant(ToolCallBlock("c1", "read_file", {"path": "b.py"}))) + r.messages[2:], r.system, r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool result text", lambda r: GenerationRequest(r.messages[:2] + (Message.tool_results(ToolResultBlock("c1", "x = 2")),), r.system, r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool result error flag", lambda r: GenerationRequest(r.messages[:2] + (Message.tool_results(ToolResultBlock("c1", "x = 1", True)),), r.system, r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("system prompt", lambda r: GenerationRequest(r.messages, (TextBlock("system!"),), r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("system cache flag", lambda r: GenerationRequest(r.messages, (TextBlock("system", True),), r.tools, r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool name", lambda r: GenerationRequest(r.messages, r.system, (ToolDefinition("read_files", "reads", r.tools[0].parameters),), r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool description", lambda r: GenerationRequest(r.messages, r.system, (ToolDefinition("read_file", "reads a file", r.tools[0].parameters),), r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("tool schema", lambda r: GenerationRequest(r.messages, r.system, (ToolDefinition("read_file", "reads", {"type": "object", "properties": {"path": {"type": "integer"}}}),), r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("no tools", lambda r: GenerationRequest(r.messages, r.system, (), r.temperature, r.max_output_tokens, r.stop_sequences)),
    ("temperature", lambda r: GenerationRequest(r.messages, r.system, r.tools, 0.6, r.max_output_tokens, r.stop_sequences)),
    ("temperature unset", lambda r: GenerationRequest(r.messages, r.system, r.tools, None, r.max_output_tokens, r.stop_sequences)),
    ("output limit", lambda r: GenerationRequest(r.messages, r.system, r.tools, r.temperature, 101, r.stop_sequences)),
    ("stop sequences", lambda r: GenerationRequest(r.messages, r.system, r.tools, r.temperature, r.max_output_tokens, ("STOP", "END"))),
])
def test_changing_anything_the_model_would_see_changes_the_fingerprint(name, change):
    assert request_fingerprint(change(BASE))["sha256"] != request_fingerprint(BASE)["sha256"], name


def test_unicode_is_fingerprinted_by_its_characters_not_an_escape_form():
    a = request_fingerprint(GenerationRequest((Message.user("é"),)))
    assert a["bytes"] == len(canonical_json({"messages": [{"role": "user", "blocks": [{"type": "text", "text": "é", "cache": False}]}], "system": [], "tools": [], "temperature": None, "max_output_tokens": None, "stop_sequences": []}).encode())


def test_canonical_json_refuses_nan_and_scrub_value_reaches_everything():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    out = scrub_value({"a SECRET": ["SECRET", {"k": "SECRET!"}, 5, None, True]}, lambda t: t.replace("SECRET", "[x]"))
    assert out == {"a [x]": ["[x]", {"k": "[x]!"}, 5, None, True]}
