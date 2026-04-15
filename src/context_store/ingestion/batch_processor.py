"""BatchProcessor: 会話ログのバッチ処理ラッパー。

IngestionPipeline への委譲を行う薄いラッパー。
チャンク数の推定と、バックグラウンドバッチ処理のエントリーポイントを提供する。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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

    async def estimate_chunks(self, conversation_log: str) -> int:
        """Estimate chunk count using IngestionPipeline logic (no side effects).

        1. ConversationAdapter splits log into turn-based RawContent (e.g. 5 turns).
        2. Chunker.chunk() further splits each into Q&A pairs (e.g. 3 turns).
        """
        if not conversation_log:
            return 0

        # Pipeline と同様に Adapter を通して分割してからカウントする
        raw_contents = await self._pipeline._conversation_adapter.adapt(
            conversation_log,
            metadata={},
        )

        total_chunks = 0
        for raw in raw_contents:
            total_chunks += sum(1 for _ in self._chunker.chunk(raw))

        return total_chunks

    async def process(
        self,
        conversation_log: str,
        *,
        session_id: str,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Background batch processing entry point.

        Returns:
            bool: True if processing completed successfully, False otherwise.
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
