# MCP Memory Timeout Reduction (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce p95 latency and timeout frequency of MCP memory operations (`memory_save`, `memory_search`, `memory_delete`, `session_flush`) when the storage backend is a remote DB (Supabase Data API). Eliminate the six biggest per-call costs identified in the 2026-05-26 bottleneck audit: payload bloat from `SELECT *` on the `embedding` column, N+1 access-count RPCs after every search, per-call thread-pool churn in the local embedding provider, per-chunk synchronous embedding during ingestion, missing client-level request timeout, and duplicated vector-dimension probes at startup.

**Architecture:**
- Add a new Supabase RPC `vector_search_brief` that returns the same rows as `vector_search` but without the 768-dim `embedding` column; the adapter calls the brief variant from `SupabaseStorageAdapter.vector_search`. Slim `select(...)` column lists are introduced in `keyword_search`, `get_memory`, `get_memories_batch`, and `list_by_filter` so the embedding column is never fetched on the retrieval path.
- Add a new bulk RPC `increment_memory_access_counts(p_memory_ids uuid[])`, add the method to the `StorageAdapter` protocol, and make `PostProcessor.process` issue a single bulk update instead of N parallel calls. Postgres/SQLite adapters get equivalent batch implementations using `= ANY($1)` / `IN (?, ?, ?, ...)`.
- Replace the per-call `ThreadPoolExecutor(max_workers=1)` in `LocalModelEmbeddingProvider.embed_batch` with a single executor created in `__init__`, with a `start()` method that preloads the model so first-call latency does not block the MCP handshake. `close()` shuts the executor down.
- Refactor `IngestionPipeline.ingest` to (a) collect all chunks across all `RawContent`s, (b) embed them in a single `embed_batch` call, and (c) feed the precomputed embeddings into `_process_chunk_core`. Order-dependent per-chunk processing remains sequential; **parallelization is intentionally deferred to Phase 2**.
- Add a `supabase_request_timeout_seconds` setting and pass it through `AsyncClientOptions(postgrest_client_timeout=...)` when creating the Supabase client.
- Cache the result of `SupabaseStorageAdapter.get_vector_dimension` so that the Orchestrator's `_check_vector_dimension` does not trigger a second HTTPS round trip on startup.

**Out of scope (deferred to a later plan):**
- Tenacity retry tuning for OpenAI/LiteLLM embedding providers (B-2)
- MCP gateway `UpstreamClient.call_tool` timeout wrapper (D-1)
- Universal evaluator parallelization (D-2)
- Approval timeout tuning (D-3)
- Substring-ILIKE keyword search rework (C-3)
- `IngestionPipeline._process_chunk` parallel `asyncio.gather` (A-3 part 2)

**Tech Stack:** Python 3.12, asyncio, supabase-py 2.x (`AsyncClientOptions`), postgrest-py, pytest, pytest-asyncio, sentence-transformers (local embedding), pgvector (HNSW)

---

## File Structure

**New files:**
- `supabase/migrations/20260526000001_vector_search_brief.sql` — Adds `vector_search_brief` RPC that returns search rows without the `embedding` column.
- `supabase/migrations/20260526000002_increment_memory_access_counts.sql` — Adds bulk access-count update RPC.

**Modified files:**
- `src/context_store/config.py` — Add `supabase_request_timeout_seconds` setting.
- `src/context_store/storage/protocols.py` — Add `increment_memory_access_counts(memory_ids: list[str]) -> int` to the `StorageAdapter` protocol.
- `src/context_store/storage/supabase.py` — Apply client timeout, cache dimension, switch `vector_search` to brief RPC, slim `select(...)` columns, implement bulk access-count RPC.
- `src/context_store/storage/postgres.py` — Implement `increment_memory_access_counts` using `WHERE id = ANY($1)`.
- `src/context_store/storage/sqlite.py` — Implement `increment_memory_access_counts` using parameterized `IN`.
- `src/context_store/storage/factory.py` — Add the new method to `ReadOnlyNoOpStorageAdapter`.
- `src/context_store/storage/inmemory.py` — If an in-memory storage stub is referenced by tests, add the method there.
- `src/context_store/retrieval/post_processor.py` — Replace per-result `gather(...)` with a single bulk call.
- `src/context_store/embedding/local_model.py` — Shared executor, `start()` to preload, `close()` to shutdown.
- `src/context_store/ingestion/pipeline.py` — Pre-batch embeddings before per-chunk processing.
- `src/context_store/orchestrator.py` — Skip the second `get_vector_dimension` round trip; pass dimension hint via cached adapter state.

**Test files (modified or created):**
- `tests/unit/storage/test_supabase_adapter.py` — Existing file; add new tests for timeout option, cached dimension, brief vector_search, slim selects, bulk increment.
- `tests/unit/test_postgres_storage.py` — Add bulk increment test (existing file at tests/unit/).
- `tests/unit/test_sqlite_storage.py` — Add bulk increment test (existing file at tests/unit/).
- `tests/unit/test_post_processor.py` — New file: assert PostProcessor issues exactly one bulk update call.
- `tests/unit/test_embedding_local.py` — Add tests for shared executor + `start()`/`close()` lifecycle.
- `tests/unit/test_ingestion_pipeline.py` — Add assertion that `embed_batch` is called exactly once per `ingest()`.
- `tests/unit/storage/test_config_supabase.py` — Add tests for new setting.

---

## Task 1: Add `supabase_request_timeout_seconds` setting and wire it into the client

**Files:**
- Modify: `src/context_store/config.py`
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_config_supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [x] **Step 1: Add a failing test for the new setting default**

Append to `tests/unit/storage/test_config_supabase.py`:

```python
def test_supabase_request_timeout_default(monkeypatch):
    """Default request timeout should be 10.0 seconds."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-role-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("ENV_FILE", "/dev/null")

    from context_store.config import get_settings

    settings = get_settings()
    assert settings.supabase_request_timeout_seconds == 10.0


def test_supabase_request_timeout_env_override(monkeypatch):
    """SUPABASE_REQUEST_TIMEOUT_SECONDS should override the default."""
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-role-key")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "768")
    monkeypatch.setenv("SUPABASE_REQUEST_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("ENV_FILE", "/dev/null")

    from context_store.config import get_settings

    settings = get_settings()
    assert settings.supabase_request_timeout_seconds == 30.0
```

- [x] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/storage/test_config_supabase.py::test_supabase_request_timeout_default tests/unit/storage/test_config_supabase.py::test_supabase_request_timeout_env_override -v`
Expected: FAIL with `AttributeError` on `supabase_request_timeout_seconds`.

- [x] **Step 3: Add the setting**

In `src/context_store/config.py`, add inside `class Settings` (right after the existing `supabase_key` field around line 99-103):

```python
    # --- Supabase request timeout (postgrest_client_timeout) ---
    supabase_request_timeout_seconds: float = Field(
        default=10.0,
        gt=0.0,
        description="Per-request timeout (seconds) for Supabase Data API calls.",
    )
```

- [x] **Step 4: Re-run the setting tests**

Run: `uv run pytest tests/unit/storage/test_config_supabase.py -v`
Expected: PASS.

- [x] **Step 5: Add a failing test that the adapter passes options through**

Append to `tests/unit/storage/test_supabase_adapter.py`:

```python
@pytest.mark.asyncio
async def test_create_passes_request_timeout_to_client(monkeypatch):
    """SupabaseStorageAdapter.create should pass postgrest_client_timeout."""
    captured = {}

    async def fake_create_async_client(url, key, options=None):
        captured["url"] = url
        captured["key"] = key
        captured["options"] = options
        client = make_mock_client()
        # The factory's internal dimension probe must succeed:
        vec_768 = "[" + ",".join(["0.1"] * 768) + "]"
        chain = (
            client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
        )
        chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_768}]))
        return client

    monkeypatch.setattr(
        "context_store.storage.supabase.create_async_client",
        fake_create_async_client,
    )

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://example.supabase.co",
        supabase_key="srk",
        embedding_dimension=768,
        supabase_request_timeout_seconds=12.5,
        _env_file=None,
    )

    adapter = await SupabaseStorageAdapter.create(settings)
    await adapter.dispose()

    assert captured["options"] is not None
    assert captured["options"].postgrest_client_timeout == 12.5
```

- [x] **Step 6: Run the adapter test and confirm it fails**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py::test_create_passes_request_timeout_to_client -v`
Expected: FAIL — `captured["options"]` is `None` because the adapter does not pass options.

- [x] **Step 7: Update the adapter to construct and pass `AsyncClientOptions`**

In `src/context_store/storage/supabase.py`, change the `try` block at the top to import `AsyncClientOptions`:

```python
try:  # noqa: I001
    from postgrest.exceptions import (  # type: ignore[import-not-found]
        APIError as PostgrestAPIError,  # type: ignore[import-not-found]  # noqa: F401
    )

    from supabase import (  # type: ignore[attr-defined]  # noqa: F401
        AsyncClient,
        AsyncClientOptions,
        create_async_client,
    )

    _supabase_available = True
except ImportError:
    AsyncClient = Any  # type: ignore[misc,assignment]
    AsyncClientOptions = Any  # type: ignore[misc,assignment]
    PostgrestAPIError = Exception  # type: ignore[misc,assignment]
    _supabase_available = False
```

Then in `SupabaseStorageAdapter.create` (lines 69-95), change the `create_async_client` call:

```python
        client = await create_async_client(
            settings.supabase_url,
            settings.supabase_key.get_secret_value(),
            options=AsyncClientOptions(
                postgrest_client_timeout=settings.supabase_request_timeout_seconds,
            ),
        )
```

- [x] **Step 8: Re-run the adapter test**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py::test_create_passes_request_timeout_to_client -v`
Expected: PASS.

- [x] **Step 9: Run the full Supabase adapter test module to catch regressions**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -v`
Expected: All PASS (existing tests continue to work because the new option is additive).

- [x] **Step 10: Commit**

```bash
git add src/context_store/config.py src/context_store/storage/supabase.py \
        tests/unit/storage/test_config_supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): add supabase_request_timeout_seconds and wire through AsyncClientOptions"
```

---

## Task 2: Cache `SupabaseStorageAdapter.get_vector_dimension` to remove the double startup probe

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [x] **Step 1: Add a failing test that asserts the second call does not hit the wire**

Append to `tests/unit/storage/test_supabase_adapter.py`:

```python
@pytest.mark.asyncio
async def test_get_vector_dimension_is_cached_after_first_call():
    """Subsequent get_vector_dimension calls must not issue another HTTP request."""
    client = make_mock_client()
    vec_768 = "[" + ",".join(["0.1"] * 768) + "]"
    chain = (
        client.table.return_value.select.return_value.not_.is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_768}]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() == 768
    # Reset the mock so any further call is observable.
    chain.execute.reset_mock()
    client.rpc.reset_mock()

    assert await adapter.get_vector_dimension() == 768
    chain.execute.assert_not_called()
    client.rpc.assert_not_called()
```

- [x] **Step 2: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py::test_get_vector_dimension_is_cached_after_first_call -v`
Expected: FAIL — `chain.execute` is called a second time.

- [x] **Step 3: Add a `_cached_dimension` field and short-circuit logic**

In `src/context_store/storage/supabase.py`, update `__init__` (around line 66) and `get_vector_dimension` (line 97):

```python
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client
        self._cached_dimension: int | None = None

    async def get_vector_dimension(self) -> int | None:
        if self._cached_dimension is not None:
            return self._cached_dimension

        chain = (
            self._client.table("memories")
            .select("embedding")
            .not_.is_("embedding", "null")
            .limit(1)
        )
        response = await chain.execute()
        rows = response.data or []
        if rows:
            embedding = _parse_embedding(rows[0].get("embedding"))
            if embedding:
                self._cached_dimension = len(embedding)
                return self._cached_dimension
        # Empty table: query schema dimension via RPC
        try:
            rpc_response = await self._client.rpc("get_embedding_dimension", {}).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        data = rpc_response.data
        if isinstance(data, list) and data:
            dim = data[0]
        elif isinstance(data, int):
            dim = data
        else:
            dim = None
        if isinstance(dim, int) and dim > 0:
            self._cached_dimension = dim
            return self._cached_dimension
        raise StorageError(
            "Could not determine memories.embedding dimension from schema. "
            "Ensure pgvector extension is installed and the memories table exists.",
            code="INVALID_STATE",
            recoverable=False,
        )
```

- [x] **Step 4: Re-run the test**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py::test_get_vector_dimension_is_cached_after_first_call -v`
Expected: PASS.

- [x] **Step 5: Run the full Supabase adapter and orchestrator tests to verify no regressions**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py tests/unit/test_orchestrator.py -v`
Expected: All PASS. (The existing `Orchestrator._check_vector_dimension` continues to call `get_vector_dimension`, but the cached value short-circuits the second round trip.)

- [x] **Step 6: Commit**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "perf(storage): cache Supabase vector dimension to avoid duplicate startup probe"
```

---

## Task 3: Add `vector_search_brief` RPC and switch the Supabase adapter to it

**Files:**
- Create: `supabase/migrations/20260526000001_vector_search_brief.sql`
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [x] **Step 1: Create the new migration**

Create `supabase/migrations/20260526000001_vector_search_brief.sql` with:

```sql
-- ============================================================
-- vector_search_brief: same as vector_search but omits the
-- embedding column from the return row. Reduces per-row payload
-- by ~10KB (768 floats × JSON encoding overhead) for clients
-- that only need the score + memory metadata for display.
-- The original vector_search is kept for backward compatibility.
-- ============================================================
CREATE OR REPLACE FUNCTION vector_search_brief(
    query_embedding vector(768),
    match_count     integer,
    p_project       text DEFAULT NULL
)
RETURNS TABLE (
    id                 uuid,
    content            text,
    memory_type        varchar,
    source_type        varchar,
    source_metadata    jsonb,
    semantic_relevance float,
    importance_score   float,
    access_count       integer,
    last_accessed_at   timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    archived_at        timestamptz,
    tags               text[],
    project            text,
    content_hash       text,
    score              float
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT
        m.id, m.content, m.memory_type, m.source_type, m.source_metadata,
        m.semantic_relevance, m.importance_score, m.access_count,
        m.last_accessed_at, m.created_at, m.updated_at, m.archived_at,
        m.tags, m.project, m.content_hash,
        (1 - (m.embedding <=> query_embedding))::float AS score
    FROM memories m
    WHERE m.archived_at IS NULL
      AND m.embedding IS NOT NULL
      AND (p_project IS NULL OR m.project = p_project)
    ORDER BY m.embedding <=> query_embedding
    LIMIT COALESCE(GREATEST(match_count, 0), 0);
$$;

GRANT EXECUTE ON FUNCTION vector_search_brief(vector, integer, text) TO service_role;
```

- [x] **Step 2: Add a failing test for the new RPC name**

Append to `tests/unit/storage/test_supabase_adapter.py`:

```python
@pytest.mark.asyncio
async def test_vector_search_uses_brief_rpc_and_returns_empty_embedding():
    """vector_search should call vector_search_brief and return empty embeddings."""
    client = make_mock_client()
    rpc_chain = client.rpc.return_value
    rpc_chain.execute = AsyncMock(
        return_value=make_mock_response(
            data=[
                {
                    "id": "550e8400-e29b-41d4-a716-446655440001",
                    "content": "alpha",
                    "memory_type": "episodic",
                    "source_type": "manual",
                    "source_metadata": {},
                    "semantic_relevance": 0.5,
                    "importance_score": 0.5,
                    "access_count": 0,
                    "last_accessed_at": None,
                    "created_at": "2026-05-26T00:00:00+00:00",
                    "updated_at": "2026-05-26T00:00:00+00:00",
                    "archived_at": None,
                    "tags": [],
                    "project": "p1",
                    "content_hash": "h",
                    "score": 0.9,
                }
            ]
        )
    )

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.vector_search([0.1] * 768, top_k=5, project="p1")

    assert len(results) == 1
    assert results[0].memory.embedding == []  # brief RPC returns no embedding
    call_args = client.rpc.call_args
    assert call_args[0][0] == "vector_search_brief"
```

- [x] **Step 3: Run the test and confirm it fails**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py::test_vector_search_uses_brief_rpc_and_returns_empty_embedding -v`
Expected: FAIL — adapter still calls `vector_search`.

- [x] **Step 4: Update the adapter to call the brief RPC**

In `src/context_store/storage/supabase.py`, change `vector_search` (line 280):

```python
        try:
            response = await self._client.rpc("vector_search_brief", params).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
```

- [x] **Step 5: Update the existing `test_vector_search_calls_rpc` test**

In `tests/unit/storage/test_supabase_adapter.py`, find `test_vector_search_calls_rpc` (around line 472). Update the row builder to drop the `"embedding"` key (the brief RPC does not return it) and change the assertion:

```python
    assert call_args[0][0] == "vector_search_brief"
```

(Leave the `query_embedding` parameter assertion unchanged.)

Also update the row dict in that test to remove `"embedding": embedding,` and assert `results[0].memory.embedding == []`.

- [x] **Step 6: Re-run the adapter tests**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -v`
Expected: All PASS.

- [x] **Step 6.5: Add a SQL-level regression test for the new migration**

The existing `tests/unit/storage/test_supabase_migrations.py` pins the structure of migrations via `re.search` (see e.g. `test_vector_search_rpc_returns_embedding_column` which fixes the existing `vector_search` schema). Add a sibling test so the new RPC's brief contract cannot regress silently.

Append to `tests/unit/storage/test_supabase_migrations.py`:

```python
def test_vector_search_brief_rpc_omits_embedding_column() -> None:
    sql = Path("supabase/migrations/20260526000001_vector_search_brief.sql").read_text()

    assert "CREATE OR REPLACE FUNCTION vector_search_brief(" in sql

    match = re.search(r"RETURNS TABLE\s*\((?P<columns>.*?)\)\s*LANGUAGE", sql, re.S)
    assert match is not None
    returns_table = match.group("columns")
    function_body = sql.split("AS $$", 1)[1].split("$$;", 1)[0]

    # The brief RPC must NOT return the embedding column in its result rows.
    assert re.search(r"\bembedding\s+vector\b", returns_table) is None
    # Score must still be derived from cosine distance against the embedding.
    assert "m.embedding <=>" in function_body
    # Service role grant must be present.
    assert (
        re.search(
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+vector_search_brief\(.*\)\s+TO\s+service_role",
            sql,
            re.I,
        )
        is not None
    )
```

Run: `uv run pytest tests/unit/storage/test_supabase_migrations.py::test_vector_search_brief_rpc_omits_embedding_column -v`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add supabase/migrations/20260526000001_vector_search_brief.sql \
        src/context_store/storage/supabase.py \
        tests/unit/storage/test_supabase_adapter.py \
        tests/unit/storage/test_supabase_migrations.py
git commit -m "perf(storage): switch Supabase vector_search to brief RPC that omits embedding column"
```

---

## Task 4: Slim Supabase `select(...)` column lists on read paths

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [x] **Step 1: Add a failing test that `keyword_search` does not request embedding**

Append to `tests/unit/storage/test_supabase_adapter.py`:

```python
_BRIEF_COLUMNS = (
    "id,content,memory_type,source_type,source_metadata,"
    "semantic_relevance,importance_score,access_count,"
    "last_accessed_at,created_at,updated_at,archived_at,"
    "tags,project,content_hash"
)


@pytest.mark.asyncio
async def test_keyword_search_does_not_select_embedding():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value
        .ilike.return_value.is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.keyword_search("hello", top_k=5)

    client.table.return_value.select.assert_called_once_with(_BRIEF_COLUMNS)


@pytest.mark.asyncio
async def test_get_memory_does_not_select_embedding():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.get_memory("550e8400-e29b-41d4-a716-446655440000")

    client.table.return_value.select.assert_called_once_with(_BRIEF_COLUMNS)


@pytest.mark.asyncio
async def test_get_memories_batch_does_not_select_embedding():
    client = make_mock_client()
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.get_memories_batch(["550e8400-e29b-41d4-a716-446655440000"])

    client.table.return_value.select.assert_called_once_with(_BRIEF_COLUMNS)


@pytest.mark.asyncio
async def test_list_by_filter_does_not_select_embedding():
    client = make_mock_client()
    # MemoryFilters() leaves archived=None, which triggers .is_("archived_at", "null")
    # inside _apply_common_filters. The terminal builder is therefore one hop deeper.
    chain = client.table.return_value.select.return_value.is_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.list_by_filter(MemoryFilters())

    client.table.return_value.select.assert_called_once_with(_BRIEF_COLUMNS)
```

- [x] **Step 2: Run the new tests and confirm failures**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -k "does_not_select_embedding" -v`
Expected: FAIL — adapter still calls `select("*")`.

- [x] **Step 3: Add the column constant and replace `select("*")` on read paths**

In `src/context_store/storage/supabase.py`, add a module-level constant (right after `ALLOWED_UPDATE_COLUMNS` around line 60):

```python
# Read-path SELECT projection that intentionally omits the 768-dim `embedding`
# column to reduce per-row payload (~10KB) on retrieval. Write paths still
# fetch/insert the embedding via dedicated INSERT/UPDATE statements.
#
# Scope note (Phase 1): only the Supabase adapter applies this projection.
# Postgres/SQLite adapters still SELECT * because the SQLite-backed
# LifecycleManager (Consolidator at lifecycle/consolidator.py:113) reads
# `memory.embedding` from list_by_filter() results to feed vector_search().
# Current Supabase consumers of get_memory/get_memories_batch/list_by_filter
# (dashboard services, _resolve_graph_nodes, Consolidator._recompute_embedding)
# do not read `.embedding` from these results, so this change is safe today;
# future Supabase-side callers that need the embedding column MUST fetch it
# explicitly (e.g. through a future `get_memory_with_embedding` API).
_MEMORY_BRIEF_COLUMNS = (
    "id,content,memory_type,source_type,source_metadata,"
    "semantic_relevance,importance_score,access_count,"
    "last_accessed_at,created_at,updated_at,archived_at,"
    "tags,project,content_hash"
)
```

Then replace `select("*")` in:

- `get_memory` (line 212): `self._client.table("memories").select(_MEMORY_BRIEF_COLUMNS).eq(...)`
- `get_memories_batch` (line 229): `self._client.table("memories").select(_MEMORY_BRIEF_COLUMNS).in_(...)`
- `keyword_search` (line 299): `self._client.table("memories").select(_MEMORY_BRIEF_COLUMNS).ilike(...)`
- `list_by_filter` (line 319): `self._client.table("memories").select(_MEMORY_BRIEF_COLUMNS)`

Do **not** touch `count_by_filter` (line 372) — it uses `head=True` and needs `count="exact"` semantics.
Do **not** touch `save_memory` (line 173) — INSERT must still write the embedding column.
Do **not** touch `update_memory` (line 197) — UPDATE may need to write the embedding column.

- [x] **Step 4: Re-run the new tests**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -k "does_not_select_embedding" -v`
Expected: PASS.

- [x] **Step 5: Run the full adapter suite to catch regressions**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -v`
Expected: All PASS. (Any existing test that asserted `select("*")` needs the same constant; if you see a failure, replace the literal in the assertion with `_BRIEF_COLUMNS` from the test file.)

- [x] **Step 6: Commit**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "perf(storage): omit embedding column from Supabase read-path SELECTs"
```

---

## Task 5: Bulk `increment_memory_access_counts` across adapters and PostProcessor

**Files:**
- Create: `supabase/migrations/20260526000002_increment_memory_access_counts.sql`
- Modify: `src/context_store/storage/protocols.py`
- Modify: `src/context_store/storage/supabase.py`
- Modify: `src/context_store/storage/postgres.py`
- Modify: `src/context_store/storage/sqlite.py`
- Modify: `src/context_store/storage/factory.py`
- Modify: `src/context_store/retrieval/post_processor.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`
- Create: `tests/unit/test_post_processor.py`

- [x] **Step 1: Create the bulk RPC migration**

Create `supabase/migrations/20260526000002_increment_memory_access_counts.sql`:

```sql
-- ============================================================
-- increment_memory_access_counts: bulk variant of
-- increment_memory_access_count. Avoids N HTTPS round trips
-- after every search by accepting an array of UUIDs.
-- Returns the number of rows actually updated.
-- ============================================================
CREATE OR REPLACE FUNCTION increment_memory_access_counts(
    p_memory_ids uuid[]
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    affected integer;
BEGIN
    IF p_memory_ids IS NULL OR array_length(p_memory_ids, 1) IS NULL THEN
        RETURN 0;
    END IF;

    UPDATE memories
       SET access_count     = access_count + 1,
           last_accessed_at = NOW(),
           updated_at       = NOW()
     WHERE id = ANY(p_memory_ids);

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

GRANT EXECUTE ON FUNCTION increment_memory_access_counts(uuid[]) TO service_role;
```

- [x] **Step 2: Add the method to the StorageAdapter protocol**

In `src/context_store/storage/protocols.py`, add to the `StorageAdapter` protocol (right after `increment_memory_access_count` around line 118):

```python
    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        """Bulk variant: increment access_count for many memories in one call.

        Returns the number of rows actually updated.
        Implementations MUST issue at most one storage round trip.
        """
        ...
```

- [x] **Step 3: Add a failing test that the Supabase adapter calls the bulk RPC once**

Append to `tests/unit/storage/test_supabase_adapter.py`:

```python
@pytest.mark.asyncio
async def test_increment_memory_access_counts_invokes_bulk_rpc():
    client = make_mock_client()
    rpc_chain = client.rpc.return_value
    rpc_chain.execute = AsyncMock(return_value=make_mock_response(data=3))

    adapter = SupabaseStorageAdapter(client)
    ids = [
        "550e8400-e29b-41d4-a716-446655440001",
        "550e8400-e29b-41d4-a716-446655440002",
        "550e8400-e29b-41d4-a716-446655440003",
    ]
    affected = await adapter.increment_memory_access_counts(ids)

    assert affected == 3
    client.rpc.assert_called_once_with(
        "increment_memory_access_counts", {"p_memory_ids": ids}
    )


@pytest.mark.asyncio
async def test_increment_memory_access_counts_filters_invalid_uuids():
    client = make_mock_client()
    rpc_chain = client.rpc.return_value
    rpc_chain.execute = AsyncMock(return_value=make_mock_response(data=1))

    adapter = SupabaseStorageAdapter(client)
    ids = ["not-a-uuid", "550e8400-e29b-41d4-a716-446655440002"]
    affected = await adapter.increment_memory_access_counts(ids)

    assert affected == 1
    client.rpc.assert_called_once_with(
        "increment_memory_access_counts",
        {"p_memory_ids": ["550e8400-e29b-41d4-a716-446655440002"]},
    )


@pytest.mark.asyncio
async def test_increment_memory_access_counts_empty_list_skips_call():
    client = make_mock_client()
    adapter = SupabaseStorageAdapter(client)
    affected = await adapter.increment_memory_access_counts([])
    assert affected == 0
    client.rpc.assert_not_called()
```

- [x] **Step 4: Run the new tests and confirm failures**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -k "increment_memory_access_counts" -v`
Expected: FAIL — method does not exist on the adapter.

- [x] **Step 5: Implement the bulk method on the Supabase adapter**

In `src/context_store/storage/supabase.py`, add after `increment_memory_access_count` (line 392):

```python
    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        valid_ids = [mid for mid in memory_ids if _is_valid_uuid(mid)]
        if not valid_ids:
            return 0
        try:
            response = await self._client.rpc(
                "increment_memory_access_counts", {"p_memory_ids": valid_ids}
            ).execute()
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        data = response.data
        if isinstance(data, int):
            return data
        if isinstance(data, list) and data and isinstance(data[0], int):
            return data[0]
        return 0
```

- [x] **Step 6: Re-run the Supabase bulk tests**

Run: `uv run pytest tests/unit/storage/test_supabase_adapter.py -k "increment_memory_access_counts" -v`
Expected: PASS.

- [x] **Step 7: Add the bulk method to the Postgres adapter**

In `src/context_store/storage/postgres.py`, add a method near `increment_memory_access_count` (around line 460):

```python
    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        if not memory_ids:
            return 0
        cleaned: list[str] = []
        for mid in memory_ids:
            try:
                cleaned.append(str(UUID(str(mid))))
            except (TypeError, ValueError, AttributeError):
                continue
        if not cleaned:
            return 0
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = ANY($1::uuid[])"
        )
        async with self._pool.acquire() as conn:
            status = await conn.execute(sql, cleaned)
        # status is e.g. "UPDATE 3"
        parts = str(status).split()
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0
```

- [x] **Step 8: Add the bulk method to the SQLite adapter**

The SQLite adapter has no `_run_write` helper; all write paths use `async with self._db() as conn:` directly (see the existing `increment_memory_access_count` at `src/context_store/storage/sqlite.py:1004-1024` for the canonical pattern, including the `aiosqlite.OperationalError` → busy-lock translation).

In `src/context_store/storage/sqlite.py`, add the following method immediately after `increment_memory_access_count` (line 1024):

```python
    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        """Bulk variant: atomically bump access_count for many memories in one statement."""
        if not memory_ids:
            return 0
        placeholders = ",".join("?" for _ in memory_ids)
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = ?, "
            "    updated_at = ? "
            f"WHERE id IN ({placeholders})"
        )
        async with self._db() as conn:
            try:
                now = datetime.now(timezone.utc).isoformat()
                params: list[Any] = [now, now, *list(memory_ids)]
                async with conn.execute(sql, params) as cursor:
                    # DBAPI 2.0 allows rowcount == -1 (unknown). Clamp to >= 0
                    # because the bulk API contract is "number of rows updated".
                    updated_count: int = max(cursor.rowcount, 0)
                await conn.commit()
                return updated_count
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise
```

If `datetime`/`timezone`/`aiosqlite`/`_raise_if_locked`/`Any` are not already imported at the top of `sqlite.py`, they will already be available because the surrounding methods (`increment_memory_access_count`, `update_memory`, etc.) use the same symbols — verify the imports rather than re-adding them.

- [x] **Step 9: Add the bulk method to `ReadOnlyNoOpStorageAdapter`**

In `src/context_store/storage/factory.py`, after the existing `increment_memory_access_count` (line 112):

```python
    async def increment_memory_access_counts(self, memory_ids: list[str]) -> int:
        raise NotImplementedError(
            "ReadOnlyNoOpStorageAdapter: increment_memory_access_counts not implemented"
        )
```

- [x] **Step 10: Add a failing test that `PostProcessor.process` makes only one update call**

Create `tests/unit/test_post_processor.py` (the project currently has no dedicated unit tests for `PostProcessor`; coverage in `test_retrieval_pipeline.py` mocks it wholesale):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

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
        id=memory_id,
        content="x",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.MANUAL,
    )
    return ScoredMemory(memory=memory, score=0.9, source=MemorySource.VECTOR)


@pytest.mark.asyncio
async def test_post_processor_calls_bulk_increment_once():
    storage = MagicMock()
    storage.increment_memory_access_counts = AsyncMock(return_value=3)
    storage.increment_memory_access_count = AsyncMock()  # should not be called

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
```

- [x] **Step 11: Run the new PostProcessor tests and confirm failure**

Run: `uv run pytest tests/unit/test_post_processor.py -k "bulk_increment" -v`
Expected: FAIL — `PostProcessor.process` still calls the per-result API.

- [x] **Step 12: Update `PostProcessor.process` to call the bulk API**

In `src/context_store/retrieval/post_processor.py`, replace the `process` method's step 3 (lines 58-62) and delete `_update_access_record` (lines 137-152):

```python
    async def process(
        self,
        results: list[ScoredMemory],
        project: str | None = None,
        max_tokens: int | None = None,
    ) -> list[ScoredMemory]:
        if max_tokens is None:
            max_tokens = self.max_tokens

        filtered = self._filter_by_project(results, project)
        if max_tokens is not None:
            filtered = self._apply_token_limit(filtered, max_tokens)

        if filtered:
            memory_ids = [str(r.memory.id) for r in filtered]
            try:
                await self.storage_adapter.increment_memory_access_counts(memory_ids)
            except Exception as exc:
                logger.warning(
                    "Failed to bulk-update access records for %d memories: %s",
                    len(memory_ids),
                    exc,
                )

        return filtered
```

Remove the now-unused `_update_access_record` method and the unused `asyncio` import if nothing else needs it (keep `import logging`, `import math`).

- [x] **Step 13: Re-run the PostProcessor tests**

Run: `uv run pytest tests/unit/test_post_processor.py -v`
Expected: All PASS.

- [x] **Step 14: Run the full adapter and retrieval suites**

Run: `uv run pytest tests/unit/storage/ tests/unit/test_post_processor.py tests/unit/test_retrieval_pipeline.py -v`
Expected: All PASS.

- [x] **Step 14.5: Add a SQL-level regression test for the new bulk RPC migration**

Append to `tests/unit/storage/test_supabase_migrations.py`:

```python
def test_increment_memory_access_counts_rpc_accepts_uuid_array_and_returns_integer() -> None:
    sql = Path(
        "supabase/migrations/20260526000002_increment_memory_access_counts.sql"
    ).read_text()

    assert "CREATE OR REPLACE FUNCTION increment_memory_access_counts(" in sql
    # Argument signature: uuid[] (bulk variant).
    assert re.search(r"p_memory_ids\s+uuid\[\]", sql, re.I) is not None
    # Return type: integer (number of rows updated), not boolean (singular variant).
    assert re.search(r"RETURNS\s+integer", sql, re.I) is not None
    # The body must use ANY() to apply UPDATE in a single statement.
    function_body = sql.split("AS $$", 1)[1].split("$$;", 1)[0]
    assert re.search(r"=\s*ANY\(\s*p_memory_ids\s*\)", function_body, re.I) is not None
    # NULL/empty arrays must short-circuit to 0.
    assert re.search(r"array_length\(\s*p_memory_ids", function_body, re.I) is not None
    # Service role grant must be present.
    assert (
        re.search(
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+increment_memory_access_counts\(uuid\[\]\)"
            r"\s+TO\s+service_role",
            sql,
            re.I,
        )
        is not None
    )
```

Run: `uv run pytest tests/unit/storage/test_supabase_migrations.py::test_increment_memory_access_counts_rpc_accepts_uuid_array_and_returns_integer -v`
Expected: PASS.

- [x] **Step 15: Commit**

```bash
git add supabase/migrations/20260526000002_increment_memory_access_counts.sql \
        src/context_store/storage/protocols.py \
        src/context_store/storage/supabase.py \
        src/context_store/storage/postgres.py \
        src/context_store/storage/sqlite.py \
        src/context_store/storage/factory.py \
        src/context_store/retrieval/post_processor.py \
        tests/unit/storage/test_supabase_adapter.py \
        tests/unit/storage/test_supabase_migrations.py \
        tests/unit/test_post_processor.py
git commit -m "perf(retrieval): batch access-count updates into a single bulk RPC"
```

---

## Task 6: Reuse `LocalModelEmbeddingProvider` thread executor and wire its lifecycle into the Orchestrator

**Files:**
- Modify: `src/context_store/embedding/local_model.py`
- Modify: `src/context_store/orchestrator.py`
- Modify: `tests/unit/test_embedding_local.py`

**Scope note:**
The provider gains a `start()` method that can be called explicitly to preload the model in a worker thread, but `Orchestrator.create_orchestrator()` does **not** auto-invoke it. Reason: orchestrator init is performed lazily inside `_ensure_initialized()` on the first MCP tool call, so `await start()` there does not actually move the cold-start cost off the first-call critical path; the call still blocks for the same wall time. True cold-start avoidance requires preloading at the FastMCP `lifespan` startup (eager provider construction), which is tracked as a separate item in `SPEC.md` §16.5 and is out of scope for Phase 1. Phase 1's local-model win is the executor reuse alone (one shared `ThreadPoolExecutor` instead of one per `embed_batch` call) plus correct disposal.

- [x] **Step 1: Update the top-of-file imports in `tests/unit/test_embedding_local.py`**

The existing file already imports `MagicMock, patch` and `pytest` at the top. Add `ThreadPoolExecutor` to that import block so the new tests can perform `isinstance` checks without violating ruff E402 (module-level imports must precede class/function definitions).

In `tests/unit/test_embedding_local.py`, replace the existing import block (lines 1-9):

```python
"""Tests for Local Model (sentence-transformers) Embedding Provider."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from context_store.embedding.protocols import EmbeddingProvider
```

- [x] **Step 2: Append the new failing tests at the end of `tests/unit/test_embedding_local.py`**

Use the existing project pattern for `encode().return_value` (a list of `MagicMock` instances each exposing `.tolist()`), matching `TestLocalModelEmbeddingProvider._make_mock_model` and `test_embed_batch` already in the file. A plain `[[0.1]*8, ...]` would break because the production code calls `emb.tolist()`.

Append at the end of `tests/unit/test_embedding_local.py`:

```python
def _make_executor_test_model(values: list[list[float]] | None = None) -> MagicMock:
    """Mock model whose ``encode`` returns objects with ``.tolist()``."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 8
    vectors = values if values is not None else [[0.1] * 8, [0.2] * 8]
    mock_embeddings = []
    for vec in vectors:
        emb = MagicMock()
        emb.tolist.return_value = vec
        mock_embeddings.append(emb)
    model.encode.return_value = mock_embeddings
    return model


@pytest.mark.asyncio
async def test_embed_batch_reuses_single_executor() -> None:
    """A single ThreadPoolExecutor must be reused across calls."""
    from context_store.embedding.local_model import LocalModelEmbeddingProvider

    with patch(
        "context_store.embedding.local_model.SentenceTransformer",
        return_value=_make_executor_test_model(),
    ):
        provider = LocalModelEmbeddingProvider(model_name="fake", dimension=8)
        await provider.embed_batch(["a", "b"])
        first_executor = provider._executor
        await provider.embed_batch(["c", "d"])
        second_executor = provider._executor

    assert first_executor is second_executor
    assert isinstance(first_executor, ThreadPoolExecutor)


@pytest.mark.asyncio
async def test_start_preloads_model_off_event_loop() -> None:
    """Explicit start() must load the model before the first embed_batch."""
    from context_store.embedding.local_model import LocalModelEmbeddingProvider

    fake = _make_executor_test_model()
    with patch(
        "context_store.embedding.local_model.SentenceTransformer",
        return_value=fake,
    ) as ctor:
        provider = LocalModelEmbeddingProvider(model_name="fake", dimension=8)
        assert provider._model is None
        await provider.start()
        assert provider._model is fake
        # Subsequent embed_batch must NOT trigger a second model construction.
        await provider.embed_batch(["a"])
        assert ctor.call_count == 1


@pytest.mark.asyncio
async def test_close_shuts_down_executor() -> None:
    """close() must shut down the shared executor."""
    from context_store.embedding.local_model import LocalModelEmbeddingProvider

    with patch(
        "context_store.embedding.local_model.SentenceTransformer",
        return_value=_make_executor_test_model(),
    ):
        provider = LocalModelEmbeddingProvider(model_name="fake", dimension=8)
        await provider.embed_batch(["a"])
        executor = provider._executor
        await provider.close()

    # Submitting to a shut-down ThreadPoolExecutor raises RuntimeError.
    with pytest.raises(RuntimeError):
        executor.submit(lambda: None)
```

- [x] **Step 3: Run the new tests and confirm they fail**

Run: `uv run pytest tests/unit/test_embedding_local.py -k "reuses_single_executor or preloads_model or close_shuts_down" -v`
Expected: FAIL — `provider._executor` does not exist and `start()` is not defined.

- [x] **Step 4: Replace per-call executor with a long-lived one**

Rewrite `src/context_store/embedding/local_model.py`:

```python
"""Local Model (sentence-transformers) Embedding Provider."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_NAME = "cl-nagoya/ruri-v3-310m"


def SentenceTransformer(model_name: str) -> Any:  # noqa: N802
    """sentence_transformers.SentenceTransformer を遅延ロードして初期化する。"""
    try:
        from sentence_transformers import SentenceTransformer as ST  # type: ignore[import]

        return ST(model_name)
    except ImportError as e:
        raise ImportError(
            "sentence-transformers が未インストールです。"
            "pip install 'context-store-mcp[embedding-local]' でインストールしてください。"
        ) from e


class LocalModelEmbeddingProvider:
    """sentence-transformers backed embedding provider.

    Uses a single long-lived ``ThreadPoolExecutor`` so per-call thread-pool
    construction overhead is eliminated. ``start()`` is provided so an
    external caller (e.g. a FastMCP lifespan handler) can preload the model
    off the event loop; it is NOT auto-called by ``create_orchestrator``
    because orchestrator init is itself lazy and would not actually move the
    cold-start cost off the first-call critical path. ``close()`` must be
    called by the owner (Orchestrator) to shut down the worker thread pool.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL_NAME,
        dimension: int | None = None,
        max_workers: int = 1,
    ) -> None:
        if dimension is not None:
            if not isinstance(dimension, int) or dimension <= 0:
                raise ValueError(f"dimension must be a positive integer, got {dimension}")
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")

        self._model_name = model_name
        self._model: Any = None
        self._dimension: int | None = dimension
        self._model_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="local-embedding",
        )
        self._closed = False

    def _get_model(self) -> Any:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info("ローカルモデルをロード中: %s", self._model_name)
                    model = SentenceTransformer(self._model_name)
                    if self._dimension is None:
                        dim = model.get_sentence_embedding_dimension()
                        if dim is not None:
                            self._dimension = int(dim)
                        else:
                            logger.info(
                                "次元数を自動取得するためにサンプルテキストをエンコードします"
                            )
                            sample_emb = model.encode(["dim check"])[0]
                            self._dimension = len(sample_emb)
                    self._model = model
                    logger.info("モデルのロード完了: dimension=%d", self._dimension)
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is not None:
            return self._dimension
        self._get_model()
        if self._dimension is None:
            raise RuntimeError("Dimension must be set after loading model")
        return self._dimension

    async def start(self) -> None:
        """Optionally preload the model on a worker thread.

        Not called automatically by the orchestrator; intended for callers
        that own MCP server startup (e.g. FastMCP ``lifespan`` hook) and can
        afford to pay the cold-start cost before the first client request.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._get_model)

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def _encode() -> list[list[float]]:
            model = self._get_model()
            embeddings = model.encode(texts, show_progress_bar=False)
            return [emb.tolist() for emb in embeddings]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _encode)

    async def close(self) -> None:
        """Shut down the worker thread pool (idempotent)."""
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=True)
```

- [x] **Step 5: Re-run the local-model tests**

Run: `uv run pytest tests/unit/test_embedding_local.py -v`
Expected: All PASS.

- [x] **Step 6: Wire `embedding_provider.close()` into `Orchestrator.dispose()`**

In `src/context_store/orchestrator.py`, extend `Orchestrator.dispose()` (lines 431-466). After the existing `self._cache.dispose()` try block (around line 464), add a fourth try block:

```python
        # 4. Embedding provider (added in Phase 1: required to release the
        # long-lived ThreadPoolExecutor owned by LocalModelEmbeddingProvider).
        try:
            close = getattr(self._embedding_provider, "close", None)
            if callable(close):
                await close()
        except Exception as exc:
            logger.error("Failed to dispose embedding provider: %s", exc, exc_info=True)
```

- [x] **Step 7: Add a failing test for orchestrator-level disposal**

Add the following to `tests/unit/test_orchestrator.py` (or to the existing dispose-coverage test file under `tests/unit/`; if there is no dispose test yet, append a new test function at the end of `tests/unit/test_orchestrator.py`):

```python
@pytest.mark.asyncio
async def test_orchestrator_dispose_closes_embedding_provider() -> None:
    """Orchestrator.dispose() must call embedding_provider.close()."""
    from unittest.mock import AsyncMock, MagicMock

    from context_store.orchestrator import Orchestrator

    embedding_provider = MagicMock()
    embedding_provider.close = AsyncMock()

    storage = MagicMock()
    storage.dispose = AsyncMock()
    cache = MagicMock()
    cache.dispose = AsyncMock()
    lifecycle_manager = MagicMock()
    lifecycle_manager.graceful_shutdown = AsyncMock()
    task_registry = MagicMock()
    task_registry.cancel_all = AsyncMock()
    task_registry.__len__ = MagicMock(return_value=0)

    orchestrator = Orchestrator(
        storage=storage,
        graph=None,
        cache=cache,
        embedding_provider=embedding_provider,
        ingestion_pipeline=MagicMock(),
        retrieval_pipeline=MagicMock(),
        lifecycle_manager=lifecycle_manager,
        task_registry=task_registry,
    )

    await orchestrator.dispose()

    embedding_provider.close.assert_awaited_once()
```

- [x] **Step 8: Wire `embedding_provider.close()` into the `create_orchestrator` failure path**

In `src/context_store/orchestrator.py`, locate the `except Exception:` block at the end of `create_orchestrator` (lines 605-611). Currently it disposes storage/graph/cache only. Replace the block with the version below so the executor is released even when ingestion/retrieval pipeline construction or `_check_vector_dimension` raises:

```python
    except Exception:
        # 初期化失敗時は全アダプターのリソースを解放して再送
        await storage.dispose()
        if graph is not None:
            await graph.dispose()
        await cache.dispose()
        # `embedding_provider` may have been created (Task 6 adds an executor
        # in its __init__); release it if so. Guarded against the early-fail
        # path where create_embedding_provider() itself raised.
        provider = locals().get("embedding_provider")
        if provider is not None:
            try:
                close = getattr(provider, "close", None)
                if callable(close):
                    await close()
            except Exception:
                logger.exception("Failed to close embedding provider during init cleanup")
        raise
```

- [x] **Step 9: Run the orchestrator tests**

Run: `uv run pytest tests/unit/test_orchestrator.py -v`
Expected: All PASS, including the new dispose test from Step 7.

- [x] **Step 10: Commit**

```bash
git add src/context_store/embedding/local_model.py \
        src/context_store/orchestrator.py \
        tests/unit/test_embedding_local.py \
        tests/unit/test_orchestrator.py
git commit -m "perf(embedding): reuse local-model executor and tie its lifecycle to Orchestrator"
```

---

## Task 7: Batch all ingestion chunk embeddings into a single `embed_batch` call

**Files:**
- Modify: `src/context_store/ingestion/pipeline.py`
- Modify: `tests/unit/test_ingestion_pipeline.py`

**Failure-mode note (intentional behavior change):**
Before Phase 1, embedding errors were caught per-chunk inside the inner `try/except`, so a single bad chunk would not abort the whole batch. After this task, `embed_batch([all chunks])` is called once up-front, so an exception there aborts the entire `ingest()` call (no per-chunk granularity for embedding failures). This is acceptable for Phase 1 because every supported embedding provider (Local, OpenAI, LiteLLM, CustomAPI) fails at the batch granularity in practice (model crash / 429 / 5xx / OOM affect the entire request). Per-text fault isolation is deferred (a future provider with deterministic per-text failure modes can reintroduce it by falling back to per-chunk `embed()` on `embed_batch` failure). Step 6.5 below adds a regression test that pins this contract.

- [x] **Step 1: Add a failing test that asserts one embed_batch call regardless of chunk count**

Append to `tests/unit/test_ingestion_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_ingest_calls_embed_batch_once_for_all_chunks(
    monkeypatch,
):
    """IngestionPipeline.ingest must batch-embed all chunks in a single call."""
    from unittest.mock import AsyncMock, MagicMock

    from context_store.ingestion.pipeline import IngestionPipeline
    from context_store.models.memory import SourceType

    storage = MagicMock()
    storage.vector_search = AsyncMock(return_value=[])
    storage.save_memory = AsyncMock(return_value="550e8400-e29b-41d4-a716-446655440099")
    storage.list_by_filter = AsyncMock(return_value=[])

    embedding_provider = MagicMock()
    embedding_provider.embed_batch = AsyncMock(return_value=[[0.1] * 8 for _ in range(3)])
    embedding_provider.embed = AsyncMock(return_value=[0.1] * 8)
    embedding_provider.dimension = 8
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=None,
        embedding_provider=embedding_provider,
        settings=None,
    )

    # Force three chunks by stubbing the chunker.
    class _FakeChunk:
        def __init__(self, content, idx):
            from context_store.ingestion.adapters import RawContent
            from context_store.models.memory import SourceType as _ST

            self._raw = RawContent(
                content=content,
                source_type=_ST.MANUAL,
                metadata={"chunk_index": idx, "chunk_count": 3},
            )

        def __iter__(self):
            return iter([self._raw])

    fake_chunks = [
        _FakeChunk("c0", 0),
        _FakeChunk("c1", 1),
        _FakeChunk("c2", 2),
    ]

    def fake_chunk(raw):
        for c in fake_chunks:
            yield c._raw

    monkeypatch.setattr(pipeline._chunker, "chunk", fake_chunk)

    await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    embedding_provider.embed_batch.assert_awaited_once()
    embed_call = embedding_provider.embed_batch.await_args
    assert embed_call.args[0] == ["c0", "c1", "c2"]
    # The per-chunk embed() shortcut must NOT be invoked when batch is used.
    embedding_provider.embed.assert_not_awaited()
```

- [x] **Step 2: Run the new test and confirm it fails**

Run: `uv run pytest tests/unit/test_ingestion_pipeline.py::test_ingest_calls_embed_batch_once_for_all_chunks -v`
Expected: FAIL — `embed_batch` is never called; `embed` is called three times.

- [x] **Step 3: Refactor `IngestionPipeline.ingest` to pre-batch embeddings**

In `src/context_store/ingestion/pipeline.py`, change `ingest` (lines 191-263). Keep the locking and result construction logic intact; only extract embedding into a single up-front pass and pipe precomputed vectors through:

```python
    async def ingest(
        self,
        source: str,
        *,
        source_type: SourceType = SourceType.MANUAL,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestionResult]:
        meta = metadata or {}

        raw_contents = await self._prepare_raw_contents(source, source_type, meta)

        # Step A: Flatten all chunks across all raw contents (preserving order).
        flattened: list[RawContent] = []
        for raw in raw_contents:
            flattened.extend(self._chunker.chunk(raw))

        if not flattened:
            return []

        # Step B: Batch-embed every chunk in a single provider call.
        embeddings = await self._embedding_provider.embed_batch(
            [chunk.content for chunk in flattened]
        )
        if len(embeddings) != len(flattened):
            raise RuntimeError(
                f"Embedding count mismatch: expected {len(flattened)}, got {len(embeddings)}"
            )

        # Step C: Process chunks sequentially using precomputed embeddings.
        # Parallelization is intentionally deferred (see Phase 2 plan).
        results: list[IngestionResult] = []
        document_memories: dict[str, list[Memory]] = {}
        failed_chunks: list[dict[str, Any]] = []

        for chunk, embedding in zip(flattened, embeddings):
            document_id = str(chunk.metadata.get("document_id", ""))
            prior_document_memories = document_memories.get(document_id, [])
            content_hash = self._compute_hash(chunk.content)
            try:
                result = await self._process_chunk(
                    chunk,
                    base_metadata=meta,
                    prior_document_memories=prior_document_memories,
                    precomputed_embedding=embedding,
                )
                if result:
                    results.append(result)
                    if document_id and result.persisted_memory is not None:
                        document_memories.setdefault(document_id, []).append(
                            result.persisted_memory
                        )
            except Exception as e:
                logger.error(
                    "Chunk 処理失敗 (content_hash=%s, doc_id=%s): %s",
                    content_hash[:8],
                    document_id,
                    e,
                    exc_info=True,
                )
                failed_chunks.append(
                    {
                        "content_hash": content_hash,
                        "document_id": document_id,
                        "error": str(e),
                    }
                )

        if flattened and not results:
            raise RuntimeError(
                f"Ingestion 全件失敗 ({len(failed_chunks)}/{len(flattened)} chunks). "
                f"Failures: {failed_chunks}"
            )

        return results
```

- [x] **Step 4: Plumb `precomputed_embedding` through `_process_chunk` and `_process_chunk_core`**

In the same file, update the two methods to accept and forward `precomputed_embedding`:

```python
    async def _process_chunk(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        precomputed_embedding: list[float] | None = None,
    ) -> IngestionResult | None:
        content_hash = self._compute_hash(chunk.content)
        merged_meta = {**base_metadata, **chunk.metadata}
        meta_json = json.dumps(merged_meta, sort_keys=True, default=self._serialize_meta)
        meta_hash = hashlib.sha256(meta_json.encode("utf-8")).hexdigest()
        memo_key = (content_hash, meta_hash, chunk.source_type.value)

        async with self._locks_mutex:
            target_task = self._content_results.get(memo_key)
            if target_task is None:
                target_task = asyncio.create_task(
                    self._process_chunk_task_wrapper(
                        chunk,
                        base_metadata=base_metadata,
                        prior_document_memories=prior_document_memories,
                        memo_key=memo_key,
                        content_hash=content_hash,
                        precomputed_embedding=precomputed_embedding,
                    )
                )
                self._content_results[memo_key] = target_task

        return await asyncio.shield(target_task)

    async def _process_chunk_task_wrapper(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        memo_key: Any,
        content_hash: str,
        precomputed_embedding: list[float] | None = None,
    ) -> IngestionResult | None:
        try:
            return await self._process_chunk_core(
                chunk,
                base_metadata=base_metadata,
                prior_document_memories=prior_document_memories,
                content_hash=content_hash,
                precomputed_embedding=precomputed_embedding,
            )
        finally:
            async with self._locks_mutex:
                if self._content_results.get(memo_key) is asyncio.current_task():
                    self._content_results.pop(memo_key, None)
```

And in `_process_chunk_core` (around line 327), replace the single embed call with the precomputed fallback:

```python
    async def _process_chunk_core(
        self,
        chunk: RawContent,
        *,
        base_metadata: dict[str, Any],
        prior_document_memories: list[Memory],
        content_hash: str,
        precomputed_embedding: list[float] | None = None,
    ) -> IngestionResult | None:
        classification = self._classifier.classify(chunk)

        if precomputed_embedding is not None:
            embedding = precomputed_embedding
        else:
            embedding = await self._embedding_provider.embed(chunk.content)

        # ... rest of the method unchanged ...
```

- [x] **Step 5: Re-run the new ingestion test**

Run: `uv run pytest tests/unit/test_ingestion_pipeline.py::test_ingest_calls_embed_batch_once_for_all_chunks -v`
Expected: PASS.

- [x] **Step 6: Run the full ingestion test module**

Run: `uv run pytest tests/unit/test_ingestion_pipeline.py tests/unit/test_batch_processor.py -v`
Expected: All PASS. (Existing tests that mocked `embed()` will still pass because the per-chunk fallback path is preserved when `precomputed_embedding is None`.)

- [x] **Step 6.5: Pin the all-or-nothing failure contract for embed_batch errors**

Append to `tests/unit/test_ingestion_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_ingest_propagates_embed_batch_failure() -> None:
    """When embed_batch raises, ingest() must abort instead of silently partially succeeding."""
    from unittest.mock import AsyncMock, MagicMock

    from context_store.ingestion.pipeline import IngestionPipeline
    from context_store.models.memory import SourceType

    storage = MagicMock()
    storage.vector_search = AsyncMock(return_value=[])
    storage.save_memory = AsyncMock()  # must NOT be called
    storage.list_by_filter = AsyncMock(return_value=[])

    embedding_provider = MagicMock()
    embedding_provider.embed_batch = AsyncMock(side_effect=RuntimeError("embedding backend down"))
    embedding_provider.embed = AsyncMock()  # must NOT be called either
    embedding_provider.dimension = 8
    embedding_provider.close = AsyncMock()

    pipeline = IngestionPipeline(
        storage=storage,
        graph=None,
        embedding_provider=embedding_provider,
        settings=None,
    )

    with pytest.raises(RuntimeError, match="embedding backend down"):
        await pipeline.ingest("dummy", source_type=SourceType.MANUAL, metadata={})

    storage.save_memory.assert_not_called()
    embedding_provider.embed.assert_not_called()
```

Run: `uv run pytest tests/unit/test_ingestion_pipeline.py::test_ingest_propagates_embed_batch_failure -v`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add src/context_store/ingestion/pipeline.py tests/unit/test_ingestion_pipeline.py
git commit -m "perf(ingestion): batch-embed all chunks in a single provider call"
```

---

## Final Verification (Perform after completing Tasks 1–7)

> [!IMPORTANT]
> Perform this Final Verification only after completing all Tasks 1–7 (including the second migration in Task 5). This is the final check following the second migration, rather than a step-by-step verification after Tasks 1–3. Specifically, Step 4 below requires the migrations from Task 5 to be fully applied.

**Execution environment:** Per `AGENTS.md` / `CLAUDE.md` §5, all backend verification commands below **MUST be run inside the project devcontainer** (`.devcontainer/`). Running them on the host risks toolchain drift (e.g. different `uv`, mismatched `ruff`/`mypy` versions, missing `aiosqlite` wheels for the host arch) and is not a supported configuration. Open the workspace in the devcontainer (`Reopen in Container` in VS Code, or `devcontainer up && devcontainer exec`) before proceeding.

- [ ] **Step 1: Run the full unit suite**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS.

- [ ] **Step 2: Run the lint/type checks**

Run: `uv run ruff check src/ tests/ && uv run mypy src/`
Expected: No errors.

- [ ] **Step 3: (Optional) Run the integration suite if Supabase credentials are configured**

Run: `uv run pytest tests/integration/ -v`
Expected: All PASS (or skipped when credentials are absent).

- [ ] **Step 4: Sanity-check latency in a local devcontainer against a remote Supabase instance**

After applying the two new SQL migrations to the target Supabase project, exercise `memory_search` with `top_k=10` and `memory_save` with a ~8 KB conversation log, then capture:
- Per-call wall time before vs after this plan.
- Bytes transferred per `memory_search` response.

Document the observed numbers in the PR description so the Phase 2 plan (parallel chunk processing + tenacity tuning) can be prioritized accordingly.
