"""BatchProcessor: 会話ログのバッチ処理ラッパー。

IngestionPipeline への委譲を行う薄いラッパー。
チャンク数の推定と、バックグラウンドバッチ処理のエントリーポイントを提供する。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from context_store.models.memory import SourceType

if TYPE_CHECKING:
    from context_store.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Thin wrapper over IngestionPipeline for batch conversation log processing.

    Delegates all processing to IngestionPipeline.
    """

    def __init__(
        self,
        ingestion_pipeline: IngestionPipeline,
        batch_max_concurrent_jobs: int = 3,
    ) -> None:
        if batch_max_concurrent_jobs < 1:
            raise ValueError("batch_max_concurrent_jobs must be at least 1")
        self._pipeline = ingestion_pipeline
        self._chunker = ingestion_pipeline.chunker
        self._semaphore = asyncio.Semaphore(batch_max_concurrent_jobs)

    async def estimate_chunks(self, conversation_log: str) -> int:
        """実際の取り込みフローに基づき、会話ログのチャンク数を推定する。

        IngestionPipeline.estimate_chunks() に委譲することで、
        Adapter による分割ロジックとの乖離を防ぐ。
        """
        return await self._pipeline.estimate_chunks(
            conversation_log,
            source_type=SourceType.CONVERSATION,
        )

    async def process(
        self,
        conversation_log: str,
        *,
        session_id: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Background batch processing entry point.

        Flow:
        1. Acquire semaphore to limit concurrency
        2. IngestionPipeline.ingest() with source_type=CONVERSATION
        3. Errors are logged and re-raised (committed chunks are retained, uncommitted are lost)

        Returns:
            bool: True if processing completed successfully.

        Raises:
            Exception: If ingestion pipeline fails.
        """
        metadata: dict[str, object] = {"session_id": session_id}
        if project is not None:
            metadata["project"] = project
        if tags:
            metadata["tags"] = tags

        async with self._semaphore:
            try:
                await self._pipeline.ingest(
                    conversation_log,
                    source_type=SourceType.CONVERSATION,
                    metadata=metadata,
                )
                logger.info(
                    "Batch processing completed: session_id=%s",
                    session_id,
                )
                return True
            except Exception:
                logger.error(
                    "Batch processing failed: session_id=%s",
                    session_id,
                    exc_info=True,
                )
                raise
