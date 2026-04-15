"""BatchProcessor のユニットテスト。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.ingestion.batch_processor import BatchProcessor


class TestEstimateChunks:
    """BatchProcessor.estimate_chunks() のテスト。"""

    @pytest.mark.asyncio
    async def test_estimate_chunks_with_mocked_chunker(self) -> None:
        """Chunker をモックして、estimate_chunks が正しく合算を行うか検証。"""
        from context_store.ingestion.adapters import ConversationAdapter

        mock_pipeline = MagicMock()
        # 1つに収まるサイズ
        mock_pipeline._conversation_adapter = ConversationAdapter(chunk_size=10)

        mock_chunker = MagicMock()
        # 2つのチャンクを返すようにモック
        mock_chunker.chunk.return_value = [MagicMock(), MagicMock()]

        processor = BatchProcessor(ingestion_pipeline=mock_pipeline, chunker=mock_chunker)

        result = await processor.estimate_chunks("User: hello\nAssistant: hi")

        assert result == 2
        mock_chunker.chunk.assert_called_once()

    @pytest.mark.asyncio
    async def test_estimate_chunks_empty_returns_zero(self) -> None:
        """空文字列は 0 チャンクを返す。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = await processor.estimate_chunks("")
        assert result == 0

    @pytest.mark.asyncio
    async def test_estimate_chunks_reflects_adapter_split_with_mock(self) -> None:
        """Adapter による分割が反映され、各分割に対して Chunker が呼ばれることを確認。"""
        from context_store.ingestion.adapters import ConversationAdapter

        mock_pipeline = MagicMock()
        # 1往復ごとに分割
        mock_pipeline._conversation_adapter = ConversationAdapter(chunk_size=2)

        mock_chunker = MagicMock()
        # 各呼び出しで 1チャンク返す
        mock_chunker.chunk.return_value = [MagicMock()]

        processor = BatchProcessor(ingestion_pipeline=mock_pipeline, chunker=mock_chunker)

        # 3往復 (6ターン) -> Adapter で 3つの RawContent に分割されるはず
        conversation_log = (
            "User: T1\nAssistant: R1\nUser: T2\nAssistant: R2\nUser: T3\nAssistant: R3\n"
        )

        result = await processor.estimate_chunks(conversation_log)

        # 3つの分割それぞれで 1チャンク返るので合計 3
        assert result == 3
        assert mock_chunker.chunk.call_count == 3


class TestProcess:
    """BatchProcessor.process() のテスト。"""

    @pytest.mark.asyncio
    async def test_process_delegates_to_ingestion_pipeline(self) -> None:
        """process() は IngestionPipeline.ingest() に委譲し、True を返す。"""
        from context_store.models.memory import SourceType

        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        success = await processor.process(
            "User: test\nAssistant: response",
            session_id="test-session",
            project="test-project",
            tags=["tag1"],
        )

        assert success is True
        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args
        assert call_args[0][0] == "User: test\nAssistant: response"
        assert call_args[1]["source_type"] == SourceType.CONVERSATION

    @pytest.mark.asyncio
    async def test_process_passes_metadata(self) -> None:
        """process() は session_id, project, tags をメタデータに含める。"""
        from context_store.models.memory import SourceType

        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        await processor.process(
            "User: hello\nAssistant: hi",
            session_id="sess-123",
            project="my-project",
            tags=["important"],
        )

        call_kwargs = mock_pipeline.ingest.call_args[1]
        assert call_kwargs["source_type"] == SourceType.CONVERSATION
        metadata = call_kwargs["metadata"]
        assert metadata["session_id"] == "sess-123"
        assert metadata["project"] == "my-project"
        assert metadata["tags"] == ["important"]

    @pytest.mark.asyncio
    async def test_process_returns_false_on_pipeline_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """IngestionPipeline.ingest() が例外を投げた場合、False を返しログに記録する。"""
        caplog.set_level(logging.ERROR, logger="context_store.ingestion.batch_processor")
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(side_effect=RuntimeError("pipeline error"))
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        # process() は例外をキャッチして False を返す
        success = await processor.process(
            "User: test\nAssistant: fail",
            session_id="test-session",
        )

        assert success is False
        assert any("Batch processing failed" in record.message for record in caplog.records)
