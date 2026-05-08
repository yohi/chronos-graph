"""In-memory registry of pending approvals (asyncio.Event based)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from mcp_gateway.approval.models import ApprovalDecision, DecisionStatus, ResolveOutcome
from mcp_gateway.approval.notifier import ApprovalRequest
from mcp_gateway.errors import PolicyError


@dataclass(slots=True)
class _Pending:
    event: asyncio.Event
    session_id: str
    requester_agent_id: str
    request: ApprovalRequest
    decision: ApprovalDecision | None = None


class PendingApprovalRegistry:
    """asyncio.Event-backed map of approval_id -> pending entry."""

    def __init__(self, *, max_pending: int = 1000) -> None:
        if max_pending <= 0:
            raise ValueError(f"max_pending must be positive, got {max_pending}")
        self._lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._max_pending = max_pending

    async def register(
        self,
        *,
        session_id: str,
        requester_agent_id: str,
        request: ApprovalRequest,
    ) -> str:
        async with self._lock:
            if len(self._pending) >= self._max_pending:
                raise PolicyError("approval_registry_full")
            approval_id = uuid.uuid4().hex
            self._pending[approval_id] = _Pending(
                event=asyncio.Event(),
                session_id=session_id,
                requester_agent_id=requester_agent_id,
                request=request,
            )
            return approval_id

    async def wait_for_decision(self, approval_id: str, *, timeout: float) -> ApprovalDecision:
        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                raise KeyError(approval_id)
            event = entry.event

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                self._pending.pop(approval_id, None)
            return ApprovalDecision(status=DecisionStatus.TIMEOUT)

        async with self._lock:
            entry = self._pending.pop(approval_id, None)
        if entry is None or entry.decision is None:
            return ApprovalDecision(status=DecisionStatus.TIMEOUT)
        return entry.decision

    async def resolve(
        self,
        approval_id: str,
        *,
        resolver_agent_id: str,
        status: DecisionStatus,
        reason: str | None = None,
    ) -> ResolveOutcome:
        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                return ResolveOutcome.NOT_FOUND
            if entry.decision is not None:
                return ResolveOutcome.ALREADY_RESOLVED
            if resolver_agent_id == entry.requester_agent_id:
                return ResolveOutcome.FORBIDDEN
            entry.decision = ApprovalDecision(status=status, reason=reason)
            entry.event.set()
            return ResolveOutcome.OK

    async def cancel_session(self, session_id: str) -> None:
        async with self._lock:
            for entry in self._pending.values():
                if entry.session_id == session_id and entry.decision is None:
                    entry.decision = ApprovalDecision(
                        status=DecisionStatus.REJECTED,
                        reason="session_evicted",
                    )
                    entry.event.set()
