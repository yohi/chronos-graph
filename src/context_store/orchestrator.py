"""Orchestrator - ChronosGraph MCP システムのメインファサード。

Settings から各アダプター・パイプラインを束ね、外部への操作インターフェースを提供する。
RL 拡張フックを受け取り、None の場合は NoOp 実装を使用する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from context_store.extensions.noop import NoOpActionLogger, NoOpPolicyHook, NoOpRewardSignal
from context_store.models.memory import SourceType
from context_store.models.search import SearchStrategy
from context_store.storage.protocols import MemoryFilters

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.embedding.protocols import EmbeddingProvider
    from context_store.extensions.protocols import ActionLogger, PolicyHook, RewardSignal
    from context_store.ingestion.pipeline import IngestionPipeline, IngestionResult
    from context_store.ingestion.task_registry import TaskRegistry
    from context_store.lifecycle.manager import LifecycleManager
    from context_store.retrieval.pipeline import RetrievalPipeline, RetrievalResponse
    from context_store.storage.protocols import CacheAdapter, GraphAdapter, StorageAdapter

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """設定エラー。ベクトル次元の不一致などを示す。"""


class Orchestrator:
    """ChronosGraph MCP システムのメインファサード。

    各アダプター・パイプラインを束ね、操作を委譲する。

    Args:
        storage: ストレージアダプター。
        graph: グラフアダプター（None の場合はグラフ機能無効）。
        cache: キャッシュアダプター。
        embedding_provider: 埋め込みプロバイダー。
        ingestion_pipeline: 取り込みパイプライン。
        retrieval_pipeline: 検索パイプライン。
        lifecycle_manager: ライフサイクルマネージャー。
        task_registry: タスクレジストリ。
        action_logger: RL 拡張: アクションロガー（None の場合は NoOp）。
        reward_signal: RL 拡張: 報酬シグナル（None の場合は NoOp）。
        policy_hook: RL 拡張: 検索戦略フック（None の場合は NoOp）。
        settings: アプリケーション設定。
    """

    def __init__(
        self,
        storage: "StorageAdapter",
        graph: "GraphAdapter | None",
        cache: "CacheAdapter",
        embedding_provider: "EmbeddingProvider",
        ingestion_pipeline: "IngestionPipeline",
        retrieval_pipeline: "RetrievalPipeline",
        lifecycle_manager: "LifecycleManager",
        task_registry: "TaskRegistry",
        action_logger: "ActionLogger | None" = None,
        reward_signal: "RewardSignal | None" = None,
        policy_hook: "PolicyHook | None" = None,
        settings: "Settings | None" = None,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._cache = cache
        self._embedding_provider = embedding_provider
        self._ingestion_pipeline = ingestion_pipeline
        self._retrieval_pipeline = retrieval_pipeline
        self._lifecycle_manager = lifecycle_manager
        self._task_registry = task_registry
        self._settings = settings

        # RL 拡張フック（None の場合は NoOp）
        self.action_logger: "ActionLogger" = (
            action_logger if action_logger is not None else NoOpActionLogger()
        )
        self.reward_signal: "RewardSignal" = (
            reward_signal if reward_signal is not None else NoOpRewardSignal()
        )
        self.policy_hook: "PolicyHook" = (
            policy_hook if policy_hook is not None else NoOpPolicyHook()
        )

    async def _check_vector_dimension(self) -> None:
        """ストレージに保存されたベクトル次元と現在の次元を比較する。

        - stored_dim が None の場合は初回起動として警告ログを出して続行する。
        - stored_dim != current_dim の場合は ConfigurationError を raise する。
        """
        stored_dim = await self._storage.get_vector_dimension()
        current_dim = self._embedding_provider.dimension

        if stored_dim is None:
            logger.warning(
                "ベクトル次元が不明です（stored_dim=None）。"
                "初回起動の場合は正常です。現在の dimension=%d を使用します。",
                current_dim,
            )
            return

        if stored_dim != current_dim:
            raise ConfigurationError(
                f"ベクトル次元の不一致が検出されました: ストレージ内の次元={stored_dim}, "
                f"現在の embedding provider の次元={current_dim}。\n"
                "このまま起動すると既存のベクトルデータと互換性がなくなります。\n\n"
                "リカバリ手順:\n"
                "  1. 別環境として開始する場合:\n"
                "     SQLite: SQLITE_DB_PATH 環境変数を新しいパスに変更する\n"
                "     PostgreSQL: 別の DB 名（postgres_db）を指定して新しい DB を作成する\n"
                "  2. 既存データを移行する場合:\n"
                "     python scripts/migrate_dimension.py を実行する\n"
                "  3. 全データを初期化する場合:\n"
                "     SQLite: DB ファイルを手動で削除する\n"
                "     PostgreSQL: スキーマを再構築する（DROP SCHEMA public CASCADE など）\n"
            )

    # ---------------------------------------------------------------------------
    # 操作の委譲
    # ---------------------------------------------------------------------------

    async def save(
        self,
        content: str,
        source_type: SourceType = SourceType.MANUAL,
        metadata: dict[str, Any] | None = None,
    ) -> list["IngestionResult"]:
        """テキストコンテンツを保存する。

        Args:
            content: 保存するテキスト。
            source_type: ソース種別。
            metadata: 付加メタデータ。

        Returns:
            IngestionResult のリスト。
        """
        results = await self._ingestion_pipeline.ingest(
            content, source_type=source_type, metadata=metadata
        )
        await self._lifecycle_manager.on_memory_saved()
        return results

    async def save_url(
        self,
        url: str,
        metadata: dict[str, Any] | None = None,
    ) -> list["IngestionResult"]:
        """URL からコンテンツを取得して保存する。

        Args:
            url: 取得する URL。
            metadata: 付加メタデータ。

        Returns:
            IngestionResult のリスト。
        """
        results = await self._ingestion_pipeline.ingest(
            url, source_type=SourceType.URL, metadata=metadata
        )
        await self._lifecycle_manager.on_memory_saved()
        return results

    async def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        top_k: int = 10,
        max_tokens: int | None = None,
    ) -> RetrievalResponse:
        """コンテキストを検索する。

        PolicyHook.adjust_strategy() を通して検索戦略を調整してから
        RetrievalPipeline.search() に委譲する。

        Args:
            query: 検索クエリ。
            project: プロジェクトフィルタ。
            memory_type: 記憶種別フィルタ（"episodic", "semantic", "procedural"）。
                現時点では RetrievalPipeline がこのパラメータをサポートしていないため
                WARNING ログを出して無視する。将来の拡張のために受け取る。
            top_k: 返す最大件数。
            max_tokens: 最大トークン数。

        Returns:
            検索結果の dict。
        """
        if memory_type is not None:
            logger.warning(
                "memory_type=%r が指定されましたが、現時点では RetrievalPipeline が "
                "このパラメータをサポートしていないため無視されます。"
                "将来の RetrievalPipeline 拡張時に有効化される予定です。",
                memory_type,
            )

        base_strategy = SearchStrategy()
        adjusted_strategy = await self.policy_hook.adjust_strategy(query, base_strategy)

        result = await self._retrieval_pipeline.search(
            query,
            project=project,
            top_k=top_k,
            max_tokens=max_tokens,
            strategy=adjusted_strategy,
        )
        return result

    async def search_graph(
        self,
        query: str,
        edge_types: list[str] | None = None,
        depth: int = 2,
        project: str | None = None,
    ) -> RetrievalResponse:
        """グラフトラバーサル検索を実行する。

        Args:
            query: 起点となるクエリ（ベクトル検索で起点ノードを特定）。
            edge_types: フィルタするエッジ種別（None で全種別）。
            depth: トラバーサル深さ。
            project: プロジェクトフィルタ。

        Returns:
            グラフ検索結果の dict。

        Raises:
            RuntimeError: グラフが無効な場合。
        """
        if self._graph is None:
            raise RuntimeError("グラフ機能が無効です。graph_enabled=true を設定してください。")

        if edge_types or depth != 2:
            logger.warning(
                "グラフトラバーサル検索は現在開発中です。edge_types=%r, depth=%d は無視され、"
                "代わりに標準の検索（top_k=5）が実行されます。",
                edge_types,
                depth,
            )
        # TODO(Phase 9): edge_types と depth を RetrievalPipeline の graph_traversal に渡す。
        # 現時点ではベクトル検索でシードノードを特定し、グラフアダプターへの委譲は未実装。
        search_result = await self._retrieval_pipeline.search(query, project=project, top_k=5)
        return search_result

    async def delete(self, memory_id: str) -> bool:
        """記憶を削除する。

        StorageAdapter.delete_memory()、GraphAdapter.delete_node()、
        CacheAdapter.invalidate() を順に呼び出す。

        Args:
            memory_id: 削除する記憶の ID。

        Returns:
            削除成功時は True。
        """
        deleted = await self._storage.delete_memory(memory_id)
        try:
            if self._graph is not None:
                await self._graph.delete_node(memory_id)
        except Exception as e:
            logger.error("Failed to delete node from graph for memory %s: %s", memory_id, e)
        finally:
            await self._cache.invalidate(memory_id)
        return deleted

    async def prune(
        self,
        older_than_days: int = 90,
        dry_run: bool = False,
    ) -> int:
        """古い記憶を削除する。

        SQLite バックエンド以外（Postgres, Redis, In-Memory等）では
        ライフサイクル状態ストアが永続化されないため、クリーンアップをスキップする。

        Args:
            older_than_days: この日数より古い記憶を削除対象とする。
            dry_run: True の場合は削除せず対象件数のみを返す。

        Returns:
            削除した（または削除対象の）件数。
        """
        if self._settings is None:
            raise RuntimeError("Orchestrator settings must be initialized before running prune.")

        if self._settings.storage_backend != "sqlite":
            logger.warning(
                "Lifecycle cleanup is only supported for 'sqlite' backend in this version. "
                "Skipping prune for backend: %s",
                self._settings.storage_backend,
            )
            return 0

        # lifecycle_manager.run_cleanup() は削除またはアーカイブされた件数 (int) を返す。
        count: int = await self._lifecycle_manager.run_cleanup(
            older_than_days=older_than_days, dry_run=dry_run
        )
        return count

    async def stats(self, project: str | None = None) -> dict[str, Any]:
        """ストレージの統計情報を返す。

        Args:
            project: プロジェクトフィルタ（None の場合は全体）。

        Returns:
            統計情報の dict。
        """
        active_count = await self._storage.count_by_filter(
            MemoryFilters(project=project, archived=None)
        )
        archived_count = await self._storage.count_by_filter(
            MemoryFilters(project=project, archived=True)
        )
        return {
            "active_count": active_count,
            "archived_count": archived_count,
            "total_count": active_count + archived_count,
            "project": project,
        }

    async def list_projects(self) -> list[str]:
        """プロジェクト一覧を返す。"""
        return await self._storage.list_projects()

    @property
    def url_fetch_concurrency(self) -> int:
        """URL フェッチの同時実行数を返す。"""
        if self._settings is None:
            return 1
        return self._settings.url_fetch_concurrency

    async def start_lifecycle(self) -> None:
        """ライフサイクルマネージャーを開始する。"""
        await self._lifecycle_manager.start()

    async def dispose(self) -> None:
        """全アダプターのリソースを解放する。"""
        # まずライフサイクルマネージャーを終了させ、タスクの完了を待機する
        await self._lifecycle_manager.graceful_shutdown()

        # 残っているバックグラウンドタスクがあればキャンセル (5s タイムアウト)
        await self._task_registry.cancel_all(timeout=5.0)

        await self._storage.dispose()
        if self._graph is not None:
            await self._graph.dispose()
        await self._cache.dispose()


# ---------------------------------------------------------------------------
# ファクトリ関数
# ---------------------------------------------------------------------------


async def create_orchestrator(
    settings: "Settings",
    action_logger: "ActionLogger | None" = None,
    reward_signal: "RewardSignal | None" = None,
    policy_hook: "PolicyHook | None" = None,
) -> Orchestrator:
    """Settings から Orchestrator を組み立てて返す。

    ベクトル次元フェイルファストチェックも実行する。

    Args:
        settings: アプリケーション設定。
        action_logger: RL 拡張: アクションロガー。
        reward_signal: RL 拡張: 報酬シグナル。
        policy_hook: RL 拡張: 検索戦略フック。

    Returns:
        初期化済み Orchestrator。

    Raises:
        ConfigurationError: ベクトル次元が不一致の場合。
    """
    from context_store.embedding import create_embedding_provider
    from context_store.ingestion.pipeline import IngestionPipeline
    from context_store.ingestion.task_registry import TaskRegistry
    from context_store.lifecycle.archiver import Archiver
    from context_store.lifecycle.consolidator import Consolidator
    from context_store.lifecycle.decay_scorer import DecayScorer
    from context_store.lifecycle.manager import (
        InMemoryLifecycleStateStore,
        LifecycleManager,
        SQLiteLifecycleStateStore,
    )
    from context_store.lifecycle.purger import Purger
    from context_store.retrieval.graph_traversal import GraphTraversal
    from context_store.retrieval.keyword_search import KeywordSearch
    from context_store.retrieval.pipeline import RetrievalPipeline
    from context_store.retrieval.post_processor import PostProcessor
    from context_store.retrieval.query_analyzer import QueryAnalyzer
    from context_store.retrieval.result_fusion import ResultFusion
    from context_store.retrieval.vector_search import VectorSearch
    from context_store.storage.factory import create_storage

    # アダプター生成
    storage, graph, cache = await create_storage(settings)

    try:
        # 埋め込みプロバイダー生成
        embedding_provider = create_embedding_provider(settings)

        # IngestionPipeline 組み立て
        ingestion_pipeline = IngestionPipeline(
            storage=storage,
            graph=graph,
            embedding_provider=embedding_provider,
            settings=settings,
        )

        # RetrievalPipeline 組み立て
        query_analyzer = QueryAnalyzer()
        vector_search = VectorSearch(
            embedding_provider=embedding_provider,
            storage_adapter=storage,
        )
        keyword_search = KeywordSearch(storage_adapter=storage)
        graph_traversal = GraphTraversal(
            graph_adapter=graph,
            default_depth=settings.graph_max_logical_depth,
            fanout_limit=settings.graph_fanout_limit,
            max_physical_hops=settings.graph_max_physical_hops,
        )
        result_fusion = ResultFusion()
        post_processor = PostProcessor(storage_adapter=storage)
        retrieval_pipeline = RetrievalPipeline(
            query_analyzer=query_analyzer,
            vector_search=vector_search,
            keyword_search=keyword_search,
            graph_traversal=graph_traversal,
            result_fusion=result_fusion,
            post_processor=post_processor,
            storage_adapter=storage,
        )

        # LifecycleManager 組み立て
        if settings.storage_backend == "sqlite":
            import os

            db_path = os.path.expanduser(settings.sqlite_db_path)
            state_store: InMemoryLifecycleStateStore | SQLiteLifecycleStateStore
            if db_path == ":memory:":
                state_store = InMemoryLifecycleStateStore()
            else:
                state_store = SQLiteLifecycleStateStore(
                    db_path=db_path,
                    stale_lock_timeout_seconds=settings.stale_lock_timeout_seconds,
                )
        else:
            state_store = InMemoryLifecycleStateStore()

        decay_scorer = DecayScorer(settings=settings)
        archiver = Archiver(storage=storage, scorer=decay_scorer)
        consolidator = Consolidator(
            storage=storage,
            graph=graph,
            embedding_provider=embedding_provider,
            dedup_threshold=settings.dedup_threshold,
            consolidation_threshold=settings.consolidation_threshold,
        )
        purger = Purger(
            storage=storage,
            graph=graph,
            retention_days=settings.purge_retention_days,
        )
        task_registry = TaskRegistry()
        lifecycle_manager = LifecycleManager(
            state_store=state_store,
            archiver=archiver,
            purger=purger,
            consolidator=consolidator,
            decay_scorer=decay_scorer,
            storage=storage,
            task_registry=task_registry,
            settings=settings,
        )

        # Orchestrator 生成・初期化
        orchestrator = Orchestrator(
            storage=storage,
            graph=graph,
            cache=cache,
            embedding_provider=embedding_provider,
            ingestion_pipeline=ingestion_pipeline,
            retrieval_pipeline=retrieval_pipeline,
            lifecycle_manager=lifecycle_manager,
            task_registry=task_registry,
            action_logger=action_logger,
            reward_signal=reward_signal,
            policy_hook=policy_hook,
            settings=settings,
        )

        # フェイルファストチェック
        await orchestrator._check_vector_dimension()

        return orchestrator

    except Exception:
        # 初期化失敗時は全アダプターのリソースを解放して再送
        await storage.dispose()
        if graph is not None:
            await graph.dispose()
        await cache.dispose()
        raise


__all__ = ["ConfigurationError", "Orchestrator", "create_orchestrator"]
