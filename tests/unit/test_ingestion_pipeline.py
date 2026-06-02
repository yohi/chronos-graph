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


# ===========================================================================
# Estimate Chunks テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_pipeline_estimate_chunks_conversation_discrepancy() -> None:
    """指摘事項に基づき、6ターンの会話が 3チャンクとして推定されることを検証。

    Flow:
    1. ConversationAdapter (chunk_size=5) -> [t1-t5, t6] の 2グループ
    2. Chunker (MAX_TURNS_PER_CHUNK=3) -> [t1-t3, t4-t5] + [t6] = 3チャンク
    """
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()

    # デフォルト設定 (conversation_chunk_size=5, MAX_TURNS_PER_CHUNK=3) を使用
    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=make_settings(conversation_chunk_size=5),
    )

    # 6ターンの会話ログを作成（6つの発話）
    conversation_log = "User: t1\nAssistant: r1\nUser: t2\nAssistant: r2\nUser: t3\nAssistant: r3\n"

    count = await pipeline.estimate_chunks(
        conversation_log,
        source_type=SourceType.CONVERSATION,
    )

    # 指摘に基づき、3 チャンクになるはず
    # 1. Adapter が 5ターンと 1ターンに分割 ([t1,r1,t2,r2,t3], [r3] は間違い。
    #    User: t1 (1), Assistant: r1 (2), User: t2 (3), Assistant: r2 (4),
    #    User: t3 (5), Assistant: r3 (6)
    #    Adapter(5) -> [t1,r1,t2,r2,t3] と [Assistant: r3]
    #    Chunker(3) -> ([t1,r1,t2], [r2,t3]) と ([r3])
    #    合計 3 チャンク。
    #    (もし Adapter なしで直接 Chunker に渡すと [t1,r1,t2] と
    #    [r2,t3,Assistant: r3] の 2 チャンクになる)
    assert count == 3


@pytest.mark.asyncio
async def test_ingest_calls_embed_batch_once_for_all_chunks(monkeypatch) -> None:
    """IngestionPipeline.ingest must batch-embed all chunks in a single call."""
    storage = MagicMock()
    storage.vector_search = AsyncMock(return_value=[])
    storage.save_memory = AsyncMock(return_value="550e8400-e29b-41d4-a716-446655440099")
    storage.list_by_filter = AsyncMock(return_value=[])

    embedding_provider = MagicMock()
    embedding_provider.embed_batch = AsyncMock(return_value=[[0.1] * 8 for _ in range(3)])
    embedding_provider.embed = AsyncMock(return_value=[0.1] * 8)
    embedding_provider.dimension = 8
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=None,
        embedding_provider=embedding_provider,
        settings=None,
    )

    fake_chunks = [
        RawContent(
            content=f"c{i}",
            source_type=SourceType.MANUAL,
            metadata={"chunk_index": i, "chunk_count": 3},
        )
        for i in range(3)
    ]

    def fake_chunk(raw: RawContent):
        yield from fake_chunks

    monkeypatch.setattr(pipeline._chunker, "chunk", fake_chunk)

    await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    embedding_provider.embed_batch.assert_awaited_once()
    embed_call = embedding_provider.embed_batch.await_args
    assert embed_call.args[0] == ["c0", "c1", "c2"]
    embedding_provider.embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_processes_chunks_in_parallel_without_graph(monkeypatch) -> None:
    storage = _make_mock_storage()
    embedding_provider = _make_mock_embedding_provider()
    pipeline = IngestionPipeline(
        storage=storage,
        graph=None,
        embedding_provider=embedding_provider,
        settings=None,
    )

    fake_chunks = [
        RawContent(content=f"c{i}", source_type=SourceType.MANUAL, metadata={"chunk_index": i})
        for i in range(4)
    ]

    def fake_chunk(raw: RawContent):
        yield from fake_chunks

    concurrent = 0
    max_concurrent = 0

    async def tracked_process(
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        precomputed_embedding: list[float] | None = None,
    ) -> IngestionResult:
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1
        return IngestionResult(
            memory_id=chunk.content,
            action=DeduplicationAction.INSERT,
            chunk_index=int(chunk.metadata["chunk_index"]),
        )

    monkeypatch.setattr(pipeline._chunker, "chunk", fake_chunk)
    monkeypatch.setattr(pipeline, "_process_chunk", tracked_process)
    pipeline._chunk_parallel_semaphore = asyncio.Semaphore(2)

    results = await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    assert [result.memory_id for result in results] == ["c0", "c1", "c2", "c3"]
    assert max_concurrent == 2


@pytest.mark.asyncio
async def test_ingest_processes_chunks_sequentially_with_graph(monkeypatch) -> None:
    storage = _make_mock_storage()
    graph = _make_mock_graph()
    embedding_provider = _make_mock_embedding_provider()
    pipeline = IngestionPipeline(
        storage=storage,
        graph=graph,
        embedding_provider=embedding_provider,
        settings=None,
    )

    fake_chunks = [
        RawContent(content=f"c{i}", source_type=SourceType.MANUAL, metadata={"chunk_index": i})
        for i in range(3)
    ]

    def fake_chunk(raw: RawContent):
        yield from fake_chunks

    concurrent = 0
    max_concurrent = 0

    async def tracked_process(
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        precomputed_embedding: list[float] | None = None,
    ) -> IngestionResult:
        nonlocal concurrent, max_concurrent
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        await asyncio.sleep(0.02)
        concurrent -= 1
        return IngestionResult(
            memory_id=chunk.content,
            action=DeduplicationAction.INSERT,
            chunk_index=int(chunk.metadata["chunk_index"]),
        )

    monkeypatch.setattr(pipeline._chunker, "chunk", fake_chunk)
    monkeypatch.setattr(pipeline, "_process_chunk", tracked_process)

    results = await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    assert [result.memory_id for result in results] == ["c0", "c1", "c2"]
    assert max_concurrent == 1


@pytest.mark.asyncio
async def test_ingest_propagates_embed_batch_failure() -> None:
    """When embed_batch raises, ingest() must abort instead of partially succeeding."""
    storage = MagicMock()
    storage.vector_search = AsyncMock(return_value=[])
    storage.save_memory = AsyncMock()
    storage.list_by_filter = AsyncMock(return_value=[])

    embedding_provider = MagicMock()
    embedding_provider.embed_batch = AsyncMock(side_effect=RuntimeError("embedding backend down"))
    embedding_provider.embed = AsyncMock()
    embedding_provider.dimension = 8
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=None,
        embedding_provider=embedding_provider,
        settings=None,
    )

    with pytest.raises(RuntimeError, match="embedding backend down"):
        await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    storage.save_memory.assert_not_called()
    embedding_provider.embed.assert_not_called()


class TestGraphSyncMode:
    """graph_sync_mode による GraphLinker 制御テスト。"""

    @pytest.mark.asyncio
    async def test_pipeline_skips_neo4j_write_in_async_outbox_mode(self) -> None:
        """async_outbox モードでは GraphLinker に graph=None が渡される。"""
        from unittest.mock import patch

        storage = _make_mock_storage()
        graph = _make_mock_graph()
        embedding_provider = _make_mock_embedding_provider()

        with patch("context_store.ingestion.pipeline.GraphLinker") as mock_linker_cls:
            IngestionPipeline(
                storage=storage,
                graph=graph,
                embedding_provider=embedding_provider,
                settings=make_settings(),
                graph_sync_mode="async_outbox",
            )

            # GraphLinker が graph=None で初期化されたことを確認
            mock_linker_cls.assert_called_once()
            call_kwargs = mock_linker_cls.call_args.kwargs
            assert call_kwargs.get("graph") is None
            assert call_kwargs.get("storage") is storage

    @pytest.mark.asyncio
    async def test_pipeline_passes_graph_in_sync_mode(self) -> None:
        """sync モードでは GraphLinker に元の graph が渡される。"""
        from unittest.mock import patch

        storage = _make_mock_storage()
        graph = _make_mock_graph()
        embedding_provider = _make_mock_embedding_provider()

        with patch("context_store.ingestion.pipeline.GraphLinker") as mock_linker_cls:
            IngestionPipeline(
                storage=storage,
                graph=graph,
                embedding_provider=embedding_provider,
                settings=make_settings(),
                graph_sync_mode="sync",
            )

            mock_linker_cls.assert_called_once()
            call_kwargs = mock_linker_cls.call_args.kwargs
            assert call_kwargs.get("graph") is graph
            assert call_kwargs.get("storage") is storage
