"""HITL approval notifier: abstract base + log-only stub implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class ApprovalRequest(BaseModel):
    """承認リクエストのデータモデル。"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    agent_id: str
    intent: str
    tool_name: str
    arguments: Mapping[str, Any]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("arguments", mode="after")
    @classmethod
    def _make_immutable(cls, v: Mapping[str, Any]) -> Mapping[str, Any]:
        """引数を不変（MappingProxyType）に変換します。

        元の辞書への参照を切るため、常に新しい辞書を作成してからラップします。
        """
        return MappingProxyType(dict(v))


def _sanitize_for_log(data: Any) -> Any:
    """ログ出力用に機密情報をマスクします。"""
    sensitive_keys = {"api_key", "token", "secret", "authorization", "password", "email", "ssn"}

    if isinstance(data, (dict, MappingProxyType, Mapping)):
        return {
            str(k): "**********" if str(k).lower() in sensitive_keys else _sanitize_for_log(v)
            for k, v in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [_sanitize_for_log(i) for i in data]
    return data


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
            _sanitize_for_log(request.arguments),
            request.requested_at.isoformat(),
        )
