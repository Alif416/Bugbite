"""Hammer the parser with seeded random replies: it must never raise, and must never hand back
arguments that break the tool's schema."""

import json
import random

from jsonschema import Draft202012Validator
from text_action_helpers import MODE, TOOLS

from bugbite.adapter import parse_action
from bugbite.adapter.text_action import ActionError, FinalAction, ToolAction

ALL_TOOLS = (*TOOLS, MODE)
BY_NAME = {t.name: t for t in ALL_TOOLS}
ALPHABET = list('{}[]":,\\\'`\n\t abcXYZ019_-.é✓🐛') + ["tool", "final", "arguments", "null", "true", "```json", "```"]


def random_value(rng, depth=0):
    kind = rng.choice(["str", "int", "float", "bool", "null", "list", "dict"] if depth < 3 else ["str", "int"])
    if kind == "str":
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 12)))
    if kind == "int":
        return rng.randint(-5, 10**6)
    if kind == "float":
        return rng.random() * 100
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "null":
        return None
    if kind == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 3))]
    return {"k%d" % i: random_value(rng, depth + 1) for i in range(rng.randint(0, 3))}


def random_action(rng):
    roll = rng.random()
    if roll < 0.15:
        return {"final": random_value(rng)}
    tool = rng.choice(ALL_TOOLS)
    arguments = {}
    for name, schema in tool.parameters.get("properties", {}).items():
        if rng.random() < 0.7:
            arguments[name] = random_value(rng) if rng.random() < 0.5 else {"string": "x", "integer": 3, "boolean": True, "array": ["a"], "object": {"n": 1}}.get(schema.get("type"), "fast")
    for name in tool.parameters.get("required", []):
        if rng.random() < 0.8:
            arguments.setdefault(name, "v")
    name = tool.name if rng.random() < 0.9 else rng.choice(["nope", "", "READ_FILE", 5])
    return {"tool": name, "arguments": arguments if rng.random() < 0.95 else random_value(rng)}


def corrupt(rng, text):
    for _ in range(rng.randint(0, 3)):
        roll = rng.random()
        if roll < 0.25 and text:
            i = rng.randrange(len(text))
            text = text[:i] + text[i + 1 :]
        elif roll < 0.5:
            i = rng.randrange(len(text) + 1)
            text = text[:i] + rng.choice(ALPHABET) + text[i:]
        elif roll < 0.6 and text:
            text = text[: rng.randrange(len(text))]
        elif roll < 0.75:
            text = text + "\n" + text
        elif roll < 0.9:
            text = "```json\n" + text + "\n```"
        else:
            text = "Some reasoning {with braces}.\n" + text + "\nMore words."
    return text


def build(rng):
    kind = rng.random()
    if kind < 0.2:
        return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 80)))
    return corrupt(rng, json.dumps(random_action(rng), default=str, ensure_ascii=rng.random() < 0.5))


def test_the_parser_never_raises_and_never_returns_arguments_that_break_the_schema():
    rng = random.Random(20261101)
    counts = {"tool": 0, "final": 0, "error": 0}
    for _ in range(3000):
        text = build(rng)
        result = parse_action(text, ALL_TOOLS)  # must not raise
        if isinstance(result, ToolAction):
            counts["tool"] += 1
            assert result.name in BY_NAME
            assert Draft202012Validator(BY_NAME[result.name].parameters).is_valid(result.arguments), (text, result)
            assert isinstance(result.arguments, dict) and isinstance(result.prose, str)
        elif isinstance(result, FinalAction):
            counts["final"] += 1
            assert isinstance(result.text, str)
        else:
            assert isinstance(result, ActionError) and result.message and len(result.message) < 1200, text
            counts["error"] += 1
    # the generator exercises every outcome, so the property above is not vacuous
    assert counts["tool"] > 100 and counts["final"] > 20 and counts["error"] > 500, counts


def test_valid_actions_always_parse_back_to_themselves():
    rng = random.Random(7)
    checked = 0
    for _ in range(2000):
        action = random_action(rng)
        tool = BY_NAME.get(action["tool"]) if "tool" in action else None
        if tool is None or not isinstance(action["arguments"], dict):
            continue
        if not Draft202012Validator(tool.parameters).is_valid(action["arguments"]):
            continue
        result = parse_action(json.dumps(action, ensure_ascii=rng.random() < 0.5), ALL_TOOLS)
        assert isinstance(result, ToolAction) and (result.name, result.arguments) == (action["tool"], action["arguments"])
        checked += 1
    assert checked > 100
