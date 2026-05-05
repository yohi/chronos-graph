"""HITL approval notifier: abstract base + log-only stub implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    session_id: str
    agent_id: str
    intent: str
    tool_name: str
    arguments: dict[str, Any]
    requested_at: datetime


class ApprovalNotifier(ABC):
    @abstractmethod
    async def request_approval(self, req: ApprovalRequest) -> None: ...


class LogOnlyApprovalNotifier(ApprovalNotifier):
    async def request_approval(self, req: ApprovalRequest) -> None:
        # TODO: Slack Webhook / CIBA event queue への送信に差し替える
        logger.info(
            "approval_required sid=%s agent=%s intent=%s tool=%s args=%r requested_at=%s",
            req.session_id,
            req.agent_id,
            req.intent,
            req.tool_name,
            req.arguments,
            req.requested_at.isoformat(),
        )
