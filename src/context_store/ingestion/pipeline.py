"""Ingestion Pipeline: 取り込みパイプラインの統合クラス。

フロー: Adapter → Chunker → Classifier → Embedding → Deduplicator → GraphLinker → 永続化

重要な設計上の注意:
- EmbeddingProvider によるベクトル化は StorageAdapter の書き込み前に完了させる
  （SQLite の SQLITE_BUSY 回避）
- コンテンツハッシュ/URL に基づく asyncio.Lock での排他制御
  （同一プロセス内での重複登録防止）
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from context_store.ingestion.adapters import RawContent, URLAdapter
from context_store.ingestion.chunker import Chunker
from context_store.ingestion.classifier import Classifier
from context_store.ingestion.deduplicator import DeduplicationAction, Deduplicator
from context_store.ingestion.graph_linker import GraphLinker
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import GraphAdapter, StorageAdapter

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """インジェスト結果を保持するデータクラス。"""

    memory_id: str
    action: DeduplicationAction
    memory_type: MemoryType = MemoryType.EPISODIC
    chunk_index: int = 0
    chunk_count: int = 1


class IngestionPipeline:
    """Ingestion Pipeline: 各コンポーネントを統合して処理するクラス。

    排他制御:
    - コンテンツハッシュに基づく asyncio.Lock でデュープリケーション防止
    - 同一プロセス内のベストエフォート防衛

    トランザクション境界:
    - EmbeddingProvider.embed() は save_memory() より必ず前に完了
    """

    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter,
        embedding_provider: Any,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._embedding_provider = embedding_provider

        self._chunker = Chunker()
        self._classifier = Classifier()
        self._deduplicator = Deduplicator(storage=storage)
        self._graph_linker = GraphLinker(storage=storage, graph=graph)
        self._url_adapter: URLAdapter | None = None  # 遅延初期化

        # コンテンツハッシュ別の Lock（排他制御）
        self._content_locks: dict[str, asyncio.Lock] = {}
        self._locks_mutex = asyncio.Lock()

    async def _get_content_lock(self, content_hash: str) -> asyncio.Lock:
        """コンテンツハッシュに対応する Lock を取得（なければ作成）する。"""
        async with self._locks_mutex:
            if content_hash not in self._content_locks:
                self._content_locks[content_hash] = asyncio.Lock()
            return self._content_locks[content_hash]

    def _compute_hash(self, content: str) -> str:
        """コンテンツのハッシュ値を計算する。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def _fetch_url_content(self, url: str) -> list[RawContent]:
        """URL からコンテンツを取得する（テストでモック可能）。"""
        if self._url_adapter is None:
            self._url_adapter = URLAdapter()
        return await self._url_adapter.adapt(url)

    async def dispose(self) -> None:
        """保持しているクローズ可能リソースを解放する。"""
        if self._url_adapter is not None:
            aclose = getattr(self._url_adapter, "aclose", None)
            if callable(aclose):
                await aclose()

        provider_dispose = getattr(self._embedding_provider, "dispose", None)
        if callable(provider_dispose):
            dispose_result = provider_dispose()
            if inspect.isawaitable(dispose_result):
                await dispose_result
                return

        provider_close = getattr(self._embedding_provider, "close", None)
        if callable(provider_close):
            close_result = provider_close()
            if inspect.isawaitable(close_result):
                await close_result

    async def ingest(
        self,
        source: str,
        *,
        source_type: SourceType = SourceType.MANUAL,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestionResult]:
        """コンテンツを取り込んで永続化する。

        Args:
            source: コンテンツ本文または URL
            source_type: ソースタイプ
            metadata: 追加メタデータ（project, session_id など）

        Returns:
            List[IngestionResult]: 各チャンクの処理結果
        """
        meta = metadata or {}

        # ステップ1: ソースからコンテンツを取得
        if source_type == SourceType.URL:
            raw_contents = await self._fetch_url_content(source)
        else:
            raw_contents = [RawContent(content=source, source_type=source_type, metadata=meta)]

        results: list[IngestionResult] = []

        for raw in raw_contents:
            # ステップ2: チャンク分割
            chunks = list(self._chunker.chunk(raw))

            # ステップ3: 各チャンクを処理
            for chunk in chunks:
                result = await self._process_chunk(chunk, base_metadata=meta)
                if result:
                    results.append(result)

        return results

    async def _process_chunk(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
    ) -> IngestionResult | None:
        """単一チャンクの処理パイプラインを実行する。"""
        # コンテンツハッシュで排他制御
        content_hash = self._compute_hash(chunk.content)
        lock = await self._get_content_lock(content_hash)

        async with lock:
            return await self._process_chunk_locked(chunk, base_metadata=base_metadata)

    async def _process_chunk_locked(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
    ) -> IngestionResult | None:
        """排他ロック取得済みの状態でチャンクを処理する。"""
        # ステップ3: 分類（LLM不使用のルールベース）
        classification = self._classifier.classify(chunk)

        # ========================================================
        # 重要: EmbeddingProvider によるベクトル化を StorageAdapter の
        # 書き込みトランザクション開始前に完了させる（SQLITE_BUSY 回避）
        # ========================================================
        embedding = await self._embedding_provider.embed(chunk.content)

        # メタデータの整合
        merged_meta = {**chunk.metadata, **base_metadata}
        project = merged_meta.get("project")

        # Memory オブジェクトの作成（埋め込みベクトル設定済み）
        memory = Memory(
            content=chunk.content,
            memory_type=classification.memory_type,
            source_type=chunk.source_type,
            embedding=embedding,
            importance_score=classification.importance_score,
            source_metadata=merged_meta,
            project=str(project) if project else None,
        )

        # ステップ5: 重複排除（類似度チェック）
        dedup_result = await self._deduplicator.deduplicate(memory)

        # MERGE_CANDIDATE の場合は統合候補としてマークするが挿入も行う
        # （Consolidator が後で処理する）
        supersedes_memory = None
        if dedup_result.action == DeduplicationAction.REPLACE:
            supersedes_memory = dedup_result.existing_memory

        # ========================================================
        # ここからが StorageAdapter の書き込み操作
        # （埋め込みベクトル化は上で完了済み）
        # ========================================================

        # ステップ6: 永続化
        memory_id = await self._storage.save_memory(memory)

        # ステップ7: グラフノード作成
        await self._graph.create_node(
            memory_id,
            {
                "memory_type": memory.memory_type.value,
                "source_type": memory.source_type.value,
                "project": memory.project,
            },
        )

        # ステップ8: グラフリンク（エッジ作成）
        await self._graph_linker.link(
            memory,
            supersedes=supersedes_memory,
        )

        logger.info(
            "Ingestion 完了: memory_id=%s, action=%s, type=%s",
            memory_id,
            dedup_result.action.value,
            classification.memory_type.value,
        )

        return IngestionResult(
            memory_id=memory_id,
            action=dedup_result.action,
            memory_type=classification.memory_type,
            chunk_index=int(chunk.metadata.get("chunk_index", 0)),
            chunk_count=int(chunk.metadata.get("chunk_count", 1)),
        )
