"""Orchestrator のユニットテスト。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.extensions.noop import NoOpActionLogger, NoOpPolicyHook, NoOpRewardSignal
from context_store.models.memory import SourceType
from context_store.models.search import SearchStrategy
from tests.unit.conftest import make_settings

# graph=None を明示的に渡すためのセンチネル
_UNSET = object()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_storage(vector_dim: int | None = None) -> MagicMock:
    """StorageAdapter モックを生成する。"""
    storage = AsyncMock()
    storage.get_vector_dimension = AsyncMock(return_value=vector_dim)
    storage.delete_memory = AsyncMock(return_value=True)
    storage.list_by_filter = AsyncMock(return_value=[])
    storage.dispose = AsyncMock()
    return storage


def _make_mock_graph() -> MagicMock:
    """GraphAdapter モックを生成する。"""
    graph = AsyncMock()
    graph.delete_node = AsyncMock()
    graph.dispose = AsyncMock()
    return graph


def _make_mock_cache() -> MagicMock:
    """CacheAdapter モックを生成する。"""
    cache = AsyncMock()
    cache.invalidate = AsyncMock()
    cache.dispose = AsyncMock()
    return cache


def _make_mock_embedding(dimension: int = 1536) -> MagicMock:
    """EmbeddingProvider モックを生成する。"""
    embedding = MagicMock()
    embedding.dimension = dimension
    embedding.embed = AsyncMock(return_value=[0.1] * dimension)
    return embedding


def _make_mock_ingestion_pipeline() -> MagicMock:
    """IngestionPipeline モックを生成する。"""
    from context_store.ingestion.deduplicator import DeduplicationAction
    from context_store.ingestion.pipeline import IngestionResult

    pipeline = AsyncMock()
    pipeline.ingest = AsyncMock(
        return_value=[
            IngestionResult(
                memory_id="test-id-1",
                action=DeduplicationAction.INSERT,
            )
        ]
    )
    return pipeline


def _make_mock_retrieval_pipeline() -> MagicMock:
    """RetrievalPipeline モックを生成する。"""
    pipeline = AsyncMock()
    pipeline.search = AsyncMock(
        return_value={
            "query": "test",
            "results": [],
            "total_count": 0,
            "strategy": {},
        }
    )
    return pipeline


def _make_mock_lifecycle_manager() -> MagicMock:
    """LifecycleManager モックを生成する。"""
    manager = AsyncMock()
    manager.start = AsyncMock()
    manager.on_memory_saved = AsyncMock()
    manager.graceful_shutdown = AsyncMock()
    manager.run_cleanup = AsyncMock()
    return manager


def _make_mock_task_registry() -> MagicMock:
    """TaskRegistry モックを生成する。"""
    registry = AsyncMock()
    registry.register = MagicMock()
    registry.cancel_all = AsyncMock()
    registry.__len__ = MagicMock(return_value=0)
    return registry


async def _build_orchestrator(
    *,
    storage=None,
    graph=_UNSET,
    cache=None,
    embedding=None,
    ingestion_pipeline=None,
    retrieval_pipeline=None,
    lifecycle_manager=None,
    task_registry=_UNSET,
    action_logger=None,
    reward_signal=None,
    policy_hook=None,
    settings=None,
    batch_processor=_UNSET,
):
    """Orchestrator を依存性注入でビルドするヘルパー。

    graph, batch_processor, task_registry に None を明示的に渡すと、
    その機能が無効な状態として扱う。省略(_UNSET)した場合はデフォルトのモックを使用する。
    """
    from context_store.orchestrator import Orchestrator

    storage = storage or _make_mock_storage()
    graph = _make_mock_graph() if graph is _UNSET else graph
    cache = cache or _make_mock_cache()
    embedding = embedding or _make_mock_embedding()
    ingestion_pipeline = ingestion_pipeline or _make_mock_ingestion_pipeline()
    retrieval_pipeline = retrieval_pipeline or _make_mock_retrieval_pipeline()
    lifecycle_manager = lifecycle_manager or _make_mock_lifecycle_manager()
    task_registry = _make_mock_task_registry() if task_registry is _UNSET else task_registry
    settings = settings or make_settings()
    batch_processor = AsyncMock() if batch_processor is _UNSET else batch_processor

    orch = Orchestrator(
        storage=storage,
        graph=graph,
        cache=cache,
        embedding_provider=embedding,
        ingestion_pipeline=ingestion_pipeline,
        retrieval_pipeline=retrieval_pipeline,
        lifecycle_manager=lifecycle_manager,
        task_registry=task_registry,
        action_logger=action_logger,
        reward_signal=reward_signal,
        policy_hook=policy_hook,
        settings=settings,
        batch_processor=batch_processor,
    )
    # フェイルファストチェック(次元不一致時は ConfigurationError を raise)
    await orch._check_vector_dimension()
    return (
        orch,
        storage,
        graph,
        cache,
        embedding,
        ingestion_pipeline,
        retrieval_pipeline,
        lifecycle_manager,
        task_registry,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrchestratorCreation:
    """Orchestrator の生成テスト。"""

    @pytest.mark.asyncio
    async def test_orchestrator_creates_with_defaults(self):
        """デフォルト引数(RL フック未指定)で Orchestrator を生成できる。"""
        orch, *_ = await _build_orchestrator()
        assert orch is not None
        assert isinstance(orch.action_logger, NoOpActionLogger)
        assert isinstance(orch.reward_signal, NoOpRewardSignal)
        assert isinstance(orch.policy_hook, NoOpPolicyHook)

    @pytest.mark.asyncio
    async def test_orchestrator_accepts_custom_rl_hooks(self):
        """カスタム RL フックを注入できる。"""
        custom_logger = NoOpActionLogger()
        custom_reward = NoOpRewardSignal()
        custom_policy = NoOpPolicyHook()

        orch, *_ = await _build_orchestrator(
            action_logger=custom_logger,
            reward_signal=custom_reward,
            policy_hook=custom_policy,
        )
        assert orch.action_logger is custom_logger
        assert orch.reward_signal is custom_reward
        assert orch.policy_hook is custom_policy


class TestDimensionCheck:
    """ベクトル次元フェイルファストチェックのテスト。"""

    @pytest.mark.asyncio
    async def test_dimension_mismatch_raises_configuration_error(self):
        """stored_dim != current_dim の場合 ConfigurationError を raise する。"""
        from context_store.orchestrator import ConfigurationError

        storage = _make_mock_storage(vector_dim=512)
        embedding = _make_mock_embedding(dimension=1536)

        with pytest.raises(ConfigurationError) as exc_info:
            await _build_orchestrator(
                storage=storage,
                embedding=embedding,
            )
        error_msg = str(exc_info.value)
        # リカバリ手順がメッセージに含まれることを確認
        assert "SQLITE_DB_PATH" in error_msg or "migrate_dimension" in error_msg

    @pytest.mark.asyncio
    async def test_dimension_mismatch_error_contains_recovery_hints(self):
        """ConfigurationError メッセージにリカバリ手順が含まれる。"""
        from context_store.orchestrator import ConfigurationError

        storage = _make_mock_storage(vector_dim=768)
        embedding = _make_mock_embedding(dimension=1536)

        with pytest.raises(ConfigurationError) as exc_info:
            await _build_orchestrator(storage=storage, embedding=embedding)

        msg = str(exc_info.value)
        assert "migrate_dimension" in msg

    @pytest.mark.asyncio
    async def test_dimension_unknown_logs_warning_and_continues(self, caplog):
        """stored_dim=None の場合は警告ログを出力して続行する(初回起動)。"""
        storage = _make_mock_storage(vector_dim=None)
        embedding = _make_mock_embedding(dimension=1536)

        with caplog.at_level(logging.WARNING, logger="context_store.orchestrator"):
            orch, *_ = await _build_orchestrator(storage=storage, embedding=embedding)

        assert orch is not None
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("dimension" in msg.lower() or "次元" in msg for msg in warning_messages)

    @pytest.mark.asyncio
    async def test_dimension_match_proceeds_without_error(self):
        """stored_dim == current_dim の場合はエラーなく続行する。"""
        storage = _make_mock_storage(vector_dim=1536)
        embedding = _make_mock_embedding(dimension=1536)

        orch, *_ = await _build_orchestrator(storage=storage, embedding=embedding)
        assert orch is not None


class TestSaveOperation:
    """save() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_save_delegates_to_ingestion_pipeline(self):
        """save() が IngestionPipeline.ingest() に委譲される。"""
        ingestion = _make_mock_ingestion_pipeline()
        orch, *_, _lifecycle_manager = await _build_orchestrator(ingestion_pipeline=ingestion)

        results = await orch.save("test content", source_type=SourceType.MANUAL)

        ingestion.ingest.assert_called_once()
        call_kwargs = ingestion.ingest.call_args
        assert call_kwargs[0][0] == "test content"
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_save_calls_lifecycle_on_memory_saved(self):
        """save() 後に LifecycleManager.on_memory_saved() が呼ばれる。"""
        ingestion = _make_mock_ingestion_pipeline()
        lifecycle = _make_mock_lifecycle_manager()
        orch, *_ = await _build_orchestrator(
            ingestion_pipeline=ingestion, lifecycle_manager=lifecycle
        )

        await orch.save("test content")

        lifecycle.on_memory_saved.assert_called()

    @pytest.mark.asyncio
    async def test_save_url_delegates_to_ingestion_pipeline(self):
        """save_url() が IngestionPipeline.ingest() に URL ソースタイプで委譲される。"""
        ingestion = _make_mock_ingestion_pipeline()
        orch, *_ = await _build_orchestrator(ingestion_pipeline=ingestion)

        await orch.save_url("https://example.com/page")

        ingestion.ingest.assert_called_once()
        call_args = ingestion.ingest.call_args
        assert call_args[0][0] == "https://example.com/page"
        assert call_args[1].get("source_type") == SourceType.URL


class TestSearchOperation:
    """search() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_search_delegates_to_retrieval_pipeline(self):
        """search() が RetrievalPipeline.search() に委譲される。"""
        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(retrieval_pipeline=retrieval)

        result = await orch.search("test query")

        retrieval.search.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_passes_parameters_to_pipeline(self):
        """search() がパラメータを RetrievalPipeline.search() に渡す。"""
        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(retrieval_pipeline=retrieval)

        await orch.search("test query", project="my-project", top_k=5, max_tokens=1000)

        call_kwargs = retrieval.search.call_args[1]
        assert call_kwargs.get("project") == "my-project"
        assert call_kwargs.get("top_k") == 5
        assert call_kwargs.get("max_tokens") == 1000

    @pytest.mark.asyncio
    async def test_rl_hooks_called_on_search(self):
        """PolicyHook が search() 時に呼ばれる。"""
        policy_hook = AsyncMock()
        policy_hook.adjust_strategy = AsyncMock(
            side_effect=lambda q, s: s  # そのまま返す
        )
        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(retrieval_pipeline=retrieval, policy_hook=policy_hook)

        await orch.search("test query")

        policy_hook.adjust_strategy.assert_called_once()
        call_args = policy_hook.adjust_strategy.call_args
        assert call_args[0][0] == "test query"
        assert isinstance(call_args[0][1], SearchStrategy)

    @pytest.mark.asyncio
    async def test_adjusted_strategy_is_computed_from_policy_hook(self):
        """PolicyHook.adjust_strategy() が返した戦略が
        RetrievalPipeline.search() に渡されること。
        """
        custom_strategy = SearchStrategy(vector_weight=0.8, keyword_weight=0.1, graph_weight=0.1)
        policy_hook = AsyncMock()
        policy_hook.adjust_strategy = AsyncMock(return_value=custom_strategy)

        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(retrieval_pipeline=retrieval, policy_hook=policy_hook)

        await orch.search("test query")

        # PolicyHook が正しい引数で呼ばれ、adjusted_strategy が返されたことを確認
        policy_hook.adjust_strategy.assert_called_once()
        call_args = policy_hook.adjust_strategy.call_args[0]
        assert call_args[0] == "test query"
        assert isinstance(call_args[1], SearchStrategy)

        # RetrievalPipeline.search() に custom_strategy が渡されたことを確認
        retrieval.search.assert_called_once()
        search_kwargs = retrieval.search.call_args.kwargs
        assert "strategy" in search_kwargs
        assert search_kwargs["strategy"] is custom_strategy


class TestSearchGraphOperation:
    """search_graph() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_search_graph_raises_when_graph_is_none(self):
        """グラフが無効(graph=None)の場合 RuntimeError を raise する。"""
        orch, *_ = await _build_orchestrator(graph=None)

        with pytest.raises(RuntimeError) as exc_info:
            await orch.search_graph("test query")

        assert "グラフ機能が無効" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_graph_delegates_to_retrieval_pipeline(self):
        """グラフが有効な場合 RetrievalPipeline.search() に委譲される。

        注意: edge_types と depth は現時点では RetrievalPipeline に渡されない。
        Phase 9 で graph_traversal に委譲される予定(orchestrator.py の TODO 参照)。
        """
        graph = _make_mock_graph()
        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(graph=graph, retrieval_pipeline=retrieval)

        result = await orch.search_graph("test query", depth=2)

        retrieval.search.assert_called_once()
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_graph_passes_project_to_retrieval_pipeline(self):
        """search_graph() が project パラメータを RetrievalPipeline.search() に渡す。"""
        graph = _make_mock_graph()
        retrieval = _make_mock_retrieval_pipeline()
        orch, *_ = await _build_orchestrator(graph=graph, retrieval_pipeline=retrieval)

        await orch.search_graph("test query", project="my-project")

        call_kwargs = retrieval.search.call_args[1]
        assert call_kwargs.get("project") == "my-project"


class TestDeleteOperation:
    """delete() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_delete_delegates_to_storage_adapter(self):
        """delete() が StorageAdapter.delete_memory() に委譲される。"""
        storage = _make_mock_storage()
        orch, *_ = await _build_orchestrator(storage=storage)

        await orch.delete("memory-id-123")

        storage.delete_memory.assert_called_once_with("memory-id-123")

    @pytest.mark.asyncio
    async def test_delete_also_invalidates_cache(self):
        """delete() がキャッシュも無効化する。"""
        storage = _make_mock_storage()
        cache = _make_mock_cache()
        orch, *_ = await _build_orchestrator(storage=storage, cache=cache)

        await orch.delete("memory-id-123")

        cache.invalidate.assert_called()

    @pytest.mark.asyncio
    async def test_delete_also_removes_graph_node(self):
        """delete() がグラフノードも削除する。"""
        storage = _make_mock_storage()
        graph = _make_mock_graph()
        orch, *_ = await _build_orchestrator(storage=storage, graph=graph)

        await orch.delete("memory-id-123")

        graph.delete_node.assert_called_once_with("memory-id-123")

    @pytest.mark.asyncio
    async def test_delete_invalidates_cache_even_if_graph_fails(self, caplog):
        """グラフノードの削除が失敗してもキャッシュが無効化されること。"""
        storage = _make_mock_storage()
        graph = _make_mock_graph()
        graph.delete_node.side_effect = Exception("Graph error")
        cache = _make_mock_cache()
        orch, *_ = await _build_orchestrator(storage=storage, graph=graph, cache=cache)

        with caplog.at_level(logging.ERROR):
            await orch.delete("memory-id-123")

        # グラフ削除が失敗しても、キャッシュ無効化が呼ばれていること
        cache.invalidate.assert_called_once_with("memory-id-123")
        # エラーログが出力されていること
        assert "Failed to delete node from graph" in caplog.text


class TestPruneOperation:
    """prune() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_prune_calls_lifecycle_run_cleanup(self):
        """prune() が LifecycleManager.run_cleanup() に委譲される。"""
        lifecycle = _make_mock_lifecycle_manager()
        orch, *_ = await _build_orchestrator(lifecycle_manager=lifecycle)

        await orch.prune(older_than_days=30, dry_run=False)

        lifecycle.run_cleanup.assert_called()

    @pytest.mark.asyncio
    async def test_prune_dry_run_calls_run_cleanup_preview(self):
        """prune(dry_run=True) は run_cleanup() を preview モードで呼び出す。"""
        lifecycle = _make_mock_lifecycle_manager()
        lifecycle.run_cleanup = AsyncMock(return_value=10)
        orch, *_ = await _build_orchestrator(lifecycle_manager=lifecycle)

        result = await orch.prune(older_than_days=30, dry_run=True)

        lifecycle.run_cleanup.assert_called_once_with(older_than_days=30, dry_run=True)
        assert result == 10


class TestStatsOperation:
    """stats() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_stats_returns_dict(self):
        """stats() が dict を返す。"""
        storage = _make_mock_storage()
        storage.list_by_filter = AsyncMock(return_value=[])
        orch, *_ = await _build_orchestrator(storage=storage)

        result = await orch.stats()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_stats_with_project_filter(self):
        """stats(project=...) がプロジェクトフィルタで動作する。"""
        storage = _make_mock_storage()
        storage.list_by_filter = AsyncMock(return_value=[])
        orch, *_ = await _build_orchestrator(storage=storage)

        result = await orch.stats(project="my-project")

        assert isinstance(result, dict)


class TestDisposeOperation:
    """dispose() 操作のテスト。"""

    @pytest.mark.asyncio
    async def test_dispose_calls_adapters(self):
        """dispose() が全アダプターの dispose() を呼び出す。"""
        storage = _make_mock_storage()
        graph = _make_mock_graph()
        cache = _make_mock_cache()
        lifecycle = _make_mock_lifecycle_manager()
        orch, *_ = await _build_orchestrator(
            storage=storage, graph=graph, cache=cache, lifecycle_manager=lifecycle
        )

        await orch.dispose()

        storage.dispose.assert_called_once()
        graph.dispose.assert_called_once()
        cache.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispose_calls_lifecycle_graceful_shutdown(self):
        """dispose() が LifecycleManager.graceful_shutdown() を呼び出す。"""
        lifecycle = _make_mock_lifecycle_manager()
        orch, *_ = await _build_orchestrator(lifecycle_manager=lifecycle)

        await orch.dispose()

        lifecycle.graceful_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispose_calls_task_registry_cancel_all(self):
        """dispose() が TaskRegistry.cancel_all() を呼び出す。"""
        task_registry = _make_mock_task_registry()
        orch, *_ = await _build_orchestrator(task_registry=task_registry)

        await orch.dispose()

        task_registry.cancel_all.assert_called_once()


class TestSessionFlush:
    """session_flush() のテスト。"""

    @pytest.mark.asyncio
    async def test_session_flush_accepted(self):
        """正常系: タスクが受理され、レジストリに登録される。"""
        task_registry = _make_mock_task_registry()
        batch_processor = AsyncMock()
        batch_processor.estimate_chunks = AsyncMock(return_value=5)

        orch, *_ = await _build_orchestrator(
            task_registry=task_registry,
            batch_processor=batch_processor,
        )

        resp = await orch.session_flush("test log")

        assert resp["status"] == "accepted"
        assert resp["estimated_chunks"] == 5
        task_registry.register.assert_called_once()
        batch_processor.estimate_chunks.assert_called_once_with("test log")

        # 登録されたタスクを取得して待機し、クリーンアップする
        task = task_registry.register.call_args[0][0]
        await task

    @pytest.mark.asyncio
    async def test_session_flush_empty_log_returns_error(self):
        """バリデーション: 空のログはエラー。"""
        orch, *_ = await _build_orchestrator()
        resp = await orch.session_flush("")
        assert "error" in resp
        assert "empty" in resp["error"]

    @pytest.mark.asyncio
    async def test_session_flush_too_long_log_returns_error(self):
        """バリデーション: 長すぎるログはエラー。"""
        settings = make_settings()
        settings.session_flush_max_log_length = 10
        orch, *_ = await _build_orchestrator(settings=settings)

        resp = await orch.session_flush("this is too long")
        assert "error" in resp
        assert "exceeds maximum length" in resp["error"]

    @pytest.mark.asyncio
    async def test_session_flush_concurrency_limit(self):
        """同時実行数制限: max_jobs を超えるとエラー。"""
        settings = make_settings()
        settings.batch_max_concurrent_jobs = 1
        task_registry = _make_mock_task_registry()
        task_registry.__len__ = MagicMock(return_value=1)  # すでに1つ実行中

        orch, *_ = await _build_orchestrator(
            settings=settings,
            task_registry=task_registry,
            batch_processor=AsyncMock(),
        )

        resp = await orch.session_flush("test log")
        assert "error" in resp
        assert "Too many concurrent jobs" in resp["error"]

    @pytest.mark.asyncio
    async def test_session_flush_not_configured(self):
        """BatchProcessor または TaskRegistry が未設定の場合エラー。"""
        # TaskRegistry が None のケース
        orch, *_ = await _build_orchestrator(task_registry=None)
        resp = await orch.session_flush("test log")
        assert "error" in resp
        assert "not configured" in resp["error"]

        # BatchProcessor が None のケース
        orch, *_ = await _build_orchestrator(batch_processor=None)
        resp = await orch.session_flush("test log")
        assert "error" in resp
        assert "not configured" in resp["error"]

    @pytest.mark.asyncio
    async def test_session_flush_calls_batch_processor(self):
        """session_flush() が BatchProcessor.process() を呼び出す。"""
        task_registry = _make_mock_task_registry()
        batch_processor = AsyncMock()
        batch_processor.process = AsyncMock(return_value=True)
        batch_processor.estimate_chunks = AsyncMock(return_value=1)

        orch, *_ = await _build_orchestrator(
            task_registry=task_registry,
            batch_processor=batch_processor,
        )

        # session_flush を実行
        await orch.session_flush("test log", session_id="sess-123")

        # 登録されたタスクを取得して実行
        task = task_registry.register.call_args[0][0]
        await task

        # BatchProcessor.process が正しく呼ばれたことを確認
        batch_processor.process.assert_called_once_with(
            "test log",
            session_id="sess-123",
            project=None,
            tags=None,
        )
