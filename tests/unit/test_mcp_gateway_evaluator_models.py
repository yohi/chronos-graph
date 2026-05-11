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
        with pytest.raises(ValueError, match="ask_message is required"):
            Decision(decision="ask", ask_message="")
        with pytest.raises(ValueError, match="ask_message is required"):
            Decision(decision="ask", ask_message="   ")

    def test_deny_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            Decision(decision="deny")
        with pytest.raises(ValueError, match="reason is required"):
            Decision(decision="deny", reason="")
        with pytest.raises(ValueError, match="reason is required"):
            Decision(decision="deny", reason="   ")

    def test_invalid_decision_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid decision"):
            Decision(decision="invalid")  # type: ignore[arg-type]


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

    def test_redacts_sensitive_keys_in_nested_input(self) -> None:
        # Verify Issue 1: nested sensitive keys are redacted
        secret = "Bearer sk-123"
        out = _summarize_tool_input({"headers": {"authorization": secret}, "cmd": "ls"})
        # Do not rely on exact dict repr: just check that secret is gone and marker is present
        assert secret not in out
        assert REDACTED_MARKER in out
        assert "authorization" in out
        assert "cmd=ls" in out

    def test_redacts_new_sensitive_patterns(self) -> None:
        # Verify Issue 3: new patterns like private_key are redacted
        out = _summarize_tool_input({"private_key": "---BEGIN---", "cert": "trust-me"})
        assert f"private_key={REDACTED_MARKER}" in out
        assert f"cert={REDACTED_MARKER}" in out


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

    def test_no_truncation_for_llm(self) -> None:
        # Verify Issue 4: strings are NOT truncated for LLM input
        long = "x" * (MAX_VALUE_LENGTH + 10)
        out = _redact_tool_input_for_llm({"v": long})
        assert out["v"] == long
        assert "...[truncated]" not in out["v"]


class TestToolCallInput:
    def test_default_context_empty(self) -> None:
        i = ToolCallInput(tool_name="bash", tool_input={"command": "ls"})
        assert i.context == {}

    def test_not_hashable(self) -> None:
        # Verify Issue 2: ToolCallInput is not hashable because it contains dicts
        i = ToolCallInput(tool_name="bash", tool_input={"command": "ls"})
        with pytest.raises(TypeError, match="unhashable type"):
            hash(i)


class TestMemoryItem:
    def test_immutable(self) -> None:
        m = MemoryItem(content="x", memory_type="semantic", importance=0.5)
        with pytest.raises(AttributeError):
            m.content = "y"  # type: ignore[misc]
