from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.models.search import SearchStrategy
from context_store.retrieval.pipeline import RetrievalPipeline
from context_store.retrieval.result_fusion import ResultFusion


@pytest.mark.asyncio
async def test_search_passes_project_to_vector_and_keyword_search() -> None:
    vector_search = MagicMock()
    vector_search.search = AsyncMock(return_value=[])
    keyword_search = MagicMock()
    keyword_search.search = AsyncMock(return_value=[])
    graph_traversal = MagicMock()
    graph_traversal.traverse = AsyncMock()
    post_processor = MagicMock()
    post_processor.process = AsyncMock(return_value=[])

    pipeline = RetrievalPipeline(
        query_analyzer=MagicMock(),
        vector_search=vector_search,
        keyword_search=keyword_search,
        graph_traversal=graph_traversal,
        result_fusion=ResultFusion(),
        post_processor=post_processor,
        storage_adapter=MagicMock(),
    )

    await pipeline.search(
        "query",
        project="proj-a",
        top_k=7,
        strategy=SearchStrategy(vector_weight=0.5, keyword_weight=0.5, graph_weight=0.0),
    )

    vector_search.search.assert_awaited_once_with("query", top_k=7, project="proj-a")
    keyword_search.search.assert_awaited_once_with("query", top_k=7, project="proj-a")
    graph_traversal.traverse.assert_not_called()


@pytest.mark.asyncio
async def test_search_filters_fused_results_by_project() -> None:
    proj_a_memory = Memory(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        content="project a memory",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        project="proj-a",
    )
    proj_b_memory = Memory(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        content="project b memory",
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        project="proj-b",
    )
    vector_search = MagicMock()
    vector_search.search = AsyncMock(
        return_value=[
            ScoredMemory(memory=proj_b_memory, score=0.99, source=MemorySource.VECTOR),
            ScoredMemory(memory=proj_a_memory, score=0.98, source=MemorySource.VECTOR),
        ]
    )
    keyword_search = MagicMock()
    keyword_search.search = AsyncMock(return_value=[])
    post_processor = MagicMock()
    post_processor.process = AsyncMock(side_effect=lambda results, **_: results)

    pipeline = RetrievalPipeline(
        query_analyzer=MagicMock(),
        vector_search=vector_search,
        keyword_search=keyword_search,
        graph_traversal=MagicMock(),
        result_fusion=ResultFusion(),
        post_processor=post_processor,
        storage_adapter=MagicMock(),
    )

    result = await pipeline.search(
        "query",
        project="proj-a",
        top_k=10,
        strategy=SearchStrategy(vector_weight=0.5, keyword_weight=0.5, graph_weight=0.0),
    )

    assert result["total_count"] == 1
    assert [item["memory_id"] for item in result["results"]] == [str(proj_a_memory.id)]
