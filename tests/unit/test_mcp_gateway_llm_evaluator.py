from __future__ import annotations

import pytest

from mcp_gateway.policy.llm_evaluator import ResponseParseError, _parse_decision
from mcp_gateway.policy.models_evaluator import Decision


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"decision":"allow"}', Decision(decision="allow")),
        ('  {"decision": "allow"}  ', Decision(decision="allow")),
    ],
)
def test_parse_allow(text: str, expected: Decision) -> None:
    assert _parse_decision(text) == expected


def test_parse_deny_with_reason() -> None:
    out = _parse_decision('{"decision":"deny","reason":"forbidden command"}')
    assert out == Decision(decision="deny", reason="forbidden command")


def test_parse_ask_with_message() -> None:
    out = _parse_decision('{"decision":"ask","ask_message":"please confirm"}')
    assert out == Decision(decision="ask", ask_message="please confirm")


def test_parse_truncates_long_reason() -> None:
    long_reason = "x" * 500
    out = _parse_decision(f'{{"decision":"deny","reason":"{long_reason}"}}')
    assert out.reason is not None
    assert len(out.reason) <= 200


def test_parse_truncates_long_ask_message() -> None:
    long_message = "x" * 500
    out = _parse_decision(f'{{"decision":"ask","ask_message":"{long_message}"}}')
    assert out.ask_message is not None
    assert len(out.ask_message) <= 300


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"decision":"maybe"}',
        '{"decision":"deny"}',
        '{"decision":"deny","reason":"   "}',
        '{"decision":"ask"}',
    ],
)
def test_parse_rejects_invalid(text: str) -> None:
    with pytest.raises(ResponseParseError):
        _ = _parse_decision(text)
