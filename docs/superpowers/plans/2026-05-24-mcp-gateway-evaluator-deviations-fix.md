# MCP Gateway Evaluator Deviations Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix deviations between the Phase 3 design/plan and implementation by making `RetrievalPipeline.create_for_dashboard` asynchronous and narrowing the exception handling in the `/api/memories/semantic-search` endpoint.

**Architecture:** Convert `RetrievalPipeline.create_for_dashboard` and `create_from_parts` from `def` to `async def` and `await` them where used. Narrow the `try/except` block in `src/context_store/dashboard/routes/memories.py` to only catch `RuntimeError`.

**Tech Stack:** Python 3.12 / pytest

---

### Task 1: Make RetrievalPipeline factory methods asynchronous

**Files:**
- Modify: `src/context_store/retrieval/pipeline.py`
- Modify: `src/context_store/orchestrator.py`
- Modify: `src/context_store/dashboard/api_server.py`
- Modify: `tests/unit/test_retrieval_pipeline_factory.py`

- [ ] **Step 1: Write the failing tests**
Update `tests/unit/test_retrieval_pipeline_factory.py` to reflect the async signature.

```python
import pytest
from unittest.mock import MagicMock, patch

from context_store.retrieval.pipeline import RetrievalPipeline

@pytest.mark.asyncio
async def test_create_for_dashboard_returns_pipeline_with_search() -> None:
    storage = MagicMock(name="StorageAdapter")
    graph = MagicMock(name="GraphAdapter")
    settings = MagicMock(
        embedding_provider="openai",
        openai_api_key=MagicMock(get_secret_value=MagicMock(return_value="fake-key")),
        graph_max_logical_depth=2,
        graph_fanout_limit=10,
        graph_max_physical_hops=4,
    )

    with patch("context_store.embedding.create_embedding_provider") as mock_create:
        mock_create.return_value = MagicMock()
        pipeline = await RetrievalPipeline.create_for_dashboard(
            storage=storage, graph=graph, settings=settings
        )

    assert isinstance(pipeline, RetrievalPipeline)
    assert hasattr(pipeline, "search")
```

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/unit/test_retrieval_pipeline_factory.py -v`
Expected: FAIL due to `create_for_dashboard` not being an async function (RuntimeWarning about unawaited coroutine, or just returning a synchronous result that fails to be awaited).

- [ ] **Step 3: Write minimal implementation**
Modify `src/context_store/retrieval/pipeline.py` to change `create_for_dashboard` and `create_from_parts` to `async def`. Note: They might not need to `await` anything yet, but the design mandates they be async.

```python
    @classmethod
    async def create_for_dashboard(
        cls,
        *,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
        settings: Settings,
    ) -> RetrievalPipeline:
        """Build a RetrievalPipeline for the read-only dashboard."""
        from context_store.embedding import create_embedding_provider

        embedding_provider = create_embedding_provider(settings)
        return await cls.create_from_parts(
            storage=storage,
            graph=graph,
            embedding_provider=embedding_provider,
            settings=settings,
        )

    @classmethod
    async def create_from_parts(
        cls,
        *,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
        embedding_provider: EmbeddingProvider,
        settings: Settings,
    ) -> RetrievalPipeline:
```

Modify `src/context_store/dashboard/api_server.py` to `await` it:

```python
            from context_store.retrieval.pipeline import RetrievalPipeline

            retrieval_pipeline = await RetrievalPipeline.create_for_dashboard(
                storage=storage,
                graph=graph,
                settings=settings,
            )
```

Modify `src/context_store/orchestrator.py` to `await` it where it constructs the pipeline (around `retrieval_pipeline = await RetrievalPipeline.create_from_parts(...)`).

- [ ] **Step 4: Run tests to verify they pass**
Run: `uv run pytest tests/unit/test_retrieval_pipeline_factory.py tests/unit/test_orchestrator.py tests/unit/test_api_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/context_store/retrieval/pipeline.py src/context_store/dashboard/api_server.py src/context_store/orchestrator.py tests/unit/test_retrieval_pipeline_factory.py
git commit -m "fix(mcp_gateway): make RetrievalPipeline factory methods asynchronous"
```

### Task 2: Restrict Exception Catching in Semantic Search Route

**Files:**
- Modify: `src/context_store/dashboard/routes/memories.py`
- Modify: `tests/unit/test_dashboard_semantic_search.py`

- [ ] **Step 1: Write the failing test**
Update `tests/unit/test_dashboard_semantic_search.py` to add a test ensuring other exceptions are not masked.

```python
def test_semantic_search_endpoint_does_not_mask_other_exceptions() -> None:
    pipeline = MagicMock()
    pipeline.search = AsyncMock(side_effect=ConnectionError("Database down"))

    service = DashboardService(storage=MagicMock(), graph=None, retrieval_pipeline=pipeline)
    app = create_app(service_override=service)
    
    with TestClient(app) as client:
        with pytest.raises(ConnectionError, match="Database down"):
            client.post("/api/memories/semantic-search", json={"query": "x"})
```

- [ ] **Step 2: Run test to verify it fails**
Run: `uv run pytest tests/unit/test_dashboard_semantic_search.py::test_semantic_search_endpoint_does_not_mask_other_exceptions -v`
Expected: FAIL because the route catches `ConnectionError` and raises a 503 HTTP exception.

- [ ] **Step 3: Write minimal implementation**
Modify `src/context_store/dashboard/routes/memories.py` to only catch `RuntimeError` and provide the exact exception detail.

```python
    try:
        memories = await service.semantic_search(
            query=req.query,
            project=req.project,
            top_k=req.top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
```

- [ ] **Step 4: Run test to verify it passes**
Run: `uv run pytest tests/unit/test_dashboard_semantic_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/context_store/dashboard/routes/memories.py tests/unit/test_dashboard_semantic_search.py
git commit -m "fix(mcp_gateway): narrow exception catching in semantic search route"
```
