"""Tool use for models that cannot call tools natively.

The model is told to answer every turn with one JSON action; this wrapper parses and validates
it, asks for one repair when it is wrong, and turns the result into the same tool call a native
model would have produced, so callers never see the difference (AD-070 to AD-075).

Model output is untrusted data: nothing here may raise on any reply, and no tool call leaves
this module with arguments that break the tool's schema, apart from the deliberate failed
step (`invalid_action`).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Sequence

from jsonschema import Draft202012Validator
from jsonschema import SchemaError as JsonSchemaError
from jsonschema.exceptions import best_match

from bugbite.adapter._http import shorten
from bugbite.adapter.base import ModelAdapter, validate_request
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    STOP_END_TURN,
    STOP_MAX_TOKENS,
    STOP_REFUSAL,
    STOP_TOOL_USE,
    GenerationRequest,
    GenerationResponse,
    Message,
    TextBlock,
    ToolCallBlock,
    ToolDefinition,
    ToolResultBlock,
    Usage,
)
from bugbite.errors import INVALID_REQUEST, AdapterError

PROMPT_VERSION = "1"  # bump whenever the instruction text changes: it changes model behaviour
INVALID_ACTION = "invalid_action"  # the name of the tool call that stands for a failed step
MAX_FAILED_REPLY_CHARS = 1000
MAX_ERROR_CHARS = 300
_MAX_LISTED_TOOLS = 20


# -- parsing ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolAction:
    name: str
    arguments: dict[str, Any]
    prose: str  # whatever the model wrote around the JSON


@dataclass(frozen=True)
class FinalAction:
    text: str
    prose: str


@dataclass(frozen=True)
class ActionError:
    message: str  # specific and short: it goes straight into the repair prompt


Parsed = ToolAction | FinalAction | ActionError


def _prose(text: str, start: int, end: int) -> str:
    """The reply without the action itself and without bare code-fence lines."""
    rest = text[:start] + "\n" + text[end:]
    kept = [line for line in rest.splitlines() if line.strip().lower() not in ("```", "```json")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


_LOOKS_LIKE_ACTION = re.compile(r"""["']?(tool|final)["']?\s*:""")


def _json_objects(text: str) -> tuple[list[tuple[int, int, Any]], tuple[int, json.JSONDecodeError] | None]:
    """Every top-level JSON object in the text, and the first place a `{` failed to parse."""
    decoder = json.JSONDecoder()
    found: list[tuple[int, int, Any]] = []
    failure: tuple[int, json.JSONDecodeError] | None = None
    position = 0
    while True:
        start = text.find("{", position)
        if start == -1:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError as exc:
            failure = failure or (start, exc)
            position = start + 1
            continue
        except RecursionError:  # absurdly deep nesting is just another unusable reply
            position = start + 1
            continue
        found.append((start, end, value))
        position = end
    return found, failure


def _tool_names(tools: Sequence[ToolDefinition]) -> str:
    names = [t.name for t in tools][:_MAX_LISTED_TOOLS]
    return ", ".join(names) + (", ..." if len(tools) > _MAX_LISTED_TOOLS else "")


def _check_arguments(tool: ToolDefinition, arguments: dict[str, Any]) -> str | None:
    error = best_match(Draft202012Validator(tool.parameters).iter_errors(arguments))
    if error is None:
        return None
    path = ".".join(["arguments", *[str(part) for part in error.absolute_path]])
    return shorten(f"{path}: {error.message}", MAX_ERROR_CHARS)


def parse_action(text: str, tools: Sequence[ToolDefinition], *, truncated: bool = False) -> Parsed:
    """Find the one action in a reply and check it. Never raises, whatever the text contains."""
    if not isinstance(text, str):
        return ActionError("The reply was empty.")
    cut_off = " The reply was cut off by the output limit; keep it short." if truncated else ""
    objects, failure = _json_objects(text)

    candidates = [(s, e, v) for s, e, v in objects if isinstance(v, dict) and ("tool" in v or "final" in v)]
    distinct: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for start, end, value in candidates:
        distinct.setdefault(json.dumps(value, sort_keys=True, default=str), (start, end, value))

    if not distinct:
        if failure is not None and _LOOKS_LIKE_ACTION.search(text, failure[0]):
            # A broken attempt at an action. Say what is wrong with the JSON, not that "no action" was
            # found (a half-parsed inner object, such as the arguments, may have been decoded on its own).
            _, exc = failure
            return ActionError(f"The JSON could not be parsed: {exc.msg} (line {exc.lineno}, column {exc.colno})." + cut_off)
        if objects:
            return ActionError('The JSON has no action: it needs a "tool" key (to call a tool) or a "final" key (to finish).' + cut_off)
        return ActionError("No JSON action was found in the reply." + cut_off)
    if len(distinct) > 1:
        return ActionError(f"The reply holds {len(distinct)} different actions; reply with exactly one.")

    start, end, action = next(iter(distinct.values()))
    prose = _prose(text, start, end)
    if "tool" in action and "final" in action:
        return ActionError('An action needs either "tool" or "final", not both.')

    if "final" in action:
        if not isinstance(action["final"], str):
            return ActionError('"final" must be text.')
        return FinalAction(text=action["final"], prose=prose)

    name = action["tool"]
    if not isinstance(name, str) or not name:
        return ActionError('"tool" must be the name of a tool, as text.')
    tool = next((t for t in tools if t.name == name), None)
    if tool is None:
        return ActionError(f'Unknown tool "{shorten(name, 60)}". The available tools are: {_tool_names(tools)}.')
    arguments = action.get("arguments", {})
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return ActionError('"arguments" must be a JSON object.')
    problem = _check_arguments(tool, arguments)
    if problem:
        return ActionError(f'Invalid arguments for "{name}": {problem}')
    return ToolAction(name=name, arguments=arguments, prose=prose)


# -- the instruction prompt -----------------------------------------------------------------------


def _example_value(schema: Any) -> Any:
    kind = schema.get("type") if isinstance(schema, dict) else None
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if isinstance(schema, dict) and schema.get("enum"):
        return schema["enum"][0]
    return {"string": "...", "integer": 0, "number": 0, "boolean": True, "array": [], "object": {}}.get(kind, "...")


def _example_arguments(tool: ToolDefinition) -> dict[str, Any]:
    properties = tool.parameters.get("properties", {})
    required = tool.parameters.get("required", [])
    return {name: _example_value(properties.get(name, {})) for name in required if isinstance(name, str)}


def instruction_text(tools: Sequence[ToolDefinition]) -> str:
    lines = [
        f"HOW TO USE TOOLS (format version {PROMPT_VERSION})",
        "You work by writing actions. Every reply must contain exactly ONE JSON action; never write two."
        " You may write a short line of reasoning before the action.",
        "",
        "Available tools:",
    ]
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")
        lines.append(f"  arguments (JSON Schema): {json.dumps(tool.parameters, ensure_ascii=False, separators=(',', ':'))}")
    first = tools[0]
    lines += [
        "",
        "To call a tool, reply with:",
        '{"tool": "<tool name>", "arguments": {<arguments>}}',
        f"For example: {json.dumps({'tool': first.name, 'arguments': _example_arguments(first)}, ensure_ascii=False)}",
        "",
        "When you are finished, reply with:",
        '{"final": "<your final answer>"}',
        "",
        "Rules: use only the tools listed above and only the arguments they define; after a tool call you will"
        " receive its result in the next message; reply with one action per message.",
    ]
    return "\n".join(lines)


# -- turning a tool conversation into plain text -------------------------------------------------------


def _render_action(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"tool": name, "arguments": arguments}, ensure_ascii=False)


def _count_calls(messages: Sequence[Message]) -> int:
    return sum(1 for m in messages for b in m.blocks if isinstance(b, ToolCallBlock))


def text_request(request: GenerationRequest) -> GenerationRequest:
    """The same conversation with no tools: calls and results become text the model can follow."""
    names = {b.id: b.name for m in request.messages for b in m.blocks if isinstance(b, ToolCallBlock)}
    messages: list[Message] = []
    for message in request.messages:
        blocks: list[TextBlock] = []
        if message.role == ROLE_ASSISTANT:
            texts = [b for b in message.blocks if isinstance(b, TextBlock) and b.text]
            calls = [b for b in message.blocks if isinstance(b, ToolCallBlock)]
            valid_calls = [c for c in calls if c.name != INVALID_ACTION]
            blocks.extend(texts)
            blocks.extend(TextBlock(_render_action(c.name, c.arguments)) for c in valid_calls)
            if not calls:  # a plain answer is shown in the format the model must use to give one
                joined = "\n".join(b.text for b in texts)
                blocks = [TextBlock(json.dumps({"final": joined}, ensure_ascii=False))]
            elif not blocks:
                blocks = [TextBlock("(no valid action)")]
        else:
            for block in message.blocks:
                if isinstance(block, ToolResultBlock):
                    name = names.get(block.tool_call_id, "a tool")
                    if name == INVALID_ACTION:
                        blocks.append(TextBlock(f"Your previous reply was not a valid action: {block.content}\nReply with exactly one JSON action."))
                        continue
                    label = f"[result of {name} call {block.tool_call_id}]"
                    blocks.append(TextBlock(f"{label}\n{'ERROR: ' if block.is_error else ''}{block.content}"))
            blocks.extend(b for b in message.blocks if isinstance(b, TextBlock) and b.text)
            if not blocks:
                blocks = [TextBlock("(empty)")]
        messages.append(Message(message.role, tuple(blocks)))
    return GenerationRequest(
        messages=tuple(messages),
        system=(*request.system, TextBlock(instruction_text(request.tools))),
        tools=(),
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        stop_sequences=request.stop_sequences,
    )


def _repair_request(base: GenerationRequest, failed_reply: str, problem: str, tools: Sequence[ToolDefinition]) -> GenerationRequest:
    reply = shorten(failed_reply, MAX_FAILED_REPLY_CHARS) if failed_reply.strip() else "(empty reply)"
    nudge = (
        f"Your reply could not be used: {problem}\n"
        'Reply again with exactly one JSON action: {"tool": "<name>", "arguments": {...}} or {"final": "<answer>"}. '
        f"Available tools: {_tool_names(tools)}."
    )
    return GenerationRequest(
        messages=(*base.messages, Message.assistant(reply), Message.user(nudge)),
        system=base.system,
        tools=(),
        temperature=base.temperature,
        max_output_tokens=base.max_output_tokens,
        stop_sequences=base.stop_sequences,
    )


# -- the wrapper ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TextActionStats:
    steps: int  # model steps that used tools
    repaired_steps: int  # steps that needed the repair call and then succeeded
    failed_steps: int  # steps that stayed invalid after the repair


def _combine(calls: list[GenerationResponse], blocks: tuple[Any, ...], stop_reason: str) -> GenerationResponse:
    last = calls[-1]
    usage = Usage(
        input_tokens=sum(c.usage.input_tokens for c in calls),
        output_tokens=sum(c.usage.output_tokens for c in calls),
        cache_read_tokens=sum(c.usage.cache_read_tokens for c in calls),
        cache_write_tokens=sum(c.usage.cache_write_tokens for c in calls),
    )
    return GenerationResponse(
        blocks=blocks,
        stop_reason=stop_reason,
        usage=usage,
        model=last.model,
        raw_stop_reason=last.raw_stop_reason,
        latency_s=sum(c.latency_s for c in calls),
        request_id=last.request_id,
        usage_estimated=any(c.usage_estimated for c in calls),
    )


class TextActionAdapter(ModelAdapter):
    """Gives any adapter tool calling through text. Meter the inner adapter, not this one (AD-074)."""

    max_calls_per_step = 2  # the original call plus at most one repair

    def __init__(self, inner: ModelAdapter) -> None:
        super().__init__(inner.config)
        self._inner = inner
        self._lock = threading.Lock()
        self._steps = self._repaired = self._failed = 0

    @property
    def inner(self) -> ModelAdapter:
        return self._inner

    @property
    def stats(self) -> TextActionStats:
        with self._lock:
            return TextActionStats(self._steps, self._repaired, self._failed)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def estimate_tokens(self, request: GenerationRequest) -> int:
        """The size of what is actually sent, including the instruction block."""
        return self._inner.estimate_tokens(text_request(request) if request.tools else request)

    def __repr__(self) -> str:
        return f"TextActionAdapter({self._inner!r})"

    # -- the call -------------------------------------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        validate_request(request)
        if not request.tools:
            return self._inner.generate(request)  # nothing to convert: a plain text exchange
        for tool in request.tools:
            try:
                Draft202012Validator.check_schema(tool.parameters)
            except JsonSchemaError as exc:
                raise AdapterError(INVALID_REQUEST, f"Tool '{tool.name}' has an invalid parameter schema: {shorten(exc.message, 200)}") from None

        call_id = f"ta_{_count_calls(request.messages) + 1}"
        base = text_request(request)
        first = self._inner.generate(base)
        with self._lock:
            self._steps += 1
        if first.stop_reason == STOP_REFUSAL:
            return first

        parsed = parse_action(first.text, request.tools, truncated=first.stop_reason == STOP_MAX_TOKENS)
        if not isinstance(parsed, ActionError):
            return self._success(call_id, [first], parsed)

        second = self._inner.generate(_repair_request(base, first.text, parsed.message, request.tools))
        if second.stop_reason == STOP_REFUSAL:
            return _combine([first, second], second.blocks, STOP_REFUSAL)
        again = parse_action(second.text, request.tools, truncated=second.stop_reason == STOP_MAX_TOKENS)
        if not isinstance(again, ActionError):
            with self._lock:
                self._repaired += 1
            return self._success(call_id, [first, second], again)

        with self._lock:
            self._failed += 1
        reply = shorten(second.text, MAX_FAILED_REPLY_CHARS) if second.text.strip() else ""
        call = ToolCallBlock(call_id, INVALID_ACTION, {}, shorten(f"The reply was not a valid action: {again.message}", MAX_ERROR_CHARS))
        blocks: tuple[Any, ...] = (TextBlock(reply), call) if reply else (call,)
        return _combine([first, second], blocks, STOP_TOOL_USE)

    @staticmethod
    def _success(call_id: str, calls: list[GenerationResponse], parsed: ToolAction | FinalAction) -> GenerationResponse:
        if isinstance(parsed, FinalAction):
            text = parsed.text if parsed.text else parsed.prose
            return _combine(calls, (TextBlock(text),) if text else (), STOP_END_TURN)
        blocks: list[Any] = [TextBlock(parsed.prose)] if parsed.prose else []
        blocks.append(ToolCallBlock(call_id, parsed.name, parsed.arguments))
        return _combine(calls, tuple(blocks), STOP_TOOL_USE)
