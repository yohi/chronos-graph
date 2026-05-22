from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import cast

from mcp_gateway.policy.models_evaluator import Decision

logger = logging.getLogger("chronos_evaluator.llm")

__all__ = ["LlmUnavailableError", "ResponseParseError", "_parse_decision"]

_REASON_MAX = 200
_ASK_MESSAGE_MAX = 300


class LlmUnavailableError(Exception):
    pass


class ResponseParseError(Exception):
    pass


def _parse_decision(text: str) -> Decision:
    stripped = text.strip()
    if not stripped.startswith("{") or not stripped.endswith("}"):
        raise ResponseParseError(f"non-JSON response: {stripped[:80]!r}")

    try:
        parsed = cast(object, json.loads(stripped))
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ResponseParseError(f"top-level must be object, got {type(parsed).__name__}")

    obj = cast(Mapping[str, object], parsed)
    decision = obj.get("decision")
    if decision == "allow":
        return Decision(decision="allow")
    if decision == "deny":
        reason = obj.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ResponseParseError("deny requires non-empty 'reason'")
        return Decision(decision="deny", reason=reason[:_REASON_MAX])
    if decision == "ask":
        ask_message = obj.get("ask_message")
        if not isinstance(ask_message, str) or not ask_message.strip():
            raise ResponseParseError("ask requires non-empty 'ask_message'")
        return Decision(decision="ask", ask_message=ask_message[:_ASK_MESSAGE_MAX])

    raise ResponseParseError(f"unknown decision: {decision!r}")
