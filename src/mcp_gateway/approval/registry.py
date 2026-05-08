"""In-memory registry of pending approvals (asyncio.Event based)."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass

from mcp_gateway.approval.models import ApprovalDecision, DecisionStatus, ResolveOutcome
from mcp_gateway.approval.notifier import ApprovalRequest
from mcp_gateway.approval.sanitize import sanitize_reason
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
        self._recent_ids: deque[str] = deque(maxlen=max_pending)
        self._recent_decisions: dict[str, ApprovalDecision] = {}
        self._max_pending = max_pending

    def _add_to_history(self, approval_id: str, decision: ApprovalDecision) -> None:
        if approval_id in self._recent_decisions:
            return
        if len(self._recent_ids) >= self._max_pending:
            oldest = self._recent_ids.popleft()
            self._recent_decisions.pop(oldest, None)
        self._recent_ids.append(approval_id)
        self._recent_decisions[approval_id] = decision

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

    async def wait_for_decision(
        self,
        approval_id: str,
        *,
        timeout: float,
        started_event: asyncio.Event | None = None,
    ) -> ApprovalDecision:
        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                if approval_id in self._recent_decisions:
                    return self._recent_decisions[approval_id]
                return ApprovalDecision(
                    status=DecisionStatus.REJECTED,
                    reason="not_found_or_evicted",
                )
            event = entry.event

        try:
            if started_event:
                started_event.set()
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                entry = self._pending.pop(approval_id, None)
                if entry and entry.decision:
                    # タイムアウト検知〜ロック取得の間に他タスクで resolve されていた場合
                    self._add_to_history(approval_id, entry.decision)
                    return entry.decision
                self._add_to_history(approval_id, ApprovalDecision(status=DecisionStatus.TIMEOUT))
            return ApprovalDecision(status=DecisionStatus.TIMEOUT)
        except asyncio.CancelledError:
            async with self._lock:
                entry = self._pending.pop(approval_id, None)
                if entry and entry.decision:
                    self._add_to_history(approval_id, entry.decision)
            raise

        async with self._lock:
            # cancel_session 等で既に pop されている可能性がある
            self._pending.pop(approval_id, None)
            # wait_for が正常終了した場合、entry.decision はセットされているはず
            if entry.decision:
                self._add_to_history(approval_id, entry.decision)

        if entry.decision is None:
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
        if status not in (DecisionStatus.APPROVED, DecisionStatus.REJECTED):
            return ResolveOutcome.INVALID_STATUS

        async with self._lock:
            entry = self._pending.get(approval_id)
            if entry is None:
                if approval_id in self._recent_decisions:
                    return ResolveOutcome.ALREADY_RESOLVED
                return ResolveOutcome.NOT_FOUND
            if entry.decision is not None:
                return ResolveOutcome.ALREADY_RESOLVED
            if resolver_agent_id == entry.requester_agent_id:
                return ResolveOutcome.FORBIDDEN
            entry.decision = ApprovalDecision(status=status, reason=sanitize_reason(reason))
            entry.event.set()
            return ResolveOutcome.OK

    async def cancel_session(self, session_id: str, reason: str = "session_evicted") -> None:
        async with self._lock:
            to_cancel = [
                aid
                for aid, entry in self._pending.items()
                if entry.session_id == session_id and entry.decision is None
            ]
            sanitized = sanitize_reason(reason)
            for aid in to_cancel:
                entry = self._pending.pop(aid)
                decision = ApprovalDecision(
                    status=DecisionStatus.REJECTED,
                    reason=sanitized,
                )
                entry.decision = decision
                self._add_to_history(aid, decision)
                entry.event.set()
