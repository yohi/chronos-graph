"""HITL approval notifier: abstract base + log-only stub implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ApprovalRequest(BaseModel):
    """承認リクエストのデータモデル。"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_id: str
    intent: str
    tool_name: str
    arguments: dict[str, Any]
    requested_at: datetime = Field(default_factory=datetime.now)


class ApprovalNotifier(ABC):
    """承認通知を行うための抽象基底クラス。"""

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest) -> None:
        """承認をリクエストします。"""
        pass


class LogOnlyApprovalNotifier(ApprovalNotifier):
    """ログ出力のみを行う承認通知クラス。"""

    async def request_approval(self, request: ApprovalRequest) -> None:
        """ログに承認が必要な旨を出力します。"""
        # TODO: Slack Webhook / CIBA event queue への送信に差し替える
        logger.info(
            "approval_required sid=%s agent=%s intent=%s tool=%s args=%r requested_at=%s",
            request.session_id,
            request.agent_id,
            request.intent,
            request.tool_name,
            request.arguments,
            request.requested_at.isoformat(),
        )
