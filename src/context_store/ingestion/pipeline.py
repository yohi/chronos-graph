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
import logging
import weakref
from uuid import UUID
from dataclasses import dataclass
from typing import Any

from context_store.config import Settings
from context_store.embedding.protocols import EmbeddingProvider
from context_store.ingestion.adapters import ConversationAdapter, RawContent, URLAdapter
from context_store.ingestion.chunker import Chunker
from context_store.ingestion.classifier import Classifier
from context_store.ingestion.deduplicator import DeduplicationAction, Deduplicator
from context_store.ingestion.graph_linker import GraphLinker
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import GraphAdapter, MemoryFilters, StorageAdapter

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """インジェスト結果を保持するデータクラス。"""

    memory_id: str
    action: DeduplicationAction
    memory_type: MemoryType = MemoryType.EPISODIC
    chunk_index: int = 0
    chunk_count: int = 1
    persisted_memory: Memory | None = None


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
        embedding_provider: EmbeddingProvider,
        settings: Settings | None = None,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._embedding_provider = embedding_provider
        self._settings = settings or Settings()

        self._chunker = Chunker()
        self._classifier = Classifier()
        self._deduplicator = Deduplicator(storage=storage)
        self._graph_linker = GraphLinker(storage=storage, graph=graph)
        self._conversation_adapter = ConversationAdapter(
            chunk_size=self._settings.conversation_chunk_size
        )
        self._url_adapter: URLAdapter | None = None  # 遅延初期化

        # コンテンツハッシュ別の Lock（排他制御）
        self._content_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._content_results: dict[Any, asyncio.Task[IngestionResult | None]] = {}
        self._locks_mutex = asyncio.Lock()

    async def _get_content_lock(self, content_hash: str) -> asyncio.Lock:
        """コンテンツハッシュに対応する Lock を取得（なければ作成）する。"""
        async with self._locks_mutex:
            lock = self._content_locks.get(content_hash)
            if lock is None:
                lock = asyncio.Lock()
                self._content_locks[content_hash] = lock
            return lock

    def _compute_hash(self, content: str) -> str:
        """コンテンツのハッシュ値を計算する。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def _fetch_url_content(self, url: str) -> list[RawContent]:
        """URL からコンテンツを取得する（テストでモック可能）。"""
        if self._url_adapter is None:
            self._url_adapter = URLAdapter(settings=self._settings)
        return await self._url_adapter.adapt(url)

    async def dispose(self) -> None:
        """保持しているクローズ可能リソースを解放する。"""
        if self._url_adapter is not None:
            aclose = getattr(self._url_adapter, "aclose", None)
            if callable(aclose):
                await aclose()

        await self._embedding_provider.close()

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
        elif source_type == SourceType.CONVERSATION:
            raw_contents = await self._conversation_adapter.adapt(source, metadata=meta)
        else:
            raw_contents = [RawContent(content=source, source_type=source_type, metadata=meta)]

        results: list[IngestionResult] = []
        document_memories: dict[str, list[Memory]] = {}

        for raw in raw_contents:
            # ステップ2: チャンク分割
            chunks = list(self._chunker.chunk(raw))

            # ステップ3: 各チャンクを処理
            for chunk in chunks:
                document_id = str(chunk.metadata.get("document_id", ""))
                prior_document_memories = document_memories.get(document_id, [])
                try:
                    result = await self._process_chunk(
                        chunk,
                        base_metadata=meta,
                        prior_document_memories=prior_document_memories,
                    )
                    if result:
                        results.append(result)
                        if document_id and result.persisted_memory is not None:
                            document_memories.setdefault(document_id, []).append(
                                result.persisted_memory
                            )
                except Exception as e:
                    logger.error(
                        "Chunk 処理失敗 (content_hash=%s, doc_id=%s): %s",
                        self._compute_hash(chunk.content)[:8],
                        document_id,
                        e,
                        exc_info=True,
                    )
                    # 失敗したチャンクはスキップして続行

        return results

    async def _process_chunk(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
    ) -> IngestionResult | None:
        """単一チャンクの処理パイプラインを実行する。"""
        # コンテンツハッシュ + メタデータでキーイング
        content_hash = self._compute_hash(chunk.content)
        project_id = base_metadata.get("project", "")
        session_id = base_metadata.get("session_id", "")
        source_type = chunk.source_type.value
        # 追加のメタデータを含めてキーを精緻化
        url = chunk.metadata.get("url") or chunk.metadata.get("source_id", "")
        chunk_index = chunk.metadata.get("chunk_index", 0)
        document_id = chunk.metadata.get("document_id", "")
        memo_key = (
            content_hash,
            project_id,
            session_id,
            source_type,
            url,
            chunk_index,
            document_id,
        )

        # 1. 同一の memo_key (コンテンツ + メタデータ) が並行して走っている場合は、そのタスクを共有する
        # ここはロック外でチェックし、あれば shield で待つ。
        existing_task = self._content_results.get(memo_key)
        if existing_task is not None:
            return await asyncio.shield(existing_task)

        # 2. 自分が処理を担当する（Task として登録して実行）
        # 同一 memo_key の後続リクエストのために、自分自身を Task として登録する。
        # ロック制御は Task 内部で行う。
        current_task = asyncio.create_task(
            self._process_chunk_task_wrapper(
                chunk,
                base_metadata=base_metadata,
                prior_document_memories=prior_document_memories,
                memo_key=memo_key,
                content_hash=content_hash,
            )
        )

        async with self._locks_mutex:
            # 二重チェック
            if memo_key in self._content_results:
                current_task.cancel()
                return await asyncio.shield(self._content_results[memo_key])
            self._content_results[memo_key] = current_task

        return await asyncio.shield(current_task)

    async def _process_chunk_task_wrapper(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        memo_key: Any,
        content_hash: str,
    ) -> IngestionResult | None:
        """処理を実行し、完了後に確実にクリーンアップを行うラッパー。"""
        try:
            return await self._process_chunk_core(
                chunk,
                base_metadata=base_metadata,
                prior_document_memories=prior_document_memories,
                content_hash=content_hash,
            )
        finally:
            # タスク完了時のクリーンアップ
            async with self._locks_mutex:
                if self._content_results.get(memo_key) is asyncio.current_task():
                    self._content_results.pop(memo_key, None)

    async def _process_chunk_core(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        content_hash: str,
    ) -> IngestionResult | None:
        """チャンクのコア処理（ロック範囲を最適化）。"""
        # ステップ3: 分類（LLM不使用のルールベース）
        classification = self._classifier.classify(chunk)

        # ========================================================
        # 埋め込み生成はロック外で実施（並列性を高め SQLITE_BUSY 回避）
        # ========================================================
        embedding = await self._embedding_provider.embed(chunk.content)

        # メタデータの整合
        merged_meta = {**base_metadata, **chunk.metadata}
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

        # ========================================================
        # 重複排除（Deduplication）のみをロックで保護
        # ========================================================
        lock = await self._get_content_lock(content_hash)
        async with lock:
            dedup_result = await self._deduplicator.deduplicate(memory)

        # ロック解放後に保存処理を続行
        supersedes_memory = None
        if dedup_result.action == DeduplicationAction.REPLACE:
            supersedes_memory = dedup_result.existing_memory

        # ステップ6: 永続化
        raw_id = await self._storage.save_memory(memory)
        memory_id = UUID(raw_id) if isinstance(raw_id, str) else raw_id
        persisted_memory = memory.model_copy(update={"id": memory_id})

        # ステップ7: グラフノード作成
        node_created = False
        try:
            await self._graph.create_node(
                str(memory_id),
                {
                    "memory_type": persisted_memory.memory_type.value,
                    "source_type": persisted_memory.source_type.value,
                    "project": persisted_memory.project,
                },
            )
            node_created = True

            # ステップ8: グラフリンク（エッジ作成）
            previous_memories = await self._get_previous_memories(persisted_memory)
            chunk_neighbors = self._build_chunk_neighbors(
                persisted_memory,
                prior_document_memories,
                supersedes_memory,
            )
            await self._graph_linker.link(
                persisted_memory,
                supersedes=supersedes_memory,
                previous_memories=previous_memories,
                chunk_neighbors=chunk_neighbors,
            )
        except Exception:
            try:
                await self._storage.delete_memory(str(memory_id))
            except Exception as e:
                logger.error("Error during delete_memory for memory_id=%s: %s", memory_id, e)
            try:
                if node_created:
                    await self._graph.delete_node(str(memory_id))
            except Exception as e:
                logger.error("Error during delete_node for memory_id=%s: %s", memory_id, e)
            raise

        logger.info(
            "Ingestion 完了: memory_id=%s, action=%s, type=%s",
            memory_id,
            dedup_result.action.value,
            classification.memory_type.value,
        )

        result = IngestionResult(
            memory_id=str(memory_id),
            action=dedup_result.action,
            memory_type=classification.memory_type,
            chunk_index=int(chunk.metadata.get("chunk_index", 0)),
            chunk_count=int(chunk.metadata.get("chunk_count", 1)),
        )
        result.persisted_memory = persisted_memory
        return result

    async def _get_previous_memories(self, memory: Memory) -> list[Memory]:
        """時系列エッジ用に同一セッションまたはプロジェクトの直前候補を取得する。"""
        session_id = memory.source_metadata.get("session_id")

        # limit を 2 に増やし、自分自身が返ってきた場合でも直前の1件を取得できるようにする
        filters = MemoryFilters(
            project=memory.project,
            limit=2,
            order_by="created_at DESC",
            session_id=str(session_id) if session_id else None,
        )

        candidates = await self._storage.list_by_filter(filters)

        previous_memories: list[Memory] = []
        candidates = [c for c in candidates if str(c.id) != str(memory.id)]

        for candidate in candidates:
            candidate_session_id = candidate.source_metadata.get("session_id")
            if session_id and candidate_session_id == session_id:
                previous_memories.append(candidate)
                break
            if not session_id and memory.project and candidate.project == memory.project:
                previous_memories.append(candidate)
                break

        return previous_memories

    def _build_chunk_neighbors(
        self,
        memory: Memory,
        prior_document_memories: list[Memory],
        supersedes_memory: Memory | None,
    ) -> dict[str, list[Memory]] | None:
        """同一 document_id を持つチャンク近傍情報を構築する。"""
        document_id = memory.source_metadata.get("document_id")
        if document_id is None:
            return None

        neighbors = [*prior_document_memories, memory]
        if (
            supersedes_memory
            and supersedes_memory.source_metadata.get("document_id") == document_id
        ):
            neighbors.append(supersedes_memory)
        return {str(document_id): neighbors}
