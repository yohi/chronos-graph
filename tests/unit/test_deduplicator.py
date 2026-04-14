"""Task 4.4: Deduplicator のユニットテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from context_store.ingestion.deduplicator import (
    DeduplicationAction,
    DeduplicationResult,
    Deduplicator,
)
from context_store.models.memory import Memory, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import StorageAdapter


def _make_memory(content: str = "test", **kwargs: object) -> Memory:
    """テスト用 Memory を作成する。"""
    defaults: dict[str, object] = {
        "content": content,
        "memory_type": MemoryType.EPISODIC,
        "source_type": SourceType.MANUAL,
        "embedding": [0.1] * 4,
        "importance_score": 0.5,
    }
    defaults.update(kwargs)
    return Memory(**defaults)  # type: ignore[arg-type]


def _make_scored_memory(memory: Memory, score: float) -> ScoredMemory:
    return ScoredMemory(memory=memory, score=score)


def _make_storage_adapter(search_results: list[ScoredMemory]) -> StorageAdapter:
    """モックの StorageAdapter を作成する。"""
    adapter = MagicMock(spec=StorageAdapter)
    adapter.vector_search = AsyncMock(return_value=search_results)  # type: ignore[assignment]
    adapter.update_memory = AsyncMock(return_value=True)  # type: ignore[assignment]
    adapter.save_memory = AsyncMock(return_value=str(uuid4()))  # type: ignore[assignment]
    return adapter


# ===========================================================================
# 類似度 >= 0.90: Append-only 置換テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_deduplicator_high_similarity_replace() -> None:
    """類似度 >= 0.90 で Append-only 置換が選択される。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.95)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("新しい記憶（ほぼ同じ）")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.REPLACE
    assert result.existing_memory is not None
    assert result.existing_memory.id == existing.id


@pytest.mark.asyncio
async def test_deduplicator_high_similarity_archives_existing() -> None:
    """類似度 >= 0.90 の場合、既存記憶を Archived に遷移する。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.92)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("新しい記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.REPLACE

    # update_memory が archived_at 付きで呼ばれること
    adapter.update_memory.assert_called_once()
    call_args = adapter.update_memory.call_args
    updates = call_args[0][1] if call_args[0] else call_args[1].get("updates", {})
    assert "archived_at" in updates


@pytest.mark.asyncio
async def test_deduplicator_high_similarity_exact_boundary() -> None:
    """類似度ちょうど 0.90 でも Append-only 置換が選択される。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.90)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("新しい記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.REPLACE


# ===========================================================================
# 0.85 <= 類似度 < 0.90: 統合候補マークテスト
# ===========================================================================


@pytest.mark.asyncio
async def test_deduplicator_medium_similarity_merge_candidate() -> None:
    """0.85 <= 類似度 < 0.90 で統合候補としてマークされる。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.87)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("類似した記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.MERGE_CANDIDATE
    assert result.existing_memory is not None


@pytest.mark.asyncio
async def test_deduplicator_medium_similarity_lower_boundary() -> None:
    """類似度ちょうど 0.85 で統合候補になる。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.85)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("類似した記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.MERGE_CANDIDATE


@pytest.mark.asyncio
async def test_deduplicator_medium_similarity_upper_boundary() -> None:
    """類似度 0.89 は統合候補（0.90 未満）。"""
    existing = _make_memory("既存の記憶")
    search_results = [_make_scored_memory(existing, 0.89)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("類似した記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.MERGE_CANDIDATE


# ===========================================================================
# 類似度 < 0.85: 新規挿入テスト
# ===========================================================================


@pytest.mark.asyncio
async def test_deduplicator_low_similarity_new_insert() -> None:
    """類似度 < 0.85 で新規挿入が選択される。"""
    existing = _make_memory("全く別の記憶")
    search_results = [_make_scored_memory(existing, 0.70)]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("新しい記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.INSERT
    assert result.existing_memory is None


@pytest.mark.asyncio
async def test_deduplicator_no_existing_memories() -> None:
    """既存記憶がない場合は新規挿入。"""
    adapter = _make_storage_adapter([])
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("全く新しい記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.INSERT
    assert result.existing_memory is None


@pytest.mark.asyncio
async def test_deduplicator_uses_top5_search() -> None:
    """vector_search は top_k=5 で呼ばれる。"""
    adapter = _make_storage_adapter([])
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("テスト")
    await deduplicator.deduplicate(new_memory)

    adapter.vector_search.assert_called_once()
    call_kwargs = adapter.vector_search.call_args
    # top_k=5 が指定されている
    top_k = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("top_k", None)
    assert top_k == 5


@pytest.mark.asyncio
async def test_deduplicator_uses_highest_similarity() -> None:
    """複数の検索結果がある場合、最高類似度で判定する。"""
    existing_low = _make_memory("低類似度")
    existing_high = _make_memory("高類似度")
    # 最高類似度が 0.92 → REPLACE
    search_results = [
        _make_scored_memory(existing_high, 0.92),
        _make_scored_memory(existing_low, 0.60),
    ]

    adapter = _make_storage_adapter(search_results)
    deduplicator = Deduplicator(storage=adapter)

    new_memory = _make_memory("新しい記憶")
    result = await deduplicator.deduplicate(new_memory)

    assert result.action == DeduplicationAction.REPLACE
    assert result.existing_memory is not None
    assert result.existing_memory.id == existing_high.id


# ===========================================================================
# DeduplicationResult テスト
# ===========================================================================


def test_deduplication_result_insert() -> None:
    """INSERT アクションの DeduplicationResult を作成できる。"""
    result = DeduplicationResult(action=DeduplicationAction.INSERT, existing_memory=None)
    assert result.action == DeduplicationAction.INSERT
    assert result.existing_memory is None


def test_deduplication_result_replace() -> None:
    """REPLACE アクションの DeduplicationResult を作成できる。"""
    memory = _make_memory("test")
    result = DeduplicationResult(action=DeduplicationAction.REPLACE, existing_memory=memory)
    assert result.action == DeduplicationAction.REPLACE
    assert result.existing_memory is memory
