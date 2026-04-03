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
    from context_store.models.memory import Memory, ScoredMemory


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
        last_processed_at: 最後にチェックした記憶の作成日時。
        last_processed_id: 最後にチェックした記憶の ID。
        has_more: さらに処理すべきページが存在するかどうか。
    """

    consolidated_count: int
    checked_count: int
    last_processed_at: datetime | None = None
    last_processed_id: str | None = None
    has_more: bool = False


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
        last_cleanup_id: str | None = None,
        batch_size: int = CONSOLIDATION_BATCH_SIZE,
    ) -> ConsolidatorResult:
        """重複記憶を統合するクリーンアップジョブ。

        Args:
            last_cleanup_at: この時刻以降に作成された記憶を対象とする。
                None の場合は全記憶が対象。
            last_cleanup_id: 最後に処理した記憶の ID。
            batch_size: 1サイクルで処理する最大記憶数。

        Returns:
            処理結果を格納した ConsolidatorResult。
        """
        # 安定したページングのために (created_at, id) ASC で取得
        filters = self._build_filters(last_cleanup_at)
        filters.id_after = last_cleanup_id
        filters.limit = batch_size
        filters.order_by = "created_at ASC, id ASC"

        window = await self._storage.list_by_filter(filters)

        if not window:
            return ConsolidatorResult(
                consolidated_count=0,
                checked_count=0,
                last_processed_at=last_cleanup_at,
                last_processed_id=last_cleanup_id,
            )

        last_processed_at = window[-1].created_at
        last_processed_id = str(window[-1].id)
        has_more = len(window) >= batch_size

        consolidated_count = 0
        # 処理済み（アーカイブ済み）記憶 ID を追跡してスキップ
        archived_in_this_run: set[str] = set()
        # 統合の影響を受けた（生き残った側の）記憶 ID を追跡
        affected_memory_ids: set[str] = set()

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
                memory.embedding, top_k=_VECTOR_SEARCH_TOP_K, project=memory.project
            )

            # 自身を除外し、類似度でフィルタリング
            self_healing_candidates = []  # score >= dedup_threshold
            regular_candidates = []  # consolidation_threshold <= score < dedup_threshold

            for scored in scored_neighbors:
                neighbor_id = str(scored.memory.id)
                if neighbor_id == memory_id:
                    continue
                if neighbor_id in archived_in_this_run:
                    continue
                if scored.memory.project != memory.project:
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
                success, newer_id = await self._process_candidate(
                    memory, scored, archived_in_this_run, "Self-healing"
                )
                if success:
                    consolidated_count += 1
                    if newer_id:
                        affected_memory_ids.add(newer_id)

                # ベース側がアーカイブされた場合はこの記憶の処理を中断
                if memory_id in archived_in_this_run:
                    break

            # ベース側がアーカイブ済みならスキップ
            if memory_id in archived_in_this_run:
                continue

            # 通常統合候補を処理（0.85 <= score < 0.90）
            for scored in regular_candidates:
                success, newer_id = await self._process_candidate(
                    memory, scored, archived_in_this_run, "Consolidation"
                )
                if success:
                    consolidated_count += 1
                    if newer_id:
                        affected_memory_ids.add(newer_id)

                # ベース側がアーカイブされた場合は中断
                if memory_id in archived_in_this_run:
                    break

        # 埋め込み再計算(EmbeddingProvider が提供されている場合のみ)
        if self._embedding_provider is not None and affected_memory_ids:
            # 統合の影響を受けた（生き残った側の）記憶の埋め込みを更新
            # window 内にあるもののみ対象とする(効率のため)
            id_to_memory = {str(m.id): m for m in window}
            for mid in affected_memory_ids:
                if mid in id_to_memory:
                    memory = id_to_memory[mid]
                    new_embedding = await self._embedding_provider.embed(memory.content)
                    await self._storage.update_memory(mid, {"embedding": new_embedding})

        return ConsolidatorResult(
            consolidated_count=consolidated_count,
            checked_count=len(window),
            last_processed_at=last_processed_at,
            last_processed_id=last_processed_id,
            has_more=has_more,
        )

    async def _process_candidate(
        self,
        memory: "Memory",
        scored: "ScoredMemory",
        archived_in_this_run: set[str],
        log_prefix: str,
    ) -> tuple[bool, str | None]:
        """統合候補を処理（アーカイブ + エッジ作成）。

        Returns:
            (成功したかどうか, 生き残った側の ID)
        """
        older, newer = self._determine_order(memory, scored.memory)
        older_id = str(older.id)
        newer_id = str(newer.id)

        if older_id in archived_in_this_run:
            return False, None

        # 記憶をアーカイブ
        success = await self._archive_memory(older_id)
        if not success:
            return False, None

        archived_in_this_run.add(older_id)

        # SUPERSEDES エッジを作成
        if self._graph is not None:
            try:
                await self._graph.create_edge(
                    newer_id,
                    older_id,
                    "SUPERSEDES",
                    {"similarity": scored.score, "archived_at": datetime.now(timezone.utc)},
                )
            except Exception:
                logger.error(
                    "%s: failed to create SUPERSEDES edge from %s to %s",
                    log_prefix,
                    newer_id,
                    older_id,
                    exc_info=True,
                )

        logger.info(
            "%s: archived memory %s due to similarity %s",
            log_prefix,
            older_id,
            scored.score,
        )
        return True, newer_id

    def _build_filters(self, last_cleanup_at: datetime | None) -> MemoryFilters:
        """スライディングウィンドウのフィルタを構築する。

        Args:
            last_cleanup_at: この時刻以降に作成された記憶を対象とする。
                None の場合は全記憶が対象。

        Returns:
            MemoryFilters オブジェクト。
        """
        # archived=None はアクティブ記憶のみを示す(protocols.py 参照)
        return MemoryFilters(archived=None, created_after=last_cleanup_at)

    @staticmethod
    def _determine_order(mem_a: "Memory", mem_b: "Memory") -> tuple["Memory", "Memory"]:
        """2つの記憶のうち古い方と新しい方を返す。

        Args:
            mem_a: 比較する記憶 A。
            mem_b: 比較する記憶 B。

        Returns:
            (older, newer) のタプル。
            (created_at, id) のタプルで比較を行い、小さい方が older。
        """
        if (mem_a.created_at, str(mem_a.id)) <= (mem_b.created_at, str(mem_b.id)):
            return mem_a, mem_b
        return mem_b, mem_a

    async def _archive_memory(self, memory_id: str) -> bool:
        """記憶をアーカイブ状態に更新する。

        Args:
            memory_id: アーカイブする記憶の ID。

        Returns:
            成功した場合は True。
        """
        now = datetime.now(timezone.utc)
        return await self._storage.update_memory(memory_id, {"archived_at": now})
