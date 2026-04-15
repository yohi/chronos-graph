"""BatchProcessor のユニットテスト。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.ingestion.batch_processor import BatchProcessor
from context_store.models.memory import SourceType


class TestEstimateChunks:
    """BatchProcessor.estimate_chunks() のテスト。"""

    @pytest.mark.asyncio
    async def test_estimate_chunks_delegates_to_pipeline(self) -> None:
        """estimate_chunks() は IngestionPipeline.estimate_chunks() に委譲する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.estimate_chunks = AsyncMock(return_value=5)
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        conversation_log = "User: hello\nAssistant: hi"
        result = await processor.estimate_chunks(conversation_log)

        assert result == 5
        mock_pipeline.estimate_chunks.assert_called_once_with(
            conversation_log,
            source_type=SourceType.CONVERSATION,
        )

    @pytest.mark.asyncio
    async def test_estimate_chunks_empty_handled_by_pipeline(self) -> None:
        """空文字列の処理もパイプラインに委譲する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.estimate_chunks = AsyncMock(return_value=0)
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = await processor.estimate_chunks("")
        assert result == 0
        mock_pipeline.estimate_chunks.assert_called_once_with(
            "",
            source_type=SourceType.CONVERSATION,
        )


class TestProcess:
    """BatchProcessor.process() のテスト。"""

    @pytest.mark.asyncio
    async def test_process_delegates_to_ingestion_pipeline(self) -> None:
        """process() は IngestionPipeline.ingest() に委譲する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = await processor.process(
            "User: test\nAssistant: response",
            session_id="test-session",
            project="test-project",
            tags=["tag1"],
        )

        assert result is True
        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args
        assert call_args[0][0] == "User: test\nAssistant: response"
        # source_type の検証を追加
        assert call_args[1]["source_type"] == SourceType.CONVERSATION

    @pytest.mark.asyncio
    async def test_process_passes_metadata(self) -> None:
        """process() は session_id, project, tags をメタデータに含める。"""
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
        metadata = call_kwargs["metadata"]
        assert metadata["session_id"] == "sess-123"
        assert metadata["project"] == "my-project"
        assert metadata["tags"] == ["important"]

    @pytest.mark.asyncio
    async def test_process_logs_error_on_pipeline_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """IngestionPipeline.ingest() が例外を投げた場合、ログに記録し False を返す。"""
        caplog.set_level(logging.ERROR, logger="context_store.ingestion.batch_processor")
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(side_effect=RuntimeError("pipeline error"))
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        # process() は例外をキャッチしてログに記録し、False を返す
        result = await processor.process(
            "User: test\nAssistant: fail",
            session_id="test-session",
        )

        assert result is False
        assert any("Batch processing failed" in record.message for record in caplog.records)
