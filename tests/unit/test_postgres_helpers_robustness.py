from datetime import datetime, timezone

from context_store.storage.postgres_helpers import _parse_embedding, _record_to_memory


def test_parse_embedding_robustness():
    # Valid cases
    assert _parse_embedding(None) == []
    assert _parse_embedding([1.0, 2.0]) == [1.0, 2.0]
    assert _parse_embedding("[1.0, 2.0]") == [1.0, 2.0]

    # Malformed cases (should return [] instead of crashing)
    assert _parse_embedding("not a vector") == []
    assert _parse_embedding("[1.0, invalid]") == []
    assert _parse_embedding(["1.0", "invalid"]) == []
    assert _parse_embedding(object()) == []


def test_record_to_memory_robustness():
    now = datetime.now(timezone.utc)
    record = {
        "id": "550e8400-e29b-41d4-a716-446655440000",  # Valid UUID
        "content": "test content",
        "memory_type": "episodic",
        "source_type": "conversation",
        "source_metadata": '{"key": "value"}',
        "embedding": "[0.1, 0.2]",
        "last_accessed_at": now,
        "created_at": now,
        "updated_at": now,
    }

    # Valid case
    memory = _record_to_memory(record)
    assert memory.source_metadata == {"key": "value"}

    # Malformed JSON in source_metadata (should fallback to {})
    malformed_record = record.copy()
    malformed_record["source_metadata"] = '{"key": "value"'  # Missing closing brace
    memory = _record_to_memory(malformed_record)
    assert memory.source_metadata == {}

    # Malformed embedding (handled by _parse_embedding)
    malformed_record = record.copy()
    malformed_record["embedding"] = "invalid"
    memory = _record_to_memory(malformed_record)
    assert memory.embedding == []
