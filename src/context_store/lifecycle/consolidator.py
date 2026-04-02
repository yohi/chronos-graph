"""重複記憶を統合・自己修復するモジュール。

スライディングウィンドウ方式と HNSW インデックスを活用して
O(M log N) で重複を検出・アーカイブする。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from context_store.logger import get_logger
from context_store.storage.protocols import GraphAdapter, MemoryFilters, StorageAdapter

if TYPE_CHECKING:
    from context_store.config import Settings
    from context_store.embedding.protocols import EmbeddingProvider
    from context_store.models.memory import Memory

logger = get_logger(__name__)

# 自己修復の類似度閾値（デフォルト）
_DEFAULT_DEDUP_THRESHOLD = 0.90
# 通常統合候補の類似度閾値（デフォルト）
_DEFAULT_CONSOLIDATION_THRESHOLD = 0.85
# vector_search の近傍数
_VECTOR_SEARCH_TOP_K = 5
# 1サイクルで処理する記憶数の上限
CONSOLIDATION_BATCH_SIZE = 100


@dataclass
class ConsolidatorResult:
    """Consolidator の実行結果。

    Attributes:
        consolidated_count: アーカイブした重複数。
        checked_count: チェックした記憶数。
    """

    consolidated_count: int
    checked_count: int


class Consolidator:
    """重複記憶を統合・自己修復するクラス。

    スライディングウィンドウ（last_cleanup_at 以降の記憶）に対して
    HNSW インデックスを利用した近似近傍探索を行い、
    類似度 >= dedup_threshold の記憶を事後的にアーカイブする（自己修復）。
    類似度 0.85 <= score < 0.90 は通常統合候補として処理する。

    Args:
        storage: ストレージアダプター。
        graph: グラフアダプター。None の場合は SUPERSEDES エッジ作成をスキップ。
        embedding_provider: 埋め込みプロバイダー。None の場合は埋め込み再計算をスキップ。
        settings: アプリ設定。None の場合はデフォルト閾値を使用。
    """

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None = None,
        embedding_provider: "EmbeddingProvider | None" = None,
        settings: "Settings | None" = None,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._embedding_provider = embedding_provider
        if settings is not None:
            self._dedup_threshold = settings.dedup_threshold
            self._consolidation_threshold = settings.consolidation_threshold
        else:
            self._dedup_threshold = _DEFAULT_DEDUP_THRESHOLD
            self._consolidation_threshold = _DEFAULT_CONSOLIDATION_THRESHOLD

    async def run(
        self,
        last_cleanup_at: datetime | None = None,
        batch_size: int = CONSOLIDATION_BATCH_SIZE,
    ) -> ConsolidatorResult:
        """スライディングウィンドウ内の記憶を走査して重複を統合する。

        アルゴリズム:
        1. last_cleanup_at 以降に作成された記憶を取得（スライディングウィンドウ）。
           last_cleanup_at=None なら全記憶対象（初回実行）。
        2. batch_size 件ずつバッチ処理。
        3. 各記憶の embedding に対して vector_search(top_k=5) で近傍を検索。
        4. 自身を除いて similarity >= dedup_threshold の記憶がある場合
           → 古い方をアーカイブして SUPERSEDES エッジを作成（自己修復）。
        5. consolidation_threshold <= similarity < dedup_threshold の場合も処理
           （通常統合候補）だが、自己修復候補を優先。
        6. ログ出力: 'Self-healing: archived duplicate memory {id} due to similarity {score}'

        Args:
            last_cleanup_at: この時刻以降に作成された記憶を対象とする。
                None の場合は全記憶が対象。
            batch_size: 1サイクルで処理する最大記憶数。

        Returns:
            処理結果を格納した ConsolidatorResult。
        """
        # スライディングウィンドウ: last_cleanup_at 以降の記憶を取得
        filters = self._build_filters(last_cleanup_at)
        all_memories = await self._storage.list_by_filter(filters)

        # Python 側で last_cleanup_at によるフィルタリング
        # （MemoryFilters に created_after フィールドがないため）
        if last_cleanup_at is not None:
            all_memories = [m for m in all_memories if m.created_at >= last_cleanup_at]

        # batch_size で上限を設ける（メモリ枯渇防止）
        window = all_memories[:batch_size]

        consolidated_count = 0
        # 処理済み（アーカイブ済み）記憶 ID を追跡してスキップ
        archived_in_this_run: set[str] = set()

        for memory in window:
            memory_id = str(memory.id)

            # 既にこの実行でアーカイブされた記憶はスキップ
            if memory_id in archived_in_this_run:
                continue

            # embedding が空の場合は vector_search をスキップ
            if not memory.embedding:
                continue

            # HNSW 経由の近似近傍探索（O(log N) per query）
            scored_neighbors = await self._storage.vector_search(
                memory.embedding, top_k=_VECTOR_SEARCH_TOP_K
            )

            # 自身を除外し、類似度でフィルタリング
            self_healing_candidates = []  # score >= dedup_threshold
            regular_candidates = []       # consolidation_threshold <= score < dedup_threshold

            for scored in scored_neighbors:
                neighbor_id = str(scored.memory.id)
                if neighbor_id == memory_id:
                    continue
                if neighbor_id in archived_in_this_run:
                    continue
                # アーカイブ済みの記憶はスキップ
                if scored.memory.archived_at is not None:
                    continue

                if scored.score >= self._dedup_threshold:
                    self_healing_candidates.append(scored)
                elif scored.score >= self._consolidation_threshold:
                    regular_candidates.append(scored)

            # 自己修復候補を優先して処理
            for scored in self_healing_candidates:
                older, newer = self._determine_order(memory, scored.memory)
                older_id = str(older.id)

                if older_id in archived_in_this_run:
                    continue

                await self._archive_memory(older_id)
                archived_in_this_run.add(older_id)
                consolidated_count += 1

                # SUPERSEDES エッジを作成
                if self._graph is not None:
                    newer_id = str(newer.id)
                    await self._graph.create_edge(
                        newer_id,
                        older_id,
                        "SUPERSEDES",
                        {"similarity": scored.score, "archived_at": datetime.now(timezone.utc)},
                    )

                logger.info(
                    "Self-healing: archived duplicate memory %s due to similarity %s",
                    older_id,
                    scored.score,
                )

            # 通常統合候補を処理（0.85 <= score < 0.90）
            for scored in regular_candidates:
                older, newer = self._determine_order(memory, scored.memory)
                older_id = str(older.id)

                if older_id in archived_in_this_run:
                    continue

                await self._archive_memory(older_id)
                archived_in_this_run.add(older_id)
                consolidated_count += 1

                if self._graph is not None:
                    newer_id = str(newer.id)
                    await self._graph.create_edge(
                        newer_id,
                        older_id,
                        "SUPERSEDES",
                        {"similarity": scored.score, "archived_at": datetime.now(timezone.utc)},
                    )

                logger.info(
                    "Consolidation: archived similar memory %s due to similarity %s",
                    older_id,
                    scored.score,
                )

        # 埋め込み再計算（EmbeddingProvider が提供されている場合のみ）
        # 現在は実装スコープ外（将来の拡張ポイント）

        return ConsolidatorResult(
            consolidated_count=consolidated_count,
            checked_count=len(window),
        )

    def _build_filters(self, last_cleanup_at: datetime | None) -> MemoryFilters:
        """スライディングウィンドウのフィルタを構築する。

        Args:
            last_cleanup_at: この時刻以降に作成された記憶を対象とする。
                None の場合は全記憶が対象。

        Returns:
            MemoryFilters オブジェクト。
        """
        # archived=None はアクティブ記憶のみを示す（protocols.py 参照）
        # last_cleanup_at の期間フィルタは MemoryFilters が対応していないため、
        # 現状は list_by_filter で全アクティブ記憶を取得後、Python 側でフィルタリングする。
        # （将来: MemoryFilters に created_after フィールドを追加してストレージ側でフィルタリング）
        return MemoryFilters(archived=None)

    @staticmethod
    def _determine_order(mem_a: "Memory", mem_b: "Memory") -> tuple["Memory", "Memory"]:
        """2つの記憶のうち古い方と新しい方を返す。

        Args:
            mem_a: 比較する記憶 A。
            mem_b: 比較する記憶 B。

        Returns:
            (older, newer) のタプル。created_at が古い方が older。
        """
        if mem_a.created_at <= mem_b.created_at:
            return mem_a, mem_b
        return mem_b, mem_a

    async def _archive_memory(self, memory_id: str) -> None:
        """記憶をアーカイブ状態に更新する。

        Args:
            memory_id: アーカイブする記憶の ID。
        """
        now = datetime.now(timezone.utc)
        await self._storage.update_memory(memory_id, {"archived_at": now})
