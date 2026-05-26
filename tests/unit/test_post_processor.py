from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from context_store.models.memory import (
    Memory,
    MemorySource,
    MemoryType,
    ScoredMemory,
    SourceType,
)
from context_store.retrieval.post_processor import PostProcessor


def _scored(memory_id: str) -> ScoredMemory:
    memory = Memory(
        id=UUID(memory_id),
        content="x",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
    )
    return ScoredMemory(memory=memory, score=0.9, source=MemorySource.VECTOR)


@pytest.mark.asyncio
async def test_post_processor_calls_bulk_increment_once():
    storage = MagicMock()
    storage.increment_memory_access_counts = AsyncMock(return_value=3)
    storage.increment_memory_access_count = AsyncMock()

    pp = PostProcessor(storage_adapter=storage)
    results = [
        _scored("550e8400-e29b-41d4-a716-446655440001"),
        _scored("550e8400-e29b-41d4-a716-446655440002"),
        _scored("550e8400-e29b-41d4-a716-446655440003"),
    ]

    await pp.process(results=results)

    storage.increment_memory_access_counts.assert_awaited_once_with(
        [
            "550e8400-e29b-41d4-a716-446655440001",
            "550e8400-e29b-41d4-a716-446655440002",
            "550e8400-e29b-41d4-a716-446655440003",
        ]
    )
    storage.increment_memory_access_count.assert_not_called()


@pytest.mark.asyncio
async def test_post_processor_empty_results_skips_bulk_call():
    storage = MagicMock()
    storage.increment_memory_access_counts = AsyncMock()

    pp = PostProcessor(storage_adapter=storage)
    await pp.process(results=[])

    storage.increment_memory_access_counts.assert_not_awaited()
