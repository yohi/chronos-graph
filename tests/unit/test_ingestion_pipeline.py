"""Task 4.6: Ingestion Pipeline のユニットテスト。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.deduplicator import DeduplicationAction
from context_store.ingestion.pipeline import IngestionPipeline, IngestionResult
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import GraphAdapter, StorageAdapter
from tests.unit.conftest import make_settings


# ===========================================================================
# ヘルパー
# ===========================================================================


def _make_memory(content: str = "test") -> Memory:
    return Memory(
        content=content,
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
        embedding=[0.1] * 4,
    )


def _make_mock_embedding_provider(
    embedding: list[float] | None = None,
    delay: float = 0.0,
) -> Any:
    """モック EmbeddingProvider を作成する。"""
    provider = MagicMock()
    provider.dimension = 4

    async def embed(text: str) -> list[float]:
        if delay > 0:
            await asyncio.sleep(delay)
        return embedding or [0.1, 0.2, 0.3, 0.4]

    async def embed_batch(texts: list[str]) -> list[list[float]]:
        if delay > 0:
            await asyncio.sleep(delay)
        return [embedding or [0.1, 0.2, 0.3, 0.4] for _ in texts]

    provider.embed = embed
    provider.embed_batch = embed_batch
    return provider


def _make_mock_storage() -> StorageAdapter:
    storage = MagicMock(spec=StorageAdapter)
    saved_memories: list[Memory] = []

    async def save_memory(memory: Memory) -> str:
        mid = str(uuid4())
        persisted = memory.model_copy(update={"id": mid})
        saved_memories.append(persisted)
        return mid

    async def vector_search(embedding, top_k, project=None, filters=None):
        results = []
        for m in saved_memories:
            # プロジェクトフィルタのシミュレーション
            if project and m.project != project:
                continue
            # 同一コンテンツ（または同一ベクトル）ならスコア1.0で返す
            results.append(ScoredMemory(memory=m, score=1.0, source=MemorySource.VECTOR))
        return results

    storage.save_memory = AsyncMock(side_effect=save_memory)
    storage.vector_search = AsyncMock(side_effect=vector_search)
    storage.list_by_filter = AsyncMock(return_value=[])
    storage.update_memory = AsyncMock(return_value=True)
    return storage


def _make_mock_graph() -> GraphAdapter:
    graph = MagicMock(spec=GraphAdapter)
    graph.create_node = AsyncMock()
    graph.create_edges_batch = AsyncMock()
    return graph


# ===========================================================================
# Pipeline フロー テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_basic_flow() -> None:
    """Pipeline の基本フロー: テキスト入力 → 保存完了。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    results = await pipeline.ingest("テストコンテンツ", source_type=SourceType.MANUAL)

    assert len(results) >= 1
    for result in results:
        assert isinstance(result, IngestionResult)
        assert result.memory_id is not None


@pytest.mark.asyncio
async def test_pipeline_calls_save_memory() -> None:
    """Pipeline が save_memory を呼び出す。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    await pipeline.ingest("テストコンテンツ", source_type=SourceType.MANUAL)

    storage.save_memory.assert_called()


@pytest.mark.asyncio
async def test_pipeline_calls_create_node() -> None:
    """Pipeline が graph.create_node を呼び出す。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    await pipeline.ingest("テストコンテンツ", source_type=SourceType.MANUAL)

    graph.create_node.assert_called()


# ===========================================================================
# トランザクション境界検証テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_embed_completes_before_save() -> None:
    """EmbeddingProvider の embed 完了前に save_memory が呼ばれないこと。

    SQLITE_BUSY 回避のため、埋め込み生成はトランザクション外で完了させる必要がある。
    """
    call_order: list[str] = []

    class TrackingEmbeddingProvider:
        dimension = 4

        async def embed(self, text: str) -> list[float]:
            # embed 完了を記録
            call_order.append("embed_start")
            await asyncio.sleep(0.01)  # ネットワーク I/O をシミュレート
            call_order.append("embed_complete")
            return [0.1, 0.2, 0.3, 0.4]

        async def embed_batch(self, texts: list[str]) -> list[list[float]]:
            call_order.append("embed_batch_start")
            await asyncio.sleep(0.01)
            call_order.append("embed_batch_complete")
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    class TrackingStorage:
        async def save_memory(self, memory: Memory) -> str:
            call_order.append("save_memory")
            return str(memory.id)

        async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
            return []

        async def vector_search(
            self, embedding: list[float], top_k: int, project: Any = None
        ) -> list:
            return []

        async def update_memory(self, memory_id: str, updates: dict) -> bool:
            return True

        async def get_memory(self, memory_id: str) -> Memory | None:
            return None

        async def delete_memory(self, memory_id: str) -> bool:
            return True

        async def keyword_search(self, query: str, top_k: int, project: Any = None) -> list:
            return []

        async def list_by_filter(self, filters: Any) -> list:
            return []

        async def get_vector_dimension(self) -> int | None:
            return 4

        async def dispose(self) -> None:
            pass

    storage = TrackingStorage()
    graph = _make_mock_graph()
    embedding_provider = TrackingEmbeddingProvider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    await pipeline.ingest("テストコンテンツ", source_type=SourceType.MANUAL)

    # embed_complete が save_memory より前に来ていることを確認
    assert "embed_complete" in call_order or "embed_batch_complete" in call_order
    assert "save_memory" in call_order

    embed_done_idx = max(
        (i for i, x in enumerate(call_order) if x in ("embed_complete", "embed_batch_complete")),
        default=-1,
    )
    save_idx = call_order.index("save_memory")

    assert embed_done_idx < save_idx, (
        f"embed が完了する前に save_memory が呼ばれました。\ncall_order: {call_order}"
    )


# ===========================================================================
# 排他制御テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_concurrent_same_content_dedup() -> None:
    """同一コンテンツの並行処理で重複登録が防止される。"""
    save_count = 0

    async def slow_save(memory: Memory) -> str:
        nonlocal save_count
        await asyncio.sleep(0.05)  # 処理時間をシミュレート
        save_count += 1
        return str(memory.id)

    storage = _make_mock_storage()
    storage.save_memory = slow_save
    # Deduplicator による短絡を防ぎ、パイプラインのインプロセスロック機構を検証する
    storage.vector_search = AsyncMock(return_value=[])
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    # 同じコンテンツ、同じドキュメント、同じチャンクインデックスを同時に2回処理
    # (memo_key が完全に一致する場合のみキャッシュが効く)
    same_content = "重複テストコンテンツ"
    chunk = RawContent(
        content=same_content,
        source_type=SourceType.MANUAL,
        metadata={"document_id": "same-doc", "chunk_index": 0},
    )
    results = await asyncio.gather(
        pipeline._process_chunk(chunk, base_metadata={}, prior_document_memories=[]),
        pipeline._process_chunk(chunk, base_metadata={}, prior_document_memories=[]),
    )

    # 両方の呼び出しが完了すること
    assert len(results) == 2
    # 排他制御（memo_key の一致）により save_memory が重複して呼ばれないこと
    assert save_count == 1


@pytest.mark.asyncio
async def test_pipeline_dispose_closes_embedding_provider_and_url_adapter() -> None:
    """dispose() が保持リソースの終了処理を呼ぶ。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()

    embedding_provider = MagicMock()
    del embedding_provider.dispose
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    url_adapter = MagicMock()
    url_adapter.aclose = AsyncMock()
    pipeline._url_adapter = url_adapter

    await pipeline.dispose()

    url_adapter.aclose.assert_awaited_once()
    embedding_provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_dispose_closes_embedding_provider_and_url_adapter_fallback() -> None:
    """dispose() が dispose 失敗時に fallback として close を呼ぶ。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()

    embedding_provider = MagicMock()
    embedding_provider.dispose = AsyncMock(side_effect=Exception("dispose error"))
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    url_adapter = MagicMock()
    url_adapter.aclose = AsyncMock()
    pipeline._url_adapter = url_adapter

    await pipeline.dispose()

    embedding_provider.dispose.assert_awaited_once()
    embedding_provider.close.assert_awaited_once()
    url_adapter.aclose.assert_awaited_once()


# ===========================================================================
# URL ソースのテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_url_source() -> None:
    """URL ソースが正しく処理される。"""
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    # URL アダプターのモック化
    with patch.object(pipeline, "_fetch_url_content") as mock_fetch:
        mock_fetch.return_value = [
            RawContent(
                content="# テストページ\n\nURL からのコンテンツです。",
                source_type=SourceType.URL,
                metadata={"url": "https://example.com/test"},
            )
        ]
        results = await pipeline.ingest(
            "https://example.com/test",
            source_type=SourceType.URL,
        )

    assert len(results) >= 1


@pytest.mark.asyncio
async def test_pipeline_conversation_source_uses_conversation_adapter() -> None:
    """会話ソースが ConversationAdapter 経由で turn メタデータを保持する。"""
    saved_memories: list[Memory] = []

    async def capture_save(memory: Memory) -> str:
        saved_memories.append(memory)
        return str(memory.id)

    storage = _make_mock_storage()
    storage.save_memory = capture_save
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    await pipeline.ingest(
        "User: こんにちは\nAssistant: 了解です\nUser: 次へ",
        source_type=SourceType.CONVERSATION,
    )

    assert saved_memories
    assert saved_memories[0].source_type == SourceType.CONVERSATION
    assert saved_memories[0].source_metadata["turn_start"] == 0
    assert saved_memories[0].source_metadata["turn_end"] == 2


# ===========================================================================
# IngestionResult テスト
# ===========================================================================


def test_ingestion_result_fields() -> None:
    """IngestionResult に必須フィールドが含まれる。"""
    result = IngestionResult(
        memory_id="test-id",
        action=DeduplicationAction.INSERT,
    )
    assert result.memory_id == "test-id"
    assert result.action == DeduplicationAction.INSERT


# ===========================================================================
# メタデータ伝播テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_metadata_propagation() -> None:
    """メタデータが保存される Memory に伝播する。"""
    saved_memories: list[Memory] = []

    async def capture_save(memory: Memory) -> str:
        saved_memories.append(memory)
        return str(memory.id)

    storage = _make_mock_storage()
    storage.save_memory = capture_save
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )
    await pipeline.ingest(
        "テストコンテンツ",
        source_type=SourceType.MANUAL,
        metadata={"project": "my-project", "session_id": "sess-001"},
    )

    # ステップ10: 最終検証
    # 全ての保存済みメモリが正しいプロジェクトに属していることを確認
    assert len(saved_memories) >= 1
    for memory in saved_memories:
        # Memory.project が最優先。常に設定されているはず。
        assert memory.project == "my-project"
        assert memory.source_metadata["session_id"] == "sess-001"


@pytest.mark.asyncio
async def test_pipeline_memo_key_uniqueness_with_document_id() -> None:
    """同一コンテンツで異なる document_id を持つ場合、キャッシュキーが分離されることを検証。"""
    # モックのセットアップ
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    # 処理を遅延させて並行実行中にキャッシュが効くようにする
    embedding_provider = _make_mock_embedding_provider(delay=0.1)

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(),
    )

    content = "共通のコンテンツ"
    # 同じコンテンツだが document_id が異なる2つのチャンク
    chunk1 = RawContent(
        content=content,
        source_type=SourceType.MANUAL,
        metadata={"document_id": "doc-A", "chunk_index": 0},
    )
    chunk2 = RawContent(
        content=content,
        source_type=SourceType.MANUAL,
        metadata={"document_id": "doc-B", "chunk_index": 0},
    )

    # 並行実行
    # memo_key に document_id が含まれていない場合、
    # 2つ目のタスクは 1つ目のタスクの完了を待ってその結果を返してしまう（キャッシュ衝突）。
    results = await asyncio.gather(
        pipeline._process_chunk(chunk1, base_metadata={}, prior_document_memories=[]),
        pipeline._process_chunk(chunk2, base_metadata={}, prior_document_memories=[]),
    )

    assert results[0] is not None
    assert results[1] is not None
    # 各々の結果が自身のドキュメントIDを反映していることを確認
    # (現状の _process_chunk_locked 実装では、保存された Memory の metadata に document_id が入る)
    assert results[0].persisted_memory.source_metadata["document_id"] == "doc-A"
    assert results[1].persisted_memory.source_metadata["document_id"] == "doc-B"
    # 各々が保存されている（save_memory が 2回呼ばれている）ことを確認
    assert storage.save_memory.call_count == 2
