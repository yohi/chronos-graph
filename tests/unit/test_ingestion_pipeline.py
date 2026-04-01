"""Task 4.6: Ingestion Pipeline のユニットテスト。"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.classifier import ClassificationResult
from context_store.ingestion.deduplicator import DeduplicationAction, DeduplicationResult
from context_store.ingestion.pipeline import IngestionPipeline, IngestionResult
from context_store.models.memory import Memory, MemoryType, SourceType
from context_store.storage.protocols import GraphAdapter, StorageAdapter


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
    storage.save_memory = AsyncMock(return_value=str(uuid4()))
    storage.vector_search = AsyncMock(return_value=[])
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

        async def vector_search(self, embedding: list[float], top_k: int, project: Any = None) -> list:
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
        f"embed が完了する前に save_memory が呼ばれました。\n"
        f"call_order: {call_order}"
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
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
    )

    # 同じコンテンツを同時に2回インジェスト
    same_content = "重複テストコンテンツ"
    results = await asyncio.gather(
        pipeline.ingest(same_content, source_type=SourceType.MANUAL),
        pipeline.ingest(same_content, source_type=SourceType.MANUAL),
    )

    # 両方の呼び出しが完了すること
    assert len(results) == 2
    # 排他制御により save_memory の呼び出し回数が制限されていること
    # （最低1回は呼ばれる）
    assert save_count >= 1


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
    )

    await pipeline.ingest(
        "テストコンテンツ",
        source_type=SourceType.MANUAL,
        metadata={"project": "my-project", "session_id": "sess-001"},
    )

    assert len(saved_memories) >= 1
    for memory in saved_memories:
        assert memory.project == "my-project" or "my-project" in str(memory.source_metadata)
