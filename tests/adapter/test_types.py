import dataclasses
import json

import pytest

from bugbite.adapter import (
    SCHEMA_VERSION,
    STOP_REASONS,
    GenerationRequest,
    GenerationResponse,
    Message,
    SchemaError,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    Usage,
)

SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
TOOL = ToolDefinition("read_file", "Read a file", SCHEMA)


def full_request():
    return GenerationRequest(
        system=(TextBlock("You fix bugs. ✓ café", cache=True), TextBlock("")),
        messages=(
            Message.user("Fix it \U0001f41b"),
            Message.assistant(
                "Looking.",
                ToolCallBlock("c1", "read_file", {"path": "a.py", "nested": {"x": [1, 2.5, None, True], "": "é"}}),
                ToolCallBlock("c2", "read_file", {}, error="arguments were not valid JSON"),
            ),
            Message.tool_results(
                ToolResultBlock("c1", "line1\nline2 ✓"),
                ToolResultBlock("c2", "", is_error=True),
            ),
            Message.user("thanks", cache=True),
        ),
        tools=(TOOL, ToolDefinition("t2", "Another", {"type": "object"})),
        temperature=0.7,
        max_output_tokens=512,
        stop_sequences=("###", "END"),
    )


def full_response():
    return GenerationResponse(
        blocks=(TextBlock("ok ✓"), ToolCallBlock("c9", "read_file", {"path": "b.py"}, error=None)),
        stop_reason="tool_use",
        usage=Usage(input_tokens=100, output_tokens=20, cache_read_tokens=5, cache_write_tokens=7),
        model="m-1",
        raw_stop_reason="tool_calls",
        latency_s=1.25,
        request_id="req_1",
    )


# -- construction rules ---------------------------------------------------------


@pytest.mark.parametrize(
    "obj",
    [
        TextBlock("x"),
        ToolCallBlock("1", "t"),
        ToolResultBlock("1", "x"),
        Message.user("x"),
        TOOL,
        Usage(),
        full_request(),
        full_response(),
    ],
    ids=lambda o: type(o).__name__,
)
def test_every_type_is_immutable(obj):
    first_field = dataclasses.fields(obj)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, first_field, "changed")


def test_text_block_validation():
    with pytest.raises(TypeError):
        TextBlock(5)
    with pytest.raises(TypeError):
        TextBlock("x", cache="yes")
    assert TextBlock("").text == ""  # empty text is allowed in the type; adapters skip it


@pytest.mark.parametrize("bad_id", ["", None, 5])
def test_tool_call_needs_an_id(bad_id):
    with pytest.raises(ValueError):
        ToolCallBlock(bad_id, "t")


def test_tool_call_validation():
    with pytest.raises(ValueError):
        ToolCallBlock("1", "")
    with pytest.raises(TypeError):
        ToolCallBlock("1", "t", arguments=[1])
    with pytest.raises(TypeError):
        ToolCallBlock("1", "t", error=5)
    with pytest.raises(ValueError):
        ToolCallBlock("1", "t", {"x": object()})
    with pytest.raises(ValueError):
        ToolCallBlock("1", "t", {"x": float("nan")})


def test_tool_call_arguments_are_copied_so_callers_cannot_alias_them():
    source = {"a": [1, 2]}
    block = ToolCallBlock("1", "t", source)
    source["a"].append(3)
    assert block.arguments == {"a": [1, 2]}


def test_tool_result_validation():
    with pytest.raises(ValueError):
        ToolResultBlock("", "x")
    with pytest.raises(TypeError):
        ToolResultBlock("1", 5)
    with pytest.raises(TypeError):
        ToolResultBlock("1", "x", is_error="no")


def test_message_validation():
    with pytest.raises(ValueError):
        Message("system", (TextBlock("x"),))
    with pytest.raises(ValueError):
        Message("user", ())
    with pytest.raises(TypeError):
        Message("user", ("plain string",))
    assert isinstance(Message("user", [TextBlock("x")]).blocks, tuple)


def test_message_helpers():
    assert Message.user("hi") == Message("user", (TextBlock("hi"),))
    assert Message.assistant("a", ToolCallBlock("1", "t")).blocks[0] == TextBlock("a")
    assert Message.tool_results(ToolResultBlock("1", "r")).role == "user"


@pytest.mark.parametrize("name", ["", "has space", "dots.not.ok", "x" * 65, "üml"])
def test_tool_names_are_checked(name):
    with pytest.raises(ValueError):
        ToolDefinition(name, "d", {"type": "object"})


def test_tool_definition_validation():
    with pytest.raises(ValueError):
        ToolDefinition("t", "  ", {"type": "object"})
    with pytest.raises(ValueError):
        ToolDefinition("t", "d", {"type": "array"})
    with pytest.raises(ValueError):
        ToolDefinition("t", "d", ["not", "a", "dict"])
    with pytest.raises(ValueError):
        ToolDefinition("t", "d", {"type": "object", "x": object()})
    assert ToolDefinition("a-b_c9", "d", {"type": "object"}).name == "a-b_c9"


def test_request_coerces_lists_to_tuples_and_checks_item_types():
    req = GenerationRequest(messages=[Message.user("x")], system=[TextBlock("s")], tools=[TOOL], stop_sequences=["a"])
    assert all(isinstance(v, tuple) for v in (req.messages, req.system, req.tools, req.stop_sequences))
    with pytest.raises(TypeError):
        GenerationRequest(messages=["not a message"])
    with pytest.raises(TypeError):
        GenerationRequest(messages=(Message.user("x"),), system=(Message.user("x"),))
    with pytest.raises(TypeError):
        GenerationRequest(messages=(Message.user("x"),), tools=("t",))
    with pytest.raises(ValueError):
        GenerationRequest(messages=(Message.user("x"),), stop_sequences=("",))
    with pytest.raises(TypeError):
        GenerationRequest(messages=(Message.user("x"),), temperature="hot")
    with pytest.raises(TypeError):
        GenerationRequest(messages=(Message.user("x"),), temperature=True)
    with pytest.raises(TypeError):
        GenerationRequest(messages=(Message.user("x"),), max_output_tokens=1.5)


def test_usage_validation_and_totals():
    assert Usage().total == 0
    usage = Usage(input_tokens=10, output_tokens=5, cache_read_tokens=3, cache_write_tokens=2)
    assert usage.prompt_tokens == 15
    assert usage.total == 20
    for bad in (-1, 1.5, True, "5", None):
        with pytest.raises(ValueError):
            Usage(input_tokens=bad)
        with pytest.raises(ValueError):
            Usage(cache_read_tokens=bad)


def test_response_validation():
    base = dict(blocks=(), stop_reason="end_turn", usage=Usage(), model="m")
    GenerationResponse(**base)  # an empty response is valid (for example a max_tokens stop)
    with pytest.raises(ValueError):
        GenerationResponse(**{**base, "stop_reason": "finished"})
    with pytest.raises(ValueError):
        GenerationResponse(**{**base, "model": ""})
    with pytest.raises(TypeError):
        GenerationResponse(**{**base, "usage": {"input_tokens": 1}})
    with pytest.raises(ValueError):
        GenerationResponse(**{**base, "latency_s": -1})
    with pytest.raises(TypeError):
        GenerationResponse(**{**base, "blocks": (ToolResultBlock("1", "x"),)})  # a model cannot return tool results


def test_stop_reasons_are_the_documented_set():
    assert STOP_REASONS == {"end_turn", "tool_use", "max_tokens", "stop_sequence", "other"}


def test_response_text_and_tool_calls_keep_order():
    response = GenerationResponse(
        blocks=(TextBlock("a"), ToolCallBlock("1", "t1"), TextBlock("b"), ToolCallBlock("2", "t2")),
        stop_reason="tool_use", usage=Usage(), model="m",
    )  # fmt: skip
    assert response.text == "ab"
    assert [c.id for c in response.tool_calls] == ["1", "2"]
    assert GenerationResponse(blocks=(), stop_reason="end_turn", usage=Usage(), model="m").text == ""


# -- JSON round trips ----------------------------------------------------------------


def test_request_round_trip_is_exact_and_survives_real_json():
    request = full_request()
    data = request.to_dict()
    assert data["schema_version"] == SCHEMA_VERSION
    restored = GenerationRequest.from_dict(json.loads(json.dumps(data)))
    assert restored == request
    assert restored.to_dict() == data


def test_response_round_trip_is_exact_and_survives_real_json():
    response = full_response()
    restored = GenerationResponse.from_dict(json.loads(json.dumps(response.to_dict())))
    assert restored == response


def test_round_trip_of_minimal_objects():
    request = GenerationRequest(messages=(Message.user("x"),))
    assert GenerationRequest.from_dict(request.to_dict()) == request
    response = GenerationResponse(blocks=(), stop_reason="max_tokens", usage=Usage(), model="m")
    assert GenerationResponse.from_dict(response.to_dict()) == response


def test_unicode_is_preserved_exactly():
    text = "café ✓ \U0001f41b \u0000  "
    request = GenerationRequest(messages=(Message.user(text),))
    assert GenerationRequest.from_dict(json.loads(json.dumps(request.to_dict()))).messages[0].blocks[0].text == text


# -- decoding errors ------------------------------------------------------------------


def request_dict():
    return full_request().to_dict()


def test_unknown_schema_version_is_rejected():
    data = request_dict()
    data["schema_version"] = 99
    with pytest.raises(SchemaError, match="schema_version"):
        GenerationRequest.from_dict(data)
    del data["schema_version"]
    with pytest.raises(SchemaError, match="schema_version"):
        GenerationRequest.from_dict(data)


def test_unknown_block_type_is_rejected_with_its_location():
    data = request_dict()
    data["messages"][0]["blocks"][0] = {"type": "image", "url": "x"}
    with pytest.raises(SchemaError, match=r"messages\[0\].*image"):
        GenerationRequest.from_dict(data)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.pop("messages"), "messages"),
        (lambda d: d.pop("temperature"), "temperature"),
        (lambda d: d.update(temperature="hot"), "temperature"),
        (lambda d: d.update(messages="nope"), "messages"),
        (lambda d: d.update(extra=1), "extra"),
        (lambda d: d["messages"][0].update(role="robot"), "role"),
        (lambda d: d["messages"][0].pop("blocks"), "blocks"),
        (lambda d: d["messages"][0]["blocks"][0].pop("text"), "text"),
        (lambda d: d["messages"][0]["blocks"][0].update(text=5), "text"),
        (lambda d: d["messages"][0]["blocks"][0].update(cache="yes"), "cache"),
        (lambda d: d["messages"][0]["blocks"][0].update(surprise=1), "surprise"),
        (lambda d: d["tools"][0].pop("parameters"), "parameters"),
        (lambda d: d["tools"][0].update(name="bad name"), "name"),
        (lambda d: d["system"].append({"type": "tool_call", "id": "1", "name": "t", "arguments": {}, "error": None}), "system"),
        (lambda d: d.update(max_output_tokens="many"), "max_output_tokens"),
        (lambda d: d.update(stop_sequences=[1]), "stop_sequences"),
    ],
)
def test_malformed_request_json_is_rejected_clearly(mutate, message):
    data = request_dict()
    mutate(data)
    with pytest.raises(SchemaError, match=message):
        GenerationRequest.from_dict(data)


@pytest.mark.parametrize("junk", [None, [], "text", 5])
def test_non_object_input_is_rejected(junk):
    with pytest.raises(SchemaError):
        GenerationRequest.from_dict(junk)
    with pytest.raises(SchemaError):
        GenerationResponse.from_dict(junk)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.pop("usage"), "usage"),
        (lambda d: d["usage"].pop("cache_write_tokens"), "cache_write_tokens"),
        (lambda d: d["usage"].update(input_tokens=-1), "input_tokens"),
        (lambda d: d["usage"].update(input_tokens=1.5), "input_tokens"),
        (lambda d: d.update(stop_reason="finished"), "stop_reason"),
        (lambda d: d.update(model=5), "model"),
        (lambda d: d.update(latency_s="fast"), "latency_s"),
        (lambda d: d.update(request_id=5), "request_id"),
        (lambda d: d["blocks"].append({"type": "tool_result", "tool_call_id": "1", "content": "x", "is_error": False}), "blocks"),
        (lambda d: d.update(schema_version=2), "schema_version"),
    ],
)
def test_malformed_response_json_is_rejected_clearly(mutate, message):
    data = full_response().to_dict()
    mutate(data)
    with pytest.raises(SchemaError, match=message):
        GenerationResponse.from_dict(data)
