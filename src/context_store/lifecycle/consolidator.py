"""重複記憶を統合・自己修復するモジュール。

スライディングウィンドウ方式と HNSW インデックスを活用して
O(M log N) で重複を検出・アーカイブする。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from context_store.models.memory import Memory, ScoredMemory
from context_store.storage.protocols import GraphAdapter, MemoryFilters, StorageAdapter

logger = logging.getLogger(__name__)

# 一度に処理する最大記憶数
CONSOLIDATION_BATCH_SIZE = 100


@dataclass
class ConsolidatorResult:
    """統合処理の結果。"""

    consolidated_count: int
    checked_count: int
    last_processed_at: datetime | None
    last_processed_id: str | None
    has_more: bool = False


class Consolidator:
    """重複記憶を統合・アーカイブするクラス。"""

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None = None,
        embedding_provider: Any | None = None,
        dedup_threshold: float = 0.90,
        consolidation_threshold: float = 0.85,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._embedding_provider = embedding_provider
        self._dedup_threshold = dedup_threshold
        self._consolidation_threshold = consolidation_threshold

    async def run(
        self,
        last_cleanup_at: datetime | None = None,
        last_cleanup_id: str | None = None,
        batch_size: int = CONSOLIDATION_BATCH_SIZE,
        heartbeat_fn: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> ConsolidatorResult:
        """重複記憶を統合するクリーンアップジョブ。

        Args:
            last_cleanup_at: この時刻以降に作成された記憶を対象とする。
                None の場合は全記憶が対象。
            last_cleanup_id: 最後に処理した記憶の ID。
            batch_size: 1サイクルで処理する最大記憶数。
            heartbeat_fn: ハートビート用コールバック関数。

        Returns:
            処理結果を格納した ConsolidatorResult。
        """
        now = datetime.now(timezone.utc)

        # 安定したページングのために (created_at, id) ASC で取得
        filters = self._build_filters(last_cleanup_at)
        filters.id_after = last_cleanup_id
        filters.limit = batch_size
        filters.order_by = "created_at ASC, id ASC"

        memories = await self._storage.list_by_filter(filters)
        if not memories:
            return ConsolidatorResult(
                consolidated_count=0,
                checked_count=0,
                last_processed_at=None,
                last_processed_id=None,
            )

        consolidated_count = 0
        checked_count = 0
        archived_in_this_run: set[str] = set()
        affected_memory_ids: set[str] = set()

        for memory in memories:
            if heartbeat_fn:
                await heartbeat_fn()

            memory_id = str(memory.id)
            if memory_id in archived_in_this_run:
                continue

            checked_count += 1

            # 類似記憶を検索
            if not memory.embedding:
                continue

            candidates = await self._storage.vector_search(
                embedding=memory.embedding,
                top_k=5,
            )

            # 自分自身を除外し、閾値以上の候補を抽出
            self_healing_candidates = []
            regular_candidates = []

            for scored in candidates:
                cand_id = str(scored.memory.id)
                if cand_id == memory_id or cand_id in archived_in_this_run:
                    continue

                # 異なるプロジェクトの記憶は統合しない
                if scored.memory.project != memory.project:
                    continue

                if scored.score >= self._dedup_threshold:
                    self_healing_candidates.append(scored)
                elif scored.score >= self._consolidation_threshold:
                    regular_candidates.append(scored)

            # 自己修復候補を優先して処理
            for scored in self_healing_candidates:
                success, newer_id = await self._process_candidate(
                    memory, scored, archived_in_this_run, "Self-healing", now
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
                    memory, scored, archived_in_this_run, "Consolidation", now
                )
                if success:
                    consolidated_count += 1
                    if newer_id:
                        affected_memory_ids.add(newer_id)

                if memory_id in archived_in_this_run:
                    break

        # 影響を受けた記憶（生き残った方）の埋め込みを再計算（任意）
        if self._embedding_provider and affected_memory_ids:
            # ここでは簡単のため、生き残った側の内容で再計算するロジックのプレースホルダ
            # 実際には複数マージされた場合は内容を結合して再計算するのが望ましい
            for mid in affected_memory_ids:
                if mid in archived_in_this_run:
                    continue
                await self._recompute_embedding(mid)

        last_processed_at = memories[-1].created_at if memories else None
        last_processed_id = str(memories[-1].id) if memories else None
        has_more = len(memories) == batch_size

        return ConsolidatorResult(
            consolidated_count=consolidated_count,
            checked_count=checked_count,
            last_processed_at=last_processed_at,
            last_processed_id=last_processed_id,
            has_more=has_more,
        )

    def _build_filters(self, last_cleanup_at: datetime | None) -> MemoryFilters:
        """検索フィルタを構築する。"""
        return MemoryFilters(
            created_after=last_cleanup_at,
            archived=False,
        )

    async def _process_candidate(
        self,
        memory: "Memory",
        scored: "ScoredMemory",
        archived_in_this_run: set[str],
        log_prefix: str,
        now: datetime,
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
        success = await self._archive_memory(older_id, now)
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
                    {"similarity": scored.score, "archived_at": now},
                )
            except Exception:
                logger.error(
                    "%s: failed to create SUPERSEDES edge from %s to %s",
                    log_prefix,
                    newer_id,
                    older_id,
                )

        logger.info(
            "%s: archived duplicate memory %s (similarity=%.2f), superseding with %s",
            log_prefix,
            older_id,
            scored.score,
            newer_id,
        )
        return True, newer_id

    def _determine_order(self, mem_a: "Memory", mem_b: "Memory") -> tuple["Memory", "Memory"]:
        """どちらが古く、どちらが新しいかを決定する。

        created_at が古い方をアーカイブ対象（older）とする。
        同時刻の場合は ID の辞書順で決定。
        """
        if (mem_a.created_at, str(mem_a.id)) <= (mem_b.created_at, str(mem_b.id)):
            return mem_a, mem_b
        return mem_b, mem_a

    async def _archive_memory(self, memory_id: str, now: datetime) -> bool:
        """記憶をアーカイブ状態に更新する。

        Args:
            memory_id: アーカイブする記憶の ID。
            now: アーカイブ日時として使用するタイムスタンプ。

        Returns:
            成功した場合は True。
        """
        return await self._storage.update_memory(memory_id, {"archived_at": now})

    async def _recompute_embedding(self, memory_id: str) -> None:
        """必要に応じて記憶の埋め込みを再計算する。"""
        if not self._embedding_provider:
            return

        memory = await self._storage.get_memory(memory_id)
        if not memory:
            return

        new_embedding = await self._embedding_provider.embed(memory.content)
        await self._storage.update_memory(memory_id, {"embedding": new_embedding})
