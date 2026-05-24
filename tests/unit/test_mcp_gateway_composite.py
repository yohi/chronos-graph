"""Tests for CompositeEvaluator Tier 1/2 flow."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.composite import CompositeEvaluator
from mcp_gateway.policy.engine import EvaluationResult, Grant, PolicyEngine
from mcp_gateway.policy.llm_evaluator import LlmUnavailableError, ResponseParseError
from mcp_gateway.policy.memory_client import MemoryFetchError
from mcp_gateway.policy.models_evaluator import Decision, ToolCallInput


def _make_policy_engine_mock(result: EvaluationResult) -> MagicMock:
    eng = MagicMock(spec=PolicyEngine)
    eng.evaluate_grant.return_value = Grant(
        intent="default",
        caps=frozenset(["bash"]),
        output_filter_profile="none",
        guardrails=MappingProxyType({}),
    )
    eng.evaluate_call.return_value = result
    return eng


def _make_evaluator(
    *,
    tier1_result: EvaluationResult,
    llm: MagicMock | None,
    memory: MagicMock | None,
    fallback: str = "allow",
) -> CompositeEvaluator:
    engine = _make_policy_engine_mock(tier1_result)
    return CompositeEvaluator(
        engine=engine,
        memory_client=memory,
        llm_evaluator=llm,
        default_intent="default",
        default_agent_id="claude-code",
        fallback_when_llm_unavailable=fallback,
    )


@pytest.mark.asyncio
async def test_tier1_deny_short_circuits() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock()
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="DENY", reason="forbidden"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "rm -rf /"}))
    assert out == Decision(decision="deny", reason="forbidden")
    llm.judge.assert_not_called()


@pytest.mark.asyncio
async def test_tier1_requires_approval_returns_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock()
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="REQUIRES_APPROVAL", reason="approval"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={}))
    assert out.decision == "ask"
    assert "manual approval" in (out.ask_message or "")
    llm.judge.assert_not_called()


@pytest.mark.asyncio
async def test_allow_with_no_llm_returns_allow_default_fallback() -> None:
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=None,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")


@pytest.mark.asyncio
async def test_allow_with_no_llm_returns_ask_when_fallback_is_ask() -> None:
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=None,
        memory=None,
        fallback="ask",
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_llm_allow_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="allow"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")
    llm.judge.assert_awaited_once()
    kwargs = llm.judge.await_args.kwargs
    assert list(kwargs["memories"]) == []


@pytest.mark.asyncio
async def test_llm_deny_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="deny", reason="dangerous"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "deny"


@pytest.mark.asyncio
async def test_llm_ask_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="ask", ask_message="confirm?"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_memory_fetch_failure_does_not_block_llm() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="allow"))
    memory = MagicMock()
    memory.retrieve = AsyncMock(side_effect=MemoryFetchError("boom"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=memory,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")
    kwargs = llm.judge.await_args.kwargs
    assert list(kwargs["memories"]) == []


@pytest.mark.asyncio
async def test_llm_unavailable_falls_back_to_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(side_effect=LlmUnavailableError("timeout"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"
    assert "System evaluation failed" in (out.ask_message or "")


@pytest.mark.asyncio
async def test_llm_parse_error_falls_back_to_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(side_effect=ResponseParseError("bad json"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_policy_error_on_grant_returns_deny() -> None:
    engine = MagicMock(spec=PolicyEngine)
    engine.evaluate_grant.side_effect = PolicyError("unknown intent", reason="unknown_intent")
    ev = CompositeEvaluator(
        engine=engine,
        memory_client=None,
        llm_evaluator=None,
        default_intent="default",
        default_agent_id="claude-code",
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={}))
    assert out.decision == "deny"
    assert "unknown_intent" in (out.reason or "")


def test_startup_log_emits_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="chronos_evaluator"):
        _make_evaluator(
            tier1_result=EvaluationResult(status="ALLOW"),
            llm=None,
            memory=None,
        )
    assert any("evaluator config" in r.message for r in caplog.records)
