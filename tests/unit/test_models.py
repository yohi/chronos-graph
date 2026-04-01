import pytest
from uuid import uuid4
from pydantic import ValidationError

from context_store.models.graph import Edge, GraphResult
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.models.search import SearchFilters, SearchStrategy


def test_memory_creation():
    m = Memory(
        id=uuid4(),
        content="JWT認証をベースに統一する方針に決定",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        source_metadata={"agent": "claude-code", "project": "/my/project"},
        embedding=[0.1] * 768,
        importance_score=0.8,
        tags=["auth", "backend"],
    )
    assert m.memory_type == MemoryType.EPISODIC
    assert m.archived_at is None
    assert m.access_count == 0


def test_memory_type_enum():
    assert MemoryType.EPISODIC.value == "episodic"
    assert MemoryType.SEMANTIC.value == "semantic"
    assert MemoryType.PROCEDURAL.value == "procedural"


def test_memory_numeric_fields_are_validated():
    with pytest.raises(ValidationError):
        Memory(
            content="invalid",
            memory_type=MemoryType.SEMANTIC,
            source_type=SourceType.MANUAL,
            semantic_relevance=1.2,
        )

    with pytest.raises(ValidationError):
        Memory(
            content="invalid",
            memory_type=MemoryType.SEMANTIC,
            source_type=SourceType.MANUAL,
            access_count=-1,
        )


def test_scored_memory_source_uses_enum():
    scored = ScoredMemory(
        memory=Memory(
            content="valid",
            memory_type=MemoryType.SEMANTIC,
            source_type=SourceType.MANUAL,
        ),
        score=0.9,
        source="graph",
    )

    assert scored.source == MemorySource.GRAPH


def test_search_models_validate_constraints():
    strategy = SearchStrategy(vector_weight=0.4, keyword_weight=0.3, graph_weight=0.3, graph_depth=1)
    filters = SearchFilters(memory_type="episodic", top_k=5, max_tokens=1000)

    assert filters.memory_type == MemoryType.EPISODIC
    assert strategy.graph_depth == 1

    with pytest.raises(ValidationError):
        SearchStrategy(vector_weight=0.8, keyword_weight=0.5, graph_weight=0.3)

    with pytest.raises(ValidationError):
        SearchStrategy(vector_weight=0.4, keyword_weight=0.2, graph_weight=0.3)

    with pytest.raises(ValidationError):
        SearchStrategy(graph_depth=0)

    with pytest.raises(ValidationError):
        SearchFilters(top_k=0)

    with pytest.raises(ValidationError):
        SearchFilters(max_tokens=100001)


def test_graph_result_rejects_negative_depth():
    with pytest.raises(ValidationError):
        GraphResult(nodes=[], edges=[Edge(from_id="a", to_id="b", edge_type="refers_to")], traversal_depth=-1)
