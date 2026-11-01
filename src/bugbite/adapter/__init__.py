"""Model adapter: one provider-neutral interface for talking to any model."""

from bugbite.adapter.base import ModelAdapter, estimate_tokens, validate_request
from bugbite.adapter.claude import ClaudeAdapter
from bugbite.adapter.cost import CallCost, compute_cost, format_usd, worst_case_cost
from bugbite.adapter.ledger import CallRecord, CostLedger, ModelTotals
from bugbite.adapter.metered import MeteredAdapter
from bugbite.adapter.openai_compatible import OpenAICompatibleAdapter
from bugbite.adapter.registry import (
    create_adapter,
    register_adapter,
    registered_providers,
    unregister_adapter,
)
from bugbite.adapter.text_action import INVALID_ACTION, PROMPT_VERSION, TextActionAdapter, TextActionStats, parse_action
from bugbite.adapter.types import (
    ROLE_ASSISTANT,
    ROLE_USER,
    SCHEMA_VERSION,
    STOP_END_TURN,
    STOP_MAX_TOKENS,
    STOP_OTHER,
    STOP_REASONS,
    STOP_REFUSAL,
    STOP_SEQUENCE,
    STOP_TOOL_USE,
    Block,
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

__all__ = [
    "Block",
    "INVALID_ACTION",
    "PROMPT_VERSION",
    "TextActionAdapter",
    "TextActionStats",
    "parse_action",
    "CallCost",
    "CallRecord",
    "CostLedger",
    "MeteredAdapter",
    "ModelTotals",
    "compute_cost",
    "format_usd",
    "worst_case_cost",
    "ClaudeAdapter",
    "GenerationRequest",
    "GenerationResponse",
    "Message",
    "ModelAdapter",
    "OpenAICompatibleAdapter",
    "ROLE_ASSISTANT",
    "ROLE_USER",
    "SCHEMA_VERSION",
    "STOP_END_TURN",
    "STOP_MAX_TOKENS",
    "STOP_OTHER",
    "STOP_REASONS",
    "STOP_REFUSAL",
    "STOP_SEQUENCE",
    "STOP_TOOL_USE",
    "SchemaError",
    "TextBlock",
    "ToolCallBlock",
    "ToolDefinition",
    "ToolResultBlock",
    "Usage",
    "create_adapter",
    "estimate_tokens",
    "register_adapter",
    "registered_providers",
    "unregister_adapter",
    "validate_request",
]
