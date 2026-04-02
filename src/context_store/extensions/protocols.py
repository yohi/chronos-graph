"""RL 拡張ポイントのプロトコル定義。

初期実装は行わない。Orchestrator にフックインターフェースとして配置し、
NoOp 実装をデフォルトとして注入する（SPEC.md §10 参照）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from context_store.models.search import SearchStrategy

__all__ = ["AgentAction", "ActionLogger", "RewardSignal", "PolicyHook"]


@dataclass
class AgentAction:
    """エージェントが実行した操作を表すデータクラス。"""

    action_type: str
    memory_id: str | None = None
    query: str | None = None
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@runtime_checkable
class ActionLogger(Protocol):
    """エージェントの行動ログを記録（将来の RL 学習データ源）。"""

    async def log_action(self, action: AgentAction) -> None: ...


@runtime_checkable
class RewardSignal(Protocol):
    """報酬シグナルの収集。"""

    async def record_reward(
        self, memory_id: str, signal: float, context: dict
    ) -> None: ...


@runtime_checkable
class PolicyHook(Protocol):
    """検索戦略の決定に介入するフック（将来のプランナー用）。"""

    async def adjust_strategy(
        self, query: str, base_strategy: SearchStrategy
    ) -> SearchStrategy: ...
