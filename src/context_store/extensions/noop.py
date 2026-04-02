"""RL 拡張ポイントの NoOp（何もしない）デフォルト実装。

Orchestrator は外部から実装を注入しない限りこれらを使用する。
"""

from __future__ import annotations

from context_store.extensions.protocols import AgentAction
from context_store.models.search import SearchStrategy

__all__ = ["NoOpActionLogger", "NoOpRewardSignal", "NoOpPolicyHook"]


class NoOpActionLogger:
    """行動ログを記録しない ActionLogger の NoOp 実装。"""

    async def log_action(self, action: AgentAction) -> None:
        return None


class NoOpRewardSignal:
    """報酬シグナルを収集しない RewardSignal の NoOp 実装。"""

    async def record_reward(
        self, memory_id: str, signal: float, context: dict
    ) -> None:
        return None


class NoOpPolicyHook:
    """検索戦略を変更しない PolicyHook の NoOp 実装。"""

    async def adjust_strategy(
        self, query: str, base_strategy: SearchStrategy
    ) -> SearchStrategy:
        return base_strategy
