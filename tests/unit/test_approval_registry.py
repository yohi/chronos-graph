"""Unit tests for PendingApprovalRegistry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from mcp_gateway.approval.models import DecisionStatus, ResolveOutcome
from mcp_gateway.approval.notifier import ApprovalRequest
from mcp_gateway.approval.registry import PendingApprovalRegistry
from mcp_gateway.errors import PolicyError


def _req(sid: str = "s1", agent: str = "agent-a") -> ApprovalRequest:
    return ApprovalRequest(
        session_id=sid,
        agent_id=agent,
        intent="curate_memories",
        tool_name="memory_delete",
        arguments={},
        requested_at=datetime.now(UTC),
    )


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_returns_unique_approval_id(self) -> None:
        reg = PendingApprovalRegistry()
        a = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        b = await reg.register(session_id="s2", requester_agent_id="agent-a", request=_req("s2"))
        assert a != b
        assert len(a) == 32

    @pytest.mark.asyncio
    async def test_register_raises_policy_error_on_overflow(self) -> None:
        reg = PendingApprovalRegistry(max_pending=1)
        await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        with pytest.raises(PolicyError, match="approval_registry_full"):
            await reg.register(session_id="s2", requester_agent_id="agent-a", request=_req("s2"))


class TestWaitForDecision:
    @pytest.mark.asyncio
    async def test_returns_approved_when_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        outcome = await reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED)
        assert outcome is ResolveOutcome.OK
        d = await reg.wait_for_decision(aid, timeout=0.1)
        assert d.status is DecisionStatus.APPROVED

    @pytest.mark.asyncio
    async def test_returns_rejected_when_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        await reg.resolve(
            aid,
            resolver_agent_id="op",
            status=DecisionStatus.REJECTED,
            reason="policy violation",
        )
        d = await reg.wait_for_decision(aid, timeout=0.1)
        assert d.status is DecisionStatus.REJECTED
        assert d.reason == "policy violation"

    @pytest.mark.asyncio
    async def test_times_out(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        d = await reg.wait_for_decision(aid, timeout=0.05)
        assert d.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_unknown_id_raises_keyerror(self) -> None:
        reg = PendingApprovalRegistry()
        with pytest.raises(KeyError):
            await reg.wait_for_decision("does-not-exist", timeout=0.05)


class TestResolve:
    @pytest.mark.asyncio
    async def test_unknown_id_returns_not_found(self) -> None:
        reg = PendingApprovalRegistry()
        outcome = await reg.resolve("nope", resolver_agent_id="op", status=DecisionStatus.APPROVED)
        assert outcome is ResolveOutcome.NOT_FOUND

    @pytest.mark.asyncio
    async def test_already_resolved_returns_already_resolved(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        first = await reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED)
        second = await reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.REJECTED)
        assert first is ResolveOutcome.OK
        assert second is ResolveOutcome.ALREADY_RESOLVED

    @pytest.mark.asyncio
    async def test_self_approval_returns_forbidden(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(
            session_id="s1", requester_agent_id="agent-a", request=_req(agent="agent-a")
        )
        outcome = await reg.resolve(
            aid, resolver_agent_id="agent-a", status=DecisionStatus.APPROVED
        )
        assert outcome is ResolveOutcome.FORBIDDEN
        d = await reg.wait_for_decision(aid, timeout=0.05)
        assert d.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_concurrent_resolve_is_safe(self) -> None:
        reg = PendingApprovalRegistry()
        aid = await reg.register(session_id="s1", requester_agent_id="agent-a", request=_req())
        results = await asyncio.gather(
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
            reg.resolve(aid, resolver_agent_id="op", status=DecisionStatus.APPROVED),
        )
        ok_count = sum(1 for r in results if r is ResolveOutcome.OK)
        already_count = sum(1 for r in results if r is ResolveOutcome.ALREADY_RESOLVED)
        assert ok_count == 1
        assert already_count == 2


class TestCancelSession:
    @pytest.mark.asyncio
    async def test_rejects_pending(self) -> None:
        reg = PendingApprovalRegistry()
        aid_s1_a = await reg.register(
            session_id="s1", requester_agent_id="agent-a", request=_req("s1")
        )
        aid_s1_b = await reg.register(
            session_id="s1", requester_agent_id="agent-b", request=_req("s1", "agent-b")
        )
        aid_s2 = await reg.register(
            session_id="s2", requester_agent_id="agent-a", request=_req("s2")
        )

        await reg.cancel_session("s1")

        d_a = await reg.wait_for_decision(aid_s1_a, timeout=0.05)
        d_b = await reg.wait_for_decision(aid_s1_b, timeout=0.05)
        assert d_a.status is DecisionStatus.REJECTED
        assert d_b.status is DecisionStatus.REJECTED

        d_c = await reg.wait_for_decision(aid_s2, timeout=0.05)
        assert d_c.status is DecisionStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_idempotent_for_unknown_sid(self) -> None:
        reg = PendingApprovalRegistry()
        await reg.cancel_session("unknown")
