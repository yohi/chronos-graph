"""RL 拡張ポイント (Extension Protocols + NoOp 実装) のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_store.extensions.noop import (
    NoOpActionLogger,
    NoOpPolicyHook,
    NoOpRewardSignal,
)
from context_store.extensions.protocols import (
    ActionLogger,
    AgentAction,
    PolicyHook,
    RewardSignal,
)
from context_store.models.search import SearchStrategy

# ---------------------------------------------------------------------------
# AgentAction
# ---------------------------------------------------------------------------


class TestAgentAction:
    def test_create_with_required_fields(self) -> None:
        action = AgentAction(action_type="save")
        assert action.action_type == "save"

    def test_optional_fields_have_defaults(self) -> None:
        action = AgentAction(action_type="search")
        assert action.memory_id is None
        assert action.query is None
        assert action.metadata == {}
        assert action.timestamp is not None

    def test_create_with_all_fields(self) -> None:
        ts = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)
        action = AgentAction(
            action_type="search",
            memory_id="mem-123",
            query="検索クエリ",
            metadata={"project": "test"},
            timestamp=ts,
        )
        assert action.action_type == "search"
        assert action.memory_id == "mem-123"
        assert action.query == "検索クエリ"
        assert action.metadata == {"project": "test"}
        assert action.timestamp == ts


# ---------------------------------------------------------------------------
# Protocol 準拠チェック (ランタイム duck typing)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_noop_action_logger_conforms_to_protocol(self) -> None:
        logger = NoOpActionLogger()
        assert isinstance(logger, ActionLogger)

    def test_noop_reward_signal_conforms_to_protocol(self) -> None:
        reward = NoOpRewardSignal()
        assert isinstance(reward, RewardSignal)

    def test_noop_policy_hook_conforms_to_protocol(self) -> None:
        hook = NoOpPolicyHook()
        assert isinstance(hook, PolicyHook)


# ---------------------------------------------------------------------------
# NoOpActionLogger
# ---------------------------------------------------------------------------


class TestNoOpActionLogger:
    @pytest.mark.asyncio
    async def test_log_action_does_nothing_and_returns_none(self) -> None:
        logger = NoOpActionLogger()
        action = AgentAction(action_type="save", memory_id="mem-abc")
        result = await logger.log_action(action)
        assert result is None

    @pytest.mark.asyncio
    async def test_log_action_multiple_calls_do_not_raise(self) -> None:
        logger = NoOpActionLogger()
        for action_type in ("save", "search", "delete", "prune"):
            action = AgentAction(action_type=action_type)
            await logger.log_action(action)  # should not raise


# ---------------------------------------------------------------------------
# NoOpRewardSignal
# ---------------------------------------------------------------------------


class TestNoOpRewardSignal:
    @pytest.mark.asyncio
    async def test_record_reward_does_nothing_and_returns_none(self) -> None:
        reward = NoOpRewardSignal()
        result = await reward.record_reward(
            memory_id="mem-123",
            signal=1.0,
            context={"query": "テスト"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_record_reward_accepts_negative_signal(self) -> None:
        reward = NoOpRewardSignal()
        # should not raise even with negative or zero signal
        await reward.record_reward(memory_id="mem-456", signal=-0.5, context={})
        await reward.record_reward(memory_id="mem-789", signal=0.0, context={})


# ---------------------------------------------------------------------------
# NoOpPolicyHook
# ---------------------------------------------------------------------------


class TestNoOpPolicyHook:
    @pytest.mark.asyncio
    async def test_adjust_strategy_returns_base_strategy_unchanged(self) -> None:
        hook = NoOpPolicyHook()
        base = SearchStrategy(
            vector_weight=0.5,
            keyword_weight=0.2,
            graph_weight=0.3,
            graph_depth=3,
            time_decay_enabled=False,
        )
        result = await hook.adjust_strategy(query="テスト", base_strategy=base)
        assert result is base

    @pytest.mark.asyncio
    async def test_adjust_strategy_does_not_modify_strategy(self) -> None:
        hook = NoOpPolicyHook()
        base = SearchStrategy(
            vector_weight=0.2,
            keyword_weight=0.6,
            graph_weight=0.2,
        )
        result = await hook.adjust_strategy(query="エラーメッセージ", base_strategy=base)
        assert result.vector_weight == 0.2
        assert result.keyword_weight == 0.6
        assert result.graph_weight == 0.2
