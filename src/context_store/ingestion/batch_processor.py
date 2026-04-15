"""BatchProcessor: 会話ログのバッチ処理ラッパー。

IngestionPipeline への委譲を行う薄いラッパー。
チャンク数の推定と、バックグラウンドバッチ処理のエントリーポイントを提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from context_store.ingestion.adapters import RawContent
from context_store.ingestion.chunker import Chunker
from context_store.models.memory import SourceType

if TYPE_CHECKING:
    from context_store.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Thin wrapper over IngestionPipeline for batch conversation log processing.

    Delegates all processing to IngestionPipeline.ingest().
    """

    def __init__(
        self,
        ingestion_pipeline: "IngestionPipeline",
        chunker: Chunker | None = None,
    ) -> None:
        self._pipeline = ingestion_pipeline
        self._chunker = chunker or Chunker()

    def estimate_chunks(self, conversation_log: str) -> int:
        """Estimate chunk count using Chunker dry-run (no side effects).

        Creates a temporary RawContent with source_type=CONVERSATION,
        passes it through Chunker.chunk() to count yielded chunks,
        but does NOT persist anything. This is a pure read-only estimation.
        """
        if not conversation_log:
            return 0

        raw = RawContent(
            content=conversation_log,
            source_type=SourceType.CONVERSATION,
            metadata={},
        )
        # Chunker.chunk() はジェネレータなので、全件をカウントする
        return sum(1 for _ in self._chunker.chunk(raw))

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
        1. IngestionPipeline.ingest() with source_type=CONVERSATION
        2. Errors are logged (committed chunks are retained, uncommitted are lost)
        """
        metadata: dict[str, object] = {"session_id": session_id}
        if project is not None:
            metadata["project"] = project
        if tags:
            metadata["tags"] = tags

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
            return False
