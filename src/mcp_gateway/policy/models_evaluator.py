"""Shared data models and redaction utilities for the Universal Evaluator.

This module is imported by composite.py, llm_evaluator.py, memory_client.py,
and cli.py. Importing it must not require any optional dependency (litellm /
httpx); only stdlib + dataclasses is allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|bearer|credential|private[_-]?key|passphrase|\bprivate\b|\bcert\b|\bssh\b)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_REGEX = "|".join(
    (
        r"(?:password|passwd|secret|token|api[_-]?key|authorization|credential)"
        + r"\s*[:=]\s*(?:Bearer\s+)?\S+",
        r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}",
        r"sk-[A-Za-z0-9_-]{8,}",
        r"ghp_[A-Za-z0-9_]{8,}",
        r"xox[baprs]-[A-Za-z0-9-]{8,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    f"({_SENSITIVE_VALUE_REGEX})",
    re.IGNORECASE,
)

MAX_VALUE_LENGTH = 200
REDACTED_MARKER = "<REDACTED>"


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_PATTERN.search(key))


def _truncate(value: str) -> str:
    if len(value) > MAX_VALUE_LENGTH:
        return value[:MAX_VALUE_LENGTH] + "...[truncated]"
    return value


def summarize_tool_input(d: dict[str, Any]) -> str:
    """Build a flat key=value string for memory semantic-search queries.

    Sensitive keys (matching SENSITIVE_KEY_PATTERN) are replaced with REDACTED_MARKER.
    Each value is truncated to MAX_VALUE_LENGTH chars.
    """
    parts: list[str] = []
    for k, v in d.items():
        if _is_sensitive_key(k):
            parts.append(f"{k}={REDACTED_MARKER}")
            continue
        # Recursively redact sensitive keys in nested structures before stringifying
        sanitized_v = _redact_tool_input_for_llm(v)
        parts.append(f"{k}={_truncate(str(sanitized_v))}")
    return " ".join(parts)


# Backwards compatibility alias
_summarize_tool_input = summarize_tool_input


def _redact_tool_input_for_llm(obj: Any) -> Any:
    """Recursively redact sensitive keys and values while preserving the JSON structure."""
    if isinstance(obj, dict):
        return {
            str(k): (
                REDACTED_MARKER if _is_sensitive_key(str(k)) else _redact_tool_input_for_llm(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_tool_input_for_llm(v) for v in obj]
    if isinstance(obj, str):
        # Do not truncate strings here to preserve context for the LLM
        return _SENSITIVE_VALUE_PATTERN.sub(REDACTED_MARKER, obj)
    return obj


@dataclass(frozen=True, slots=True)
class ToolCallInput:
    tool_name: str
    tool_input: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)

    # Contains dict fields, so not hashable
    __hash__ = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class MemoryItem:
    content: str
    memory_type: str
    importance: float


@dataclass(frozen=True, slots=True)
class Decision:
    decision: Literal["allow", "deny", "ask"]
    reason: str | None = None
    ask_message: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in ("allow", "deny", "ask"):
            raise ValueError(
                f"Invalid decision: {self.decision}. Must be 'allow', 'deny', or 'ask'."
            )
        if self.decision == "deny" and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required and must be non-empty for decision=deny")
        if self.decision == "ask" and not (self.ask_message and self.ask_message.strip()):
            raise ValueError("ask_message is required and must be non-empty for decision=ask")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"decision": self.decision}
        if self.decision in ("allow", "deny"):
            if self.reason is not None:
                out["reason"] = self.reason
        elif self.decision == "ask":
            out["ask_message"] = self.ask_message
        return out
