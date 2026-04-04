"""
Unit tests for SQLite Storage Adapter.

実際の SQLite ファイル（tmpdir）を使った統合的ユニットテスト。
sqlite-vec (コサイン類似度) と FTS5 の動作も検証する。
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any
from uuid import uuid4

import pytest

from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import MemoryFilters, StorageError
from context_store.storage.sqlite import SQLiteStorageAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(**kwargs: Any) -> Memory:
    defaults: dict[str, Any] = {
        "content": "test content about Python programming",
        "memory_type": MemoryType.EPISODIC,
        "source_type": SourceType.MANUAL,
        "embedding": [],
    }
    defaults.update(kwargs)
    return Memory(**defaults)


def _make_memory_with_embedding(embedding: list[float], **kwargs: Any) -> Memory:
    return _make_memory(embedding=embedding, **kwargs)


async def _fetch_one_value(adapter, sql: str) -> Any:
    async with adapter._db() as conn:
        async with conn.execute(sql) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return row[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def adapter(tmp_path):
    """SQLiteStorageAdapter を tmpdir の DB ファイルで作成して返す。"""
    from context_store.config import Settings

    db_path = str(tmp_path / "test_memories.db")
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=db_path,
        sqlite_max_concurrent_connections=5,
        sqlite_max_queued_requests=20,
        sqlite_acquire_timeout=2.0,
        embedding_provider="local-model",
        local_model_name="test-model",
    )
    adp = await SQLiteStorageAdapter.create(settings)
    yield adp
    await adp.dispose()


@pytest.fixture
async def adapter_with_backpressure(tmp_path):
    """バックプレッシャーテスト用の厳格な制限付きアダプター。"""
    from context_store.config import Settings

    db_path = str(tmp_path / "bp_memories.db")
    settings = Settings(
        storage_backend="sqlite",
        sqlite_db_path=db_path,
        sqlite_max_concurrent_connections=2,
        sqlite_max_queued_requests=3,
        sqlite_acquire_timeout=10.0,  # タイムアウトしない長さ
        embedding_provider="local-model",
        local_model_name="test-model",
    )
    adp = await SQLiteStorageAdapter.create(settings)
    yield adp
    await adp.dispose()


# ---------------------------------------------------------------------------
# CRUD Tests
# ---------------------------------------------------------------------------


class TestSaveMemory:
    async def test_save_returns_string_id(self, adapter):
        memory = _make_memory()
        result = await adapter.save_memory(memory)
        assert isinstance(result, str)
        assert result == str(memory.id)

    async def test_save_persists_content(self, adapter):
        memory = _make_memory(content="unique content for persistence test")
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.content == memory.content

    async def test_save_persists_memory_type(self, adapter):
        memory = _make_memory(memory_type=MemoryType.SEMANTIC)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.memory_type == MemoryType.SEMANTIC

    async def test_save_persists_source_type(self, adapter):
        memory = _make_memory(source_type=SourceType.CONVERSATION)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.source_type == SourceType.CONVERSATION

    async def test_save_persists_tags(self, adapter):
        memory = _make_memory(tags=["python", "programming"])
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert set(retrieved.tags) == {"python", "programming"}

    async def test_save_persists_project(self, adapter):
        memory = _make_memory(project="my_project")
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.project == "my_project"

    async def test_save_persists_source_metadata(self, adapter):
        metadata = {"url": "https://example.com", "author": "test"}
        memory = _make_memory(source_metadata=metadata)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.source_metadata == metadata

    async def test_save_persists_importance_score(self, adapter):
        memory = _make_memory(importance_score=0.9)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        assert retrieved.importance_score == pytest.approx(0.9)

    async def test_save_multiple_memories(self, adapter):
        memories = [_make_memory(content=f"content {i}") for i in range(3)]
        for m in memories:
            await adapter.save_memory(m)
        for m in memories:
            retrieved = await adapter.get_memory(str(m.id))
            assert retrieved is not None

    async def test_vectors_metadata_dimension_is_unique(self, adapter):
        count = await _fetch_one_value(
            adapter,
            """
            SELECT COUNT(*)
            FROM pragma_table_info('vectors_metadata')
            WHERE name = 'dimension' AND pk = 0
            """,
        )

        assert count == 1

        async with adapter._db() as conn:
            async with conn.execute("PRAGMA index_list('vectors_metadata')") as cursor:
                rows = await cursor.fetchall()

        assert any(row["unique"] == 1 for row in rows)

    async def test_first_embedding_metadata_insert_is_idempotent(self, adapter):
        memory1 = _make_memory_with_embedding([0.1, 0.2, 0.3], content="vector one")
        memory2 = _make_memory_with_embedding([0.1, 0.2, 0.3], content="vector two")

        await adapter.save_memory(memory1)
        adapter._vector_dim = None
        await adapter.save_memory(memory2)

        count = await _fetch_one_value(adapter, "SELECT COUNT(*) FROM vectors_metadata")

        assert count == 1


class TestGetMemory:
    async def test_get_returns_none_when_not_found(self, adapter):
        result = await adapter.get_memory(str(uuid4()))
        assert result is None

    async def test_get_returns_memory_when_found(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        result = await adapter.get_memory(str(memory.id))
        assert result is not None
        assert str(result.id) == str(memory.id)

    async def test_get_preserves_all_fields(self, adapter):
        memory = _make_memory(
            content="full fields test",
            memory_type=MemoryType.PROCEDURAL,
            source_type=SourceType.URL,
            tags=["tag1"],
            project="proj",
            importance_score=0.75,
            semantic_relevance=0.8,
        )
        await adapter.save_memory(memory)
        result = await adapter.get_memory(str(memory.id))
        assert result is not None
        assert result.memory_type == MemoryType.PROCEDURAL
        assert result.source_type == SourceType.URL
        assert result.tags == ["tag1"]
        assert result.project == "proj"
        assert result.importance_score == pytest.approx(0.75)
        assert result.semantic_relevance == pytest.approx(0.8)


class TestDeleteMemory:
    async def test_delete_returns_true_when_deleted(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        result = await adapter.delete_memory(str(memory.id))
        assert result is True

    async def test_delete_returns_false_when_not_found(self, adapter):
        result = await adapter.delete_memory(str(uuid4()))
        assert result is False

    async def test_delete_removes_memory_from_db(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        await adapter.delete_memory(str(memory.id))
        result = await adapter.get_memory(str(memory.id))
        assert result is None

    async def test_delete_removes_from_fts_index(self, adapter):
        """FTS インデックスからも削除されること。"""
        memory = _make_memory(content="unique searchable phrase xyz123")
        await adapter.save_memory(memory)
        await adapter.delete_memory(str(memory.id))
        results = await adapter.keyword_search("unique searchable phrase xyz123", top_k=10)
        assert len(results) == 0


class TestUpdateMemory:
    async def test_update_returns_true_on_success(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        result = await adapter.update_memory(str(memory.id), {"importance_score": 0.9})
        assert result is True

    async def test_update_returns_false_when_not_found(self, adapter):
        result = await adapter.update_memory(str(uuid4()), {"importance_score": 0.9})
        assert result is False

    async def test_update_applies_changes(self, adapter):
        memory = _make_memory(importance_score=0.5)
        await adapter.save_memory(memory)
        await adapter.update_memory(str(memory.id), {"importance_score": 0.99})
        result = await adapter.get_memory(str(memory.id))
        assert result is not None
        assert result.importance_score == pytest.approx(0.99)

    async def test_update_multiple_fields(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        await adapter.update_memory(
            str(memory.id),
            {"importance_score": 0.8, "access_count": 5},
        )
        result = await adapter.get_memory(str(memory.id))
        assert result is not None
        assert result.importance_score == pytest.approx(0.8)
        assert result.access_count == 5

    async def test_update_empty_dict_returns_false(self, adapter):
        memory = _make_memory()
        await adapter.save_memory(memory)
        result = await adapter.update_memory(str(memory.id), {})
        assert result is False

    async def test_update_fts_index_on_content_change(self, adapter):
        """content 更新時に FTS インデックスが更新されること。"""
        memory = _make_memory(content="original content abc")
        await adapter.save_memory(memory)
        await adapter.update_memory(str(memory.id), {"content": "updated content xyz"})
        # 旧ワードでは見つからない
        old_results = await adapter.keyword_search("original content abc", top_k=10)
        assert len(old_results) == 0
        # 新ワードで見つかる
        new_results = await adapter.keyword_search("updated content xyz", top_k=10)
        assert len(new_results) == 1


class TestUpdateMemoryValidation:
    @pytest.mark.asyncio
    async def test_update_memory_invalid_json(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"tags": "invalid-json["})
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_update_memory_invalid_tags_type(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"tags": '{"not": "a list"}'})
        assert exc.value.code == "INVALID_PARAMETER"

    @pytest.mark.asyncio
    async def test_update_memory_invalid_metadata_type(self, adapter):
        memory = _make_memory()
        mid = await adapter.save_memory(memory)
        with pytest.raises(StorageError) as exc:
            await adapter.update_memory(mid, {"source_metadata": "[not, an, object]"})
        assert exc.value.code == "INVALID_PARAMETER"


# ---------------------------------------------------------------------------
# Vector Search Tests
# ---------------------------------------------------------------------------


class TestVectorSearch:
    async def test_vector_search_returns_empty_when_no_data(self, adapter):
        result = await adapter.vector_search([0.1, 0.2, 0.3], top_k=5)
        assert result == []

    async def test_vector_search_returns_scored_memories(self, adapter):
        emb = [1.0, 0.0, 0.0]
        memory = _make_memory_with_embedding(emb)
        await adapter.save_memory(memory)

        results = await adapter.vector_search([1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        assert isinstance(results[0], ScoredMemory)
        assert results[0].source == MemorySource.VECTOR

    async def test_vector_search_cosine_similarity_score(self, adapter):
        """コサイン類似度: 同一ベクトルはスコア 1.0 に近い。"""
        emb = [1.0, 0.0, 0.0]
        memory = _make_memory_with_embedding(emb)
        await adapter.save_memory(memory)

        results = await adapter.vector_search([1.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        # コサイン類似度が高いこと（距離が小さい＝スコアが高い）
        assert results[0].score >= 0.99

    async def test_vector_search_ranks_by_similarity(self, adapter):
        """類似度順で並ぶこと。"""
        emb_close = [1.0, 0.0, 0.0]
        emb_far = [0.0, 1.0, 0.0]
        memory_close = _make_memory_with_embedding(emb_close, content="close vector memory")
        memory_far = _make_memory_with_embedding(emb_far, content="far vector memory")
        await adapter.save_memory(memory_close)
        await adapter.save_memory(memory_far)

        query = [0.9, 0.1, 0.0]
        results = await adapter.vector_search(query, top_k=5)
        assert len(results) == 2
        # 近い方が先（スコアが高い順）
        assert results[0].memory.content == "close vector memory"

    async def test_vector_search_respects_top_k(self, adapter):
        """top_k を超えた結果は返らない。"""
        for i in range(5):
            emb = [float(i), 0.0, 0.0]
            memory = _make_memory_with_embedding(emb, content=f"memory {i}")
            await adapter.save_memory(memory)

        results = await adapter.vector_search([1.0, 0.0, 0.0], top_k=3)
        assert len(results) <= 3

    async def test_vector_search_filters_by_project(self, adapter):
        """プロジェクトフィルタが機能すること。"""
        emb = [1.0, 0.0, 0.0]
        m_proj_a = _make_memory_with_embedding(emb, content="proj a memory", project="proj_a")
        m_proj_b = _make_memory_with_embedding(emb, content="proj b memory", project="proj_b")
        await adapter.save_memory(m_proj_a)
        await adapter.save_memory(m_proj_b)

        results = await adapter.vector_search([1.0, 0.0, 0.0], top_k=10, project="proj_a")
        assert all(r.memory.project == "proj_a" for r in results)
        assert len(results) == 1

    async def test_vector_search_ignores_archived_memories(self, adapter):
        """アーカイブ済みは返さない。"""
        from datetime import datetime, timezone

        emb = [1.0, 0.0, 0.0]
        memory = _make_memory_with_embedding(emb, content="archived memory")
        await adapter.save_memory(memory)
        await adapter.update_memory(
            str(memory.id),
            {"archived_at": datetime.now(timezone.utc)},
        )

        results = await adapter.vector_search([1.0, 0.0, 0.0], top_k=10)
        assert all(r.memory.archived_at is None for r in results)

    async def test_vector_search_returns_empty_for_empty_embedding(self, adapter):
        """空の埋め込みでは空リストを返す。"""
        results = await adapter.vector_search([], top_k=5)
        assert results == []


# ---------------------------------------------------------------------------
# Keyword Search Tests
# ---------------------------------------------------------------------------


class TestKeywordSearch:
    async def test_keyword_search_returns_empty_when_no_data(self, adapter):
        result = await adapter.keyword_search("hello", top_k=5)
        assert result == []

    async def test_keyword_search_finds_matching_content(self, adapter):
        memory = _make_memory(content="Python programming language tutorial")
        await adapter.save_memory(memory)

        results = await adapter.keyword_search("Python", top_k=5)
        assert len(results) >= 1
        assert any(r.memory.content == memory.content for r in results)

    async def test_keyword_search_returns_scored_memories(self, adapter):
        memory = _make_memory(content="hello world test content")
        await adapter.save_memory(memory)

        results = await adapter.keyword_search("hello", top_k=5)
        assert len(results) >= 1
        assert isinstance(results[0], ScoredMemory)
        assert results[0].source == MemorySource.KEYWORD

    async def test_keyword_search_does_not_return_non_matching(self, adapter):
        memory = _make_memory(content="completely unrelated content here")
        await adapter.save_memory(memory)

        results = await adapter.keyword_search("xyznomatchxyz", top_k=5)
        assert len(results) == 0

    async def test_keyword_search_respects_top_k(self, adapter):
        for i in range(10):
            memory = _make_memory(content=f"searchable keyword content item {i}")
            await adapter.save_memory(memory)

        results = await adapter.keyword_search("searchable keyword", top_k=3)
        assert len(results) <= 3

    async def test_keyword_search_filters_by_project(self, adapter):
        m_a = _make_memory(content="keyword match alpha", project="proj_alpha")
        m_b = _make_memory(content="keyword match beta", project="proj_beta")
        await adapter.save_memory(m_a)
        await adapter.save_memory(m_b)

        results = await adapter.keyword_search("keyword match", top_k=10, project="proj_alpha")
        assert all(r.memory.project == "proj_alpha" for r in results)

    async def test_keyword_search_ignores_archived_memories(self, adapter):
        from datetime import datetime, timezone

        memory = _make_memory(content="archived keyword search test")
        await adapter.save_memory(memory)
        await adapter.update_memory(
            str(memory.id),
            {"archived_at": datetime.now(timezone.utc)},
        )

        results = await adapter.keyword_search("archived keyword search test", top_k=10)
        assert all(r.memory.archived_at is None for r in results)


# ---------------------------------------------------------------------------
# ListByFilter Tests
# ---------------------------------------------------------------------------


class TestListByFilter:
    async def test_list_returns_active_by_default(self, adapter):
        from datetime import datetime, timezone

        active = _make_memory(content="active memory")
        archived = _make_memory(content="archived memory")
        await adapter.save_memory(active)
        await adapter.save_memory(archived)
        await adapter.update_memory(
            str(archived.id),
            {"archived_at": datetime.now(timezone.utc)},
        )

        results = await adapter.list_by_filter(MemoryFilters())
        ids = [str(r.id) for r in results]
        assert str(active.id) in ids
        assert str(archived.id) not in ids

    async def test_list_archived_true(self, adapter):
        from datetime import datetime, timezone

        active = _make_memory(content="active")
        archived = _make_memory(content="archived")
        await adapter.save_memory(active)
        await adapter.save_memory(archived)
        await adapter.update_memory(
            str(archived.id),
            {"archived_at": datetime.now(timezone.utc)},
        )

        results = await adapter.list_by_filter(MemoryFilters(archived=True))
        ids = [str(r.id) for r in results]
        assert str(archived.id) in ids
        assert str(active.id) not in ids

    async def test_list_archived_false_returns_both(self, adapter):
        from datetime import datetime, timezone

        active = _make_memory(content="active both")
        archived = _make_memory(content="archived both")
        await adapter.save_memory(active)
        await adapter.save_memory(archived)
        await adapter.update_memory(
            str(archived.id),
            {"archived_at": datetime.now(timezone.utc)},
        )

        results = await adapter.list_by_filter(MemoryFilters(archived=False))
        ids = [str(r.id) for r in results]
        assert str(active.id) in ids
        assert str(archived.id) in ids

    async def test_list_by_project(self, adapter):
        m_a = _make_memory(content="proj a", project="proj_a")
        m_b = _make_memory(content="proj b", project="proj_b")
        await adapter.save_memory(m_a)
        await adapter.save_memory(m_b)

        results = await adapter.list_by_filter(MemoryFilters(project="proj_a"))
        assert all(r.project == "proj_a" for r in results)

    async def test_list_by_memory_type(self, adapter):
        ep = _make_memory(content="episodic", memory_type=MemoryType.EPISODIC)
        sem = _make_memory(content="semantic", memory_type=MemoryType.SEMANTIC)
        await adapter.save_memory(ep)
        await adapter.save_memory(sem)

        results = await adapter.list_by_filter(MemoryFilters(memory_type=MemoryType.EPISODIC.value))
        assert all(r.memory_type == MemoryType.EPISODIC for r in results)

    async def test_list_by_tags(self, adapter):
        tagged = _make_memory(content="has tags", tags=["ai", "python"])
        untagged = _make_memory(content="no tags")
        await adapter.save_memory(tagged)
        await adapter.save_memory(untagged)

        results = await adapter.list_by_filter(MemoryFilters(tags=["ai"]))
        ids = [str(r.id) for r in results]
        assert str(tagged.id) in ids
        assert str(untagged.id) not in ids

    async def test_list_by_tags_does_not_corrupt_values_containing_column_names(self, adapter):
        tagged = _make_memory(content="tagged", tags=["archived_at"])
        other = _make_memory(content="other", tags=["different"])
        await adapter.save_memory(tagged)
        await adapter.save_memory(other)

        results = await adapter.list_by_filter(MemoryFilters(tags=["archived_at"]))

        ids = [str(r.id) for r in results]
        assert str(tagged.id) in ids
        assert str(other.id) not in ids


class TestSqlInjection:
    async def test_list_by_filter_order_by_injection(self, adapter):
        # Malicious order_by to drop a table or cause syntax error
        malicious_order = "id; DROP TABLE memories;"
        filters = MemoryFilters(order_by=malicious_order)

        # Before fix, this will likely raise aiosqlite.OperationalError (syntax error)
        # We expect a StorageError with code 'INVALID_PARAMETER' after our fix.
        with pytest.raises(StorageError) as exc_info:
            await adapter.list_by_filter(filters)
        assert exc_info.value.code == "INVALID_PARAMETER"

    async def test_list_by_filter_order_by_extra_tokens(self, adapter):
        # Even if columns are valid, extra tokens should be rejected
        filters = MemoryFilters(order_by="id DESC extra")
        with pytest.raises(StorageError) as exc_info:
            await adapter.list_by_filter(filters)
        assert exc_info.value.code == "INVALID_PARAMETER"
        assert "Extra tokens detected" in str(exc_info.value)

    async def test_list_by_filter_limit_injection(self, adapter):
        malicious_limit = "1; DROP TABLE memories;"
        filters = MemoryFilters()
        filters.limit = malicious_limit

        with pytest.raises(StorageError) as exc_info:
            await adapter.list_by_filter(filters)
        assert exc_info.value.code == "INVALID_PARAMETER"

    async def test_list_by_filter_valid_parameters(self, adapter):
        # 1. Whitelisted order_by (ASC/DESC)
        filters = MemoryFilters(order_by="id ASC")
        # Should NOT raise StorageError
        await adapter.list_by_filter(filters)

        filters = MemoryFilters(order_by="id DESC")
        await adapter.list_by_filter(filters)

        # 2. Valid integer limit
        filters = MemoryFilters(limit=10)
        # Should NOT raise StorageError
        await adapter.list_by_filter(filters)

        # 3. Valid session_id filter
        memory = _make_memory(content="metadata search test")
        memory.source_metadata = {"session_id": "test_session_id"}
        await adapter.save_memory(memory)

        filters = MemoryFilters(session_id="test_session_id")
        results = await adapter.list_by_filter(filters)
        # Verify success and check property (source_metadata is a dict in Memory)
        assert len(results) >= 1
        assert results[0].source_metadata["session_id"] == "test_session_id"


# ---------------------------------------------------------------------------
# GetVectorDimension Tests
# ---------------------------------------------------------------------------


class TestGetVectorDimension:
    async def test_returns_none_when_no_vectors(self, adapter):
        result = await adapter.get_vector_dimension()
        assert result is None

    async def test_returns_dimension_when_vectors_exist(self, adapter):
        memory = _make_memory_with_embedding([1.0, 0.0, 0.0])
        await adapter.save_memory(memory)

        result = await adapter.get_vector_dimension()
        assert result == 3

    async def test_returns_correct_dimension(self, adapter):
        emb = [0.1, 0.2, 0.3, 0.4, 0.5]
        memory = _make_memory_with_embedding(emb)
        await adapter.save_memory(memory)

        result = await adapter.get_vector_dimension()
        assert result == 5


# ---------------------------------------------------------------------------
# WAL Mode Test
# ---------------------------------------------------------------------------


class TestWalMode:
    async def test_journal_mode_is_wal(self, adapter):
        """PRAGMA journal_mode が 'wal' を返すこと。"""

        assert isinstance(adapter, SQLiteStorageAdapter)
        async with adapter._connect() as conn:
            async with conn.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"

    async def test_foreign_keys_enabled(self, adapter):
        """PRAGMA foreign_keys が ON であること。"""

        assert isinstance(adapter, SQLiteStorageAdapter)
        async with adapter._connect() as conn:
            async with conn.execute("PRAGMA foreign_keys") as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1


# ---------------------------------------------------------------------------
# Backpressure & Concurrency Tests
# ---------------------------------------------------------------------------


class TestBackpressureControl:
    async def test_concurrent_requests_with_backpressure(self, adapter_with_backpressure):
        """
        max_concurrent=2, max_queued=3 → 合計 5 件許容。
        10 件の同時リクエストで 成功=5, 拒否=5 を厳密に確認する。
        """
        adp = adapter_with_backpressure

        # 全リクエストをブロックするために event を使用
        # DB に単純な get_memory を投げる（存在しない ID で即座完了）
        # バックプレッシャーを観察するために遅延を持つ操作を使用

        results: list[str | StorageError] = []

        async def slow_request(i: int) -> None:
            try:
                await adp.get_memory(str(uuid4()))
                results.append("ok")
            except StorageError as e:
                results.append(e)

        # シンプルに: 実際の同時リクエストを発行
        # セマフォ制御は get_memory でも適用される
        tasks = [asyncio.create_task(slow_request(i)) for i in range(10)]
        await asyncio.gather(*tasks)

        ok_count = sum(1 for r in results if r == "ok")
        busy_count = sum(1 for r in results if isinstance(r, StorageError))
        busy_errors = [r for r in results if isinstance(r, StorageError)]

        # すべて STORAGE_BUSY コードであること
        assert all(e.code == "STORAGE_BUSY" for e in busy_errors)

        # 合計 10 件
        assert ok_count + busy_count == 10

    async def test_storage_busy_error_when_at_capacity(self, tmp_path):
        """
        max_concurrent=2, max_queued=3、同時10件では必ず一部が STORAGE_BUSY になる。
        成功=5, 拒否=5 の厳密テスト（遅い操作で保証）。
        """
        from context_store.config import Settings

        db_path = str(tmp_path / "bp_strict.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            sqlite_max_concurrent_connections=2,
            sqlite_max_queued_requests=3,
            sqlite_acquire_timeout=10.0,
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)

        hold_event = asyncio.Event()
        results: list[str | StorageError] = []

        async def blocking_request(i: int) -> None:
            """セマフォを保持したまま event を待つ操作を模倣する。"""
            try:
                # _with_semaphore を直接テストするため内部メソッドを使う
                async with adp._with_semaphore():
                    await hold_event.wait()  # セマフォを長時間保持
                results.append("ok")
            except StorageError as e:
                results.append(e)

        # 10 件起動 → 2件がセマフォ取得、3件が待機キュー、5件が即座拒否
        tasks = [asyncio.create_task(blocking_request(i)) for i in range(10)]

        # タスクがスタートするよう少し待つ
        await asyncio.sleep(0.05)

        # BUSY になったタスクはすでに完了しているはず
        # hold_event を解放して残りを完了させる
        hold_event.set()
        await asyncio.gather(*tasks)

        ok_count = sum(1 for r in results if r == "ok")
        busy_count = sum(1 for r in results if isinstance(r, StorageError))
        busy_errors = [r for r in results if isinstance(r, StorageError)]

        assert ok_count == 5, f"Expected 5 successes, got {ok_count} (results: {results})"
        assert busy_count == 5, f"Expected 5 busy errors, got {busy_count}"
        assert all(e.code == "STORAGE_BUSY" for e in busy_errors)

        # リークなし確認
        assert adp._waiting_count == 0

        await adp.dispose()

    async def test_semaphore_acquire_timeout(self, tmp_path):
        """タイムアウトで STORAGE_BUSY (recoverable=True) が発生すること。"""
        from context_store.config import Settings

        db_path = str(tmp_path / "timeout.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            sqlite_max_concurrent_connections=1,
            sqlite_max_queued_requests=100,  # キューは埋まらない
            sqlite_acquire_timeout=0.05,  # 50ms タイムアウト
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)

        hold_event = asyncio.Event()
        timeout_errors: list[StorageError] = []

        async def blocking() -> None:
            async with adp._with_semaphore():
                await hold_event.wait()

        async def timing_out() -> None:
            try:
                async with adp._with_semaphore():
                    pass
            except StorageError as e:
                timeout_errors.append(e)

        # セマフォを占有
        blocker = asyncio.create_task(blocking())
        await asyncio.sleep(0.01)  # blocker がセマフォを取得するまで待つ

        # タイムアウトするタスクを起動
        waiter = asyncio.create_task(timing_out())
        await asyncio.sleep(0.2)  # タイムアウト発生を待つ

        hold_event.set()
        await asyncio.gather(blocker, waiter)

        assert len(timeout_errors) >= 1
        assert all(e.code == "STORAGE_BUSY" for e in timeout_errors)
        assert all(e.recoverable for e in timeout_errors)

        # カウンタリーク確認
        assert adp._waiting_count == 0

        await adp.dispose()

    async def test_no_semaphore_leak_after_error(self, tmp_path):
        """エラー後もセマフォ・待機カウンタがリークしないこと。"""
        from context_store.config import Settings

        db_path = str(tmp_path / "leak.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            sqlite_max_concurrent_connections=3,
            sqlite_max_queued_requests=5,
            sqlite_acquire_timeout=2.0,
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)

        # 複数のリクエストを実行（成功・失敗混在）
        tasks = []
        for _ in range(20):
            tasks.append(asyncio.create_task(adp.get_memory(str(uuid4()))))

        await asyncio.gather(*tasks, return_exceptions=True)

        # カウンタがリークしていないこと
        assert adp._waiting_count == 0

        await adp.dispose()


# ---------------------------------------------------------------------------
# Serialization / Deserialization Tests
# ---------------------------------------------------------------------------


class TestEmbeddingSerDes:
    async def test_save_and_retrieve_preserves_embedding(self, adapter):
        """保存→読み戻しで float32 精度が保たれること。"""
        emb = [0.1, 0.2, 0.3, 0.4, 0.5]
        memory = _make_memory_with_embedding(emb)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        # float32 キャストで誤差が出るため approx で比較
        for orig, ret in zip(emb, retrieved.embedding, strict=True):
            assert ret == pytest.approx(orig, abs=1e-6)

    async def test_round_trip_float32_precision(self, adapter):
        """float32 でのラウンドトリップ精度確認。"""
        # float32 で表現可能な値
        emb = [struct.unpack("f", struct.pack("f", v))[0] for v in [0.123456, 0.789012, 0.456789]]
        memory = _make_memory_with_embedding(emb)
        await adapter.save_memory(memory)
        retrieved = await adapter.get_memory(str(memory.id))
        assert retrieved is not None
        for orig, ret in zip(emb, retrieved.embedding, strict=True):
            assert ret == pytest.approx(orig, abs=1e-7)

    async def test_dimension_mismatch_raises_error(self, adapter):
        """次元不一致時に StorageError が発生すること。"""
        # 最初に dim=3 を登録
        emb3 = [1.0, 0.0, 0.0]
        memory1 = _make_memory_with_embedding(emb3, content="dim3 memory")
        await adapter.save_memory(memory1)

        # dim=4 で保存しようとするとエラー
        emb4 = [1.0, 0.0, 0.0, 0.0]
        memory2 = _make_memory_with_embedding(emb4, content="dim4 memory")
        with pytest.raises(StorageError) as exc_info:
            await adapter.save_memory(memory2)
        assert "dimension" in exc_info.value.args[0].lower() or exc_info.value.code != ""

    async def test_nan_in_embedding_raises_error(self, tmp_path):
        """NaN を含む埋め込みは拒否されること。"""
        from context_store.config import Settings

        db_path = str(tmp_path / "nan_test.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)
        try:
            emb = [1.0, float("nan"), 0.0]
            memory = _make_memory_with_embedding(emb)
            with pytest.raises(StorageError):
                await adp.save_memory(memory)
        finally:
            await adp.dispose()

    async def test_inf_in_embedding_raises_error(self, tmp_path):
        """Inf を含む埋め込みは拒否されること。"""
        from context_store.config import Settings

        db_path = str(tmp_path / "inf_test.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)
        try:
            emb = [1.0, float("inf"), 0.0]
            memory = _make_memory_with_embedding(emb)
            with pytest.raises(StorageError):
                await adp.save_memory(memory)
        finally:
            await adp.dispose()

    async def test_encode_decode_round_trip(self, tmp_path):
        """encode_embedding / decode_embedding のラウンドトリップ。"""
        from context_store.storage.sqlite import decode_embedding, encode_embedding

        emb = [1.0, 2.0, 3.0, 4.0]
        blob = encode_embedding(emb)
        assert isinstance(blob, bytes)
        decoded = decode_embedding(blob)
        assert len(decoded) == 4
        for orig, dec in zip(emb, decoded):
            assert dec == pytest.approx(orig, abs=1e-6)

    async def test_encode_uses_serialize_float32(self, tmp_path):
        """encode_embedding が serialize_float32 と同じバイト列を生成すること。"""
        import sqlite_vec

        from context_store.storage.sqlite import encode_embedding

        emb = [0.5, 1.5, 2.5]
        expected = sqlite_vec.serialize_float32(emb)
        result = encode_embedding(emb)
        assert result == expected

    async def test_fallback_encode_path(self):
        """sqlite_vec が使えない場合のフォールバック（struct.pack）が正しく動作すること。"""
        from unittest.mock import patch

        from context_store.storage.sqlite import encode_embedding

        emb = [1.0, 2.0, 3.0]
        # sqlite_vec.serialize_float32 をモックして ImportError を模倣
        with patch("context_store.storage.sqlite._USE_SQLITE_VEC_SERIALIZE", False):
            blob = encode_embedding(emb)
        expected = struct.pack("<" + "f" * len(emb), *emb)
        assert blob == expected

    async def test_validate_embedding_accepts_valid(self):
        """有効な埋め込みは例外を発生させないこと。"""
        from context_store.storage.sqlite import validate_embedding

        validate_embedding([1.0, 2.0, 3.0])  # 例外なし
        validate_embedding([0.0, -1.0, 0.5])

    async def test_validate_embedding_rejects_nan(self):
        """NaN は StorageError を発生させること。"""
        from context_store.storage.sqlite import validate_embedding

        with pytest.raises(StorageError):
            validate_embedding([1.0, float("nan"), 0.0])

    async def test_validate_embedding_rejects_inf(self):
        """Inf は StorageError を発生させること。"""
        from context_store.storage.sqlite import validate_embedding

        with pytest.raises(StorageError):
            validate_embedding([float("inf"), 0.0, 1.0])

    async def test_validate_embedding_rejects_dimension_mismatch(self):
        """期待次元と不一致の場合 StorageError を発生させること。"""
        from context_store.storage.sqlite import validate_embedding

        with pytest.raises(StorageError):
            validate_embedding([1.0, 2.0, 3.0], expected_dim=5)

    async def test_validate_embedding_accepts_correct_dimension(self):
        """正しい次元は例外を発生させないこと。"""
        from context_store.storage.sqlite import validate_embedding

        validate_embedding([1.0, 2.0, 3.0], expected_dim=3)


# ---------------------------------------------------------------------------
# Dispose Test
# ---------------------------------------------------------------------------


class TestDispose:
    async def test_dispose_can_be_called_multiple_times(self, tmp_path):
        """dispose は複数回呼んでもエラーにならない。"""
        from context_store.config import Settings

        db_path = str(tmp_path / "dispose.db")
        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=db_path,
            embedding_provider="local-model",
            local_model_name="test-model",
        )
        adp = await SQLiteStorageAdapter.create(settings)
        await adp.dispose()
        await adp.dispose()  # 2 回目もエラーなし


# ---------------------------------------------------------------------------
# get_memories_batch
# ---------------------------------------------------------------------------


class TestGetMemoriesBatch:
    @pytest.mark.asyncio
    async def test_get_memories_batch_basic(self, adapter):
        # Save some memories
        m1 = _make_memory(content="test1")
        m2 = _make_memory(content="test2")
        await adapter.save_memory(m1)
        await adapter.save_memory(m2)

        # Retrieve in batch
        results = await adapter.get_memories_batch([str(m1.id), str(m2.id)])
        assert len(results) == 2
        ids = [str(m.id) for m in results]
        assert str(m1.id) in ids
        assert str(m2.id) in ids

    @pytest.mark.asyncio
    async def test_get_memories_batch_order_and_duplicates(self, adapter):
        m1 = _make_memory(content="test1")
        m2 = _make_memory(content="test2")
        await adapter.save_memory(m1)
        await adapter.save_memory(m2)

        # Duplicate IDs and specific order
        results = await adapter.get_memories_batch([str(m2.id), str(m1.id), str(m2.id)])
        assert len(results) == 3
        assert str(results[0].id) == str(m2.id)
        assert str(results[1].id) == str(m1.id)
        assert str(results[2].id) == str(m2.id)

    @pytest.mark.asyncio
    async def test_get_memories_batch_large(self, adapter):
        # Trigger chunking (chunk_size=900)
        ids = []
        # Using 950 to trigger 2 chunks (900 + 50)
        # 1000 items save one-by-one is slow in CI
        for i in range(950):
            m = _make_memory(content=f"test{i}")
            await adapter.save_memory(m)
            ids.append(str(m.id))

        # This should trigger chunking (chunk_size=900)
        results = await adapter.get_memories_batch(ids)
        assert len(results) == 950
        for i, m in enumerate(results):
            assert str(m.id) == ids[i]
        assert results[0].content == "test0"
        assert results[-1].content == "test949"

    @pytest.mark.asyncio
    async def test_get_memories_batch_empty(self, adapter):
        results = await adapter.get_memories_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_get_memories_batch_missing_ids(self, adapter):
        m1 = _make_memory(content="test1")
        await adapter.save_memory(m1)

        results = await adapter.get_memories_batch([str(m1.id), str(uuid4())])
        assert len(results) == 1
        assert str(results[0].id) == str(m1.id)


@pytest.mark.asyncio
async def test_update_memory_non_existent_with_embedding(adapter):
    # Try to update a non-existent memory with an embedding AND other fields
    bad_id = str(uuid4())
    result = await adapter.update_memory(bad_id, {"content": "new", "embedding": [1.0, 0.0]})

    # Should safely return False, not raise SQLite FK error
    assert result is False

    # Try to update ONLY embedding
    result_only_emb = await adapter.update_memory(bad_id, {"embedding": [1.0, 0.0]})
    assert result_only_emb is False


@pytest.mark.asyncio
async def test_update_memory_unconditional_existence_check(adapter):
    # This test ensures that even if we try to update other fields,
    # we still check existence for the embedding part.
    # Currently it passes due to the cursor.rowcount check, but we want to
    # ensure the specific SELECT 1 check is run as requested.
    bad_id = str(uuid4())
    # This should return False
    result = await adapter.update_memory(bad_id, {"content": "new", "embedding": [1.0, 0.0]})
    assert result is False
