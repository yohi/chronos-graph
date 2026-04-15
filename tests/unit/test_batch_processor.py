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
        """process() は IngestionPipeline.ingest() に委譲し、成功時に True を返す。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        conversation_log = "User: test\nAssistant: response"
        result = await processor.process(
            conversation_log,
            session_id="test-session",
            project="test-project",
            tags=["tag1"],
        )

        assert result is True
        mock_pipeline.ingest.assert_called_once_with(
            conversation_log,
            source_type=SourceType.CONVERSATION,
            metadata={
                "session_id": "test-session",
                "project": "test-project",
                "tags": ["tag1"],
            },
        )

    @pytest.mark.asyncio
    async def test_process_passes_metadata(self) -> None:
        """process() は session_id, project, tags をメタデータに含める。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        conversation_log = "User: hello\nAssistant: hi"
        await processor.process(
            conversation_log,
            session_id="sess-123",
            project="my-project",
            tags=["important"],
        )

        mock_pipeline.ingest.assert_called_once_with(
            conversation_log,
            source_type=SourceType.CONVERSATION,
            metadata={
                "session_id": "sess-123",
                "project": "my-project",
                "tags": ["important"],
            },
        )

    @pytest.mark.asyncio
    async def test_process_logs_error_and_re_raises_on_pipeline_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """IngestionPipeline.ingest() が例外を投げた場合、ログに記録し、例外を再送する。"""
        logger_name = "context_store.ingestion.batch_processor"
        caplog.set_level(logging.ERROR, logger=logger_name)

        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(side_effect=RuntimeError("pipeline error"))
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        # 例外が再送されることを確認
        with pytest.raises(RuntimeError, match="pipeline error"):
            await processor.process(
                "User: test\nAssistant: fail",
                session_id="test-session",
            )

        assert any("Batch processing failed" in record.message for record in caplog.records)
