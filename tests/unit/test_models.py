from uuid import uuid4
from context_store.models.memory import Memory, MemoryType, SourceType


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
