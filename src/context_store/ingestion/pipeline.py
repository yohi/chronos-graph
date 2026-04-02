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
from uuid import UUID
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from context_store.config import Settings
from context_store.embedding.protocols import EmbeddingProvider as BaseEmbeddingProvider
from context_store.ingestion.adapters import ConversationAdapter, RawContent, URLAdapter
from context_store.ingestion.chunker import Chunker
from context_store.ingestion.classifier import Classifier
from context_store.ingestion.deduplicator import DeduplicationAction, Deduplicator
from context_store.ingestion.graph_linker import GraphLinker
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import GraphAdapter, MemoryFilters, StorageAdapter

logger = logging.getLogger(__name__)


class EmbeddingLifecycle(Protocol):
    """Lifecycle methods for EmbeddingProvider."""

    async def close(self) -> None:
        """任意のクローズ処理。"""
        ...

    async def dispose(self) -> None:
        """任意の破棄処理。"""
        ...


@runtime_checkable
class EmbeddingProvider(BaseEmbeddingProvider, EmbeddingLifecycle, Protocol):
    """Protocol combining base embedding features and lifecycle methods."""

    ...


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
        self._conversation_adapter = ConversationAdapter()
        self._url_adapter: URLAdapter | None = None  # 遅延初期化

        # コンテンツハッシュ別の Lock（排他制御）
        self._content_locks: dict[str, asyncio.Lock] = {}
        self._content_lock_refs: dict[str, int] = {}
        self._content_results: dict[Any, asyncio.Task[IngestionResult | None]] = {}
        self._locks_mutex = asyncio.Lock()

    async def _get_content_lock(self, content_hash: str) -> asyncio.Lock:
        """コンテンツハッシュに対応する Lock を取得（なければ作成）する。"""
        async with self._locks_mutex:
            if content_hash not in self._content_locks:
                self._content_locks[content_hash] = asyncio.Lock()
                self._content_lock_refs[content_hash] = 0
            self._content_lock_refs[content_hash] += 1
            return self._content_locks[content_hash]

    async def _release_content_lock(self, content_hash: str, lock: asyncio.Lock) -> None:
        """不要になったコンテンツロックを辞書から取り除く。"""
        async with self._locks_mutex:
            if self._content_locks.get(content_hash) is lock:
                self._content_lock_refs[content_hash] -= 1
                if self._content_lock_refs[content_hash] <= 0:
                    self._content_locks.pop(content_hash, None)
                    self._content_lock_refs.pop(content_hash, None)

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

        provider_dispose = getattr(self._embedding_provider, "dispose", None)
        dispose_success = False
        if callable(provider_dispose):
            try:
                dispose_result = provider_dispose()
                if inspect.isawaitable(dispose_result):
                    await dispose_result
                dispose_success = True
            except Exception as e:
                logger.error(
                    "Error during provider_dispose in IngestionPipeline: %s", e, exc_info=True
                )

        if not dispose_success:
            provider_close = getattr(self._embedding_provider, "close", None)
            if callable(provider_close):
                try:
                    close_result = provider_close()
                    if inspect.isawaitable(close_result):
                        await close_result
                except Exception as e:
                    logger.error(
                        "Error during provider_close in IngestionPipeline: %s", e, exc_info=True
                    )

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

        lock = await self._get_content_lock(content_hash)
        current_task: asyncio.Task[IngestionResult | None] | None = None

        try:
            async with lock:
                # 他の並行タスクがすでにこのチャンクを処理中であれば、そのタスクの完了を待つ
                # （in-flight map として機能させる）
                existing_task = self._content_results.get(memo_key)
                if existing_task is None:
                    # 自分が処理を担当するため、Task を作成して登録
                    current_task = asyncio.create_task(
                        self._process_chunk_locked_with_cleanup(
                            chunk,
                            base_metadata=base_metadata,
                            prior_document_memories=prior_document_memories,
                            memo_key=memo_key,
                            content_hash=content_hash,
                            lock=lock,
                        )
                    )
                    self._content_results[memo_key] = current_task

            if existing_task is not None:
                # 他のタスクが処理中なので、その完了を待つ
                # asyncio.shield を使い、呼び出し元のキャンセルが共有タスクに波及しないようにする
                return await asyncio.shield(existing_task)

            # 自分が作成したタスクを実行（current_task は必ず非 None）
            assert current_task is not None
            # 自分が作成したタスクも shield で待機し、キャンセルから保護する
            return await asyncio.shield(current_task)
        finally:
            await self._release_content_lock(content_hash, lock)

    async def _process_chunk_locked_with_cleanup(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        memo_key: Any,
        content_hash: str,
        lock: asyncio.Lock,
    ) -> IngestionResult | None:
        """処理を実行し、完了後に確実にクリーンアップを行うラッパー。"""
        try:
            return await self._process_chunk_locked(
                chunk,
                base_metadata=base_metadata,
                prior_document_memories=prior_document_memories,
            )
        finally:
            # タスク完了時のクリーンアップ
            async with lock:
                if self._content_results.get(memo_key) is asyncio.current_task():
                    self._content_results.pop(memo_key, None)

    async def _process_chunk_locked(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
    ) -> IngestionResult | None:
        """排他ロック取得済みの状態でチャンクを処理する。"""
        # ステップ3: 分類（LLM不使用のルールベース）
        classification = self._classifier.classify(chunk)

        # ========================================================
        # 重要: EmbeddingProvider によるベクトル化を StorageAdapter の
        # 書き込みトランザクション開始前に完了させる（SQLITE_BUSY 回避）
        # ========================================================
        embedding = await self._embedding_provider.embed(chunk.content)

        # メタデータの整合（パイプライン派生フィールドを含む chunk.metadata を優先）
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
        raw_id = await self._storage.save_memory(memory)
        # IDをUUIDに正規化（ストレージが文字列を返す場合があるため）
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
            # 補償処理（ロールバック）: delete_memory と delete_node を個別に試行
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
