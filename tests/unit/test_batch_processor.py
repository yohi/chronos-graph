"""BatchProcessor のユニットテスト。"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.ingestion.batch_processor import BatchProcessor


class TestEstimateChunks:
    """BatchProcessor.estimate_chunks() のテスト。"""

    def test_estimate_chunks_with_qa_pairs(self) -> None:
        """Q&A ペアを含む会話ログのチャンク数を推定できる。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        conversation_log = (
            "User: こんにちは\nAssistant: はい、こんにちは\n"
            "User: 質問があります\nAssistant: どうぞ\n"
            "User: Pythonについて教えてください\nAssistant: Pythonは...\n"
            "User: ありがとう\nAssistant: どういたしまして\n"
        )
        result = processor.estimate_chunks(conversation_log)
        # 4ターンペア → MAX_TURNS_PER_CHUNK=3 で分割 → 2チャンク程度
        assert isinstance(result, int)
        assert result >= 1

    def test_estimate_chunks_empty_returns_zero(self) -> None:
        """空文字列は 0 チャンクを返す。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = processor.estimate_chunks("")
        assert result == 0

    def test_estimate_chunks_no_qa_pattern(self) -> None:
        """Q&A パターンなしのテキストも 0 以上のチャンク数を返す。"""
        mock_pipeline = MagicMock()
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        result = processor.estimate_chunks("ランダムテキスト\n改行のみ")
        assert isinstance(result, int)
        assert result >= 0


class TestProcess:
    """BatchProcessor.process() のテスト。"""

    @pytest.mark.asyncio
    async def test_process_delegates_to_ingestion_pipeline(self) -> None:
        """process() は IngestionPipeline.ingest() に委譲する。"""
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(return_value=[])
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        await processor.process(
            "User: test\nAssistant: response",
            session_id="test-session",
            project="test-project",
            tags=["tag1"],
        )

        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args
        assert call_args[0][0] == "User: test\nAssistant: response"

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
        """IngestionPipeline.ingest() が例外を投げた場合、ログに記録する。"""
        caplog.set_level(logging.ERROR, logger="context_store.ingestion.batch_processor")
        mock_pipeline = MagicMock()
        mock_pipeline.ingest = AsyncMock(side_effect=RuntimeError("pipeline error"))
        processor = BatchProcessor(ingestion_pipeline=mock_pipeline)

        # process() は例外をキャッチしてログに記録する
        await processor.process(
            "User: test\nAssistant: fail",
            session_id="test-session",
        )

        assert any("Batch processing failed" in record.message for record in caplog.records)
