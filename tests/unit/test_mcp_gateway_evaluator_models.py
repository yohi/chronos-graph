"""Unit tests for evaluator models and redaction utilities."""

from __future__ import annotations

import pytest

from mcp_gateway.policy.models_evaluator import (
    MAX_VALUE_LENGTH,
    REDACTED_MARKER,
    Decision,
    MemoryItem,
    ToolCallInput,
    _redact_tool_input_for_llm,
    _summarize_tool_input,
)


class TestDecisionToDict:
    def test_allow_omits_optional_fields(self) -> None:
        d = Decision(decision="allow")
        assert d.to_dict() == {"decision": "allow"}

    def test_deny_serialises_reason(self) -> None:
        d = Decision(decision="deny", reason="violates rule X")
        assert d.to_dict() == {"decision": "deny", "reason": "violates rule X"}

    def test_ask_serialises_message(self) -> None:
        d = Decision(decision="ask", ask_message="confirm please")
        assert d.to_dict() == {"decision": "ask", "ask_message": "confirm please"}

    def test_ask_without_message_raises(self) -> None:
        with pytest.raises(ValueError, match="ask_message is required"):
            Decision(decision="ask")

    def test_deny_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            Decision(decision="deny")


class TestSummarizeToolInput:
    def test_redacts_sensitive_keys(self) -> None:
        out = _summarize_tool_input({"password": "hunter2", "api_key": "sk-123", "command": "ls"})
        assert f"password={REDACTED_MARKER}" in out
        assert f"api_key={REDACTED_MARKER}" in out
        assert "command=ls" in out

    def test_truncates_long_values(self) -> None:
        long = "a" * (MAX_VALUE_LENGTH + 50)
        out = _summarize_tool_input({"command": long})
        assert "...[truncated]" in out
        # Truncated content + marker should be shorter than original
        assert len(out) < len(long) + len("command=")

    def test_handles_int_value(self) -> None:
        out = _summarize_tool_input({"count": 42})
        assert out == "count=42"


class TestRedactToolInputForLLM:
    def test_preserves_nested_structure(self) -> None:
        out = _redact_tool_input_for_llm({"opts": {"flag": True, "secret": "xxx"}, "command": "ls"})
        assert out == {"opts": {"flag": True, "secret": REDACTED_MARKER}, "command": "ls"}

    def test_redacts_inside_list(self) -> None:
        out = _redact_tool_input_for_llm([{"api_key": "x"}, {"name": "ok"}])
        assert out == [{"api_key": REDACTED_MARKER}, {"name": "ok"}]

    def test_passthrough_primitives(self) -> None:
        assert _redact_tool_input_for_llm(42) == 42
        assert _redact_tool_input_for_llm(None) is None
        assert _redact_tool_input_for_llm(True) is True

    def test_truncates_long_string(self) -> None:
        long = "x" * (MAX_VALUE_LENGTH + 10)
        out = _redact_tool_input_for_llm({"v": long})
        assert isinstance(out["v"], str)
        assert "...[truncated]" in out["v"]


class TestToolCallInput:
    def test_default_context_empty(self) -> None:
        i = ToolCallInput(tool_name="bash", tool_input={"command": "ls"})
        assert i.context == {}


class TestMemoryItem:
    def test_immutable(self) -> None:
        m = MemoryItem(content="x", memory_type="semantic", importance=0.5)
        with pytest.raises(AttributeError):
            m.content = "y"  # type: ignore[misc]
