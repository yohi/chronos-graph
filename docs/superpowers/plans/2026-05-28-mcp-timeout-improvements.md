# MCP メモリ操作タイムアウト対策 (Phase 2) 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ボトルネック監査（2026-05-26）で抽出されたタイムアウト・レイテンシ関連の改善を実装し、MCP Gateway層の安定性とレスポンス時間を向上させる。

**Architecture:** 
本計画はSPEC.md §16.5で定義された9個の改善項目（D-1, D-2, D-3, E-1, E-2, E-3, E-4, E-5, E-6, E-7）をPhase 2以降のロードマップとして実装。
高優先度（High）の4項目（D-1, D-2, E-1, E-2）を優先し、Medium/Low優先度の項目は段階的に実装する。
各改善はタイムアウト問題の根本原因（直列処理、リトライ長期化、lazy初期化）に対応。

**Tech Stack:** 
- asyncio.wait_for（明示的タイムアウト）
- asyncio.gather（並列化）
- tenacity（リトライ戦略調整）
- FastMCP lifespan hooks（早期初期化）
- Supabase RPC（API ラウンドトリップ削減）

---

## ファイル構造

改善項目ごとに以下のファイルを新規作成・修正：

### 新規ファイル

- `src/mcp_gateway/upstream/timeout_client.py` — `UpstreamClient` のタイムアウト機構（D-1）
- `src/context_store/embedding/retry_config.py` — LiteLLM/OpenAI 統一リトライ設定（E-2）
- `supabase/migrations/{date}_keyword_search_optimization.sql` — 全文検索 RPC 定義（E-3）
- `tests/unit/test_upstream_timeout.py` — UpstreamClient タイムアウト単体テスト（D-1）
- `tests/unit/test_embedding_retry.py` — 埋め込みリトライ戦略テスト（E-2）
- `tests/unit/test_ingestion_parallel.py` — 並列化 テスト（E-1）

### 修正対象ファイル

| ファイル | 改善項目 | 変更内容 |
|---------|---------|---------|
| `src/mcp_gateway/upstream/context_store_client.py` | D-1 | `call_tool` を `asyncio.wait_for` でラップ |
| `src/mcp_gateway/policy/llm_evaluator.py` | D-2 | Read系ツール評価バイパス、結果キャッシュ、並列化 |
| `src/mcp_gateway/policy/intents.yaml` | D-3 | 承認バイパス対象ツール分類 |
| `src/mcp_gateway/server.py` | D-3 | 承認タイムアウト可変化、non-blocking flow 検討 |
| `src/context_store/ingestion/pipeline.py` | E-1 | `_process_chunk` の並列化（`asyncio.gather` + Semaphore） |
| `src/context_store/embedding/openai.py` | E-2 | リトライ設定参照、`Retry-After` ヘッダ尊重 |
| `src/context_store/embedding/litellm.py` | E-2 | リトライ設定参照 |
| `src/context_store/storage/supabase.py` | E-3, E-5 | `keyword_search` 戦略改善、`count_active_and_archived` RPC 呼び出し |
| `src/context_store/ingestion/graph_linker.py` | E-4 | `vector_search` 結果のキャッシング・パススルー |
| `src/context_store/ingestion/deduplicator.py` | E-4 | `similar_memories` リスト返却 |
| `src/context_store/server.py` | E-7 | FastMCP `lifespan` hook での埋め込みプロバイダ eager 初期化 |
| `src/context_store/orchestrator.py` | E-4, E-5 | `GraphLinker.link()` へのキャッシュ結果パス、`stats()` RPC 集約 |

---

## Task 1: D-1 UpstreamClient.call_tool タイムアウト導入

**Files:**
- Create: `src/mcp_gateway/upstream/timeout_client.py`
- Modify: `src/mcp_gateway/upstream/context_store_client.py`
- Test: `tests/unit/test_upstream_timeout.py`

タイムアウト機構を専用モジュールで定義し、`UpstreamClient.call_tool` を `asyncio.wait_for` でラップする。

- [ ] **Step 1: タイムアウト設定モジュール作成**

Create `src/mcp_gateway/upstream/timeout_client.py`:

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class TimeoutConfig:
    """MCP tool call タイムアウト設定"""
    default_timeout_seconds: float = 30.0
    max_timeout_seconds: float = 300.0
    
    def get_timeout(self, tool_name: str) -> float:
        """ツール別タイムアウト値を取得。現段階では統一値を返す"""
        if tool_name in ["memory_save_url"]:
            # URL取得は最大限可能性のため40秒
            return min(40.0, self.max_timeout_seconds)
        return self.default_timeout_seconds
```

- [ ] **Step 2: UpstreamClient.call_tool ラップ機能の実装**

Modify `src/mcp_gateway/upstream/context_store_client.py` around line 117-123:

```python
import asyncio
from typing import Any
from .timeout_client import TimeoutConfig

class UpstreamClient:
    def __init__(self, ...):
        # ... existing code ...
        self.timeout_config = TimeoutConfig(
            default_timeout_seconds=float(
                os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "30.0")
            )
        )
    
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """MCP tool call with explicit timeout."""
        timeout = self.timeout_config.get_timeout(tool_name)
        try:
            result = await asyncio.wait_for(
                self._call_tool_internal(tool_name, arguments),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            raise UpstreamError(
                code="UPSTREAM_TIMEOUT",
                message=f"Tool '{tool_name}' timed out after {timeout}s",
                recoverable=True
            )
        except Exception as e:
            # 既存のエラーハンドリング
            raise UpstreamError(...) from e
    
    async def _call_tool_internal(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """既存の call_tool ロジックをここに移動"""
        # ... existing implementation ...
        return await self.client.call_tool(tool_name, arguments)
```

- [ ] **Step 3: タイムアウトテスト作成**

Create `tests/unit/test_upstream_timeout.py`:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from src.mcp_gateway.upstream.context_store_client import UpstreamClient
from src.mcp_gateway.upstream.timeout_client import TimeoutConfig

@pytest.mark.asyncio
async def test_tool_call_timeout():
    """Tool call timeout is raised correctly"""
    client = UpstreamClient(...)
    client.timeout_config = TimeoutConfig(default_timeout_seconds=0.1)
    
    # Mock slow internal call
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(1.0)
        return {"result": "data"}
    
    client._call_tool_internal = slow_call
    
    from src.mcp_gateway.upstream.context_store_client import UpstreamError
    with pytest.raises(UpstreamError) as exc_info:
        await client.call_tool("memory_search", {"query": "test"})
    
    assert exc_info.value.code == "UPSTREAM_TIMEOUT"
    assert "timed out after 0.1s" in exc_info.value.message

@pytest.mark.asyncio
async def test_tool_call_success_within_timeout():
    """Normal tool call completes within timeout"""
    client = UpstreamClient(...)
    client.timeout_config = TimeoutConfig(default_timeout_seconds=5.0)
    
    async def normal_call(*args, **kwargs):
        await asyncio.sleep(0.1)
        return {"result": "success"}
    
    client._call_tool_internal = normal_call
    result = await client.call_tool("memory_search", {"query": "test"})
    assert result == {"result": "success"}

def test_timeout_config_tool_specific():
    """Tool-specific timeout values"""
    config = TimeoutConfig(default_timeout_seconds=30.0)
    assert config.get_timeout("memory_save_url") == 40.0
    assert config.get_timeout("memory_search") == 30.0
```

- [ ] **Step 4: テスト実行と検証**

Run: `uv run pytest tests/unit/test_upstream_timeout.py -v`

Expected: All 3 tests pass, timeout handling works correctly.

- [ ] **Step 5: コミット**

```bash
git add src/mcp_gateway/upstream/timeout_client.py \
        src/mcp_gateway/upstream/context_store_client.py \
        tests/unit/test_upstream_timeout.py
git commit -m "feat(mcp_gateway): add explicit timeout to upstream tool calls

- Introduce TimeoutConfig for configurable per-tool timeouts (default 30s)
- Wrap UpstreamClient.call_tool with asyncio.wait_for to prevent hangs
- Normalize timeout errors to UpstreamError(code='UPSTREAM_TIMEOUT', recoverable=True)
- Add unit tests for timeout and normal execution paths

Addresses SPEC.md §16.5 D-1"
```

---

## Task 2: D-2 Universal Evaluator レイテンシ最適化

**Files:**
- Modify: `src/mcp_gateway/policy/llm_evaluator.py`
- Modify: `src/mcp_gateway/policy/composite.py`
- Test: `tests/unit/test_llm_evaluator_optimization.py`

Read系ツール（`memory_search`, `memory_stats` 等）の評価バイパス、評価結果のキャッシング、並列化を導入。

- [ ] **Step 1: Read系ツール識別リストの定義**

Modify `src/mcp_gateway/policy/llm_evaluator.py` to add at module level (before class definition):

```python
# Read-only tools that are safe to bypass evaluation (Tier 1 rule auto-approves)
READ_ONLY_TOOLS = {
    "memory_search",
    "memory_search_graph",
    "memory_stats",
    "memory_list_projects",  # if exists
}
```

- [ ] **Step 2: LLM評価バイパス機構の実装**

Modify `src/mcp_gateway/policy/llm_evaluator.py` around line 236:

```python
async def evaluate(self, tool_name: str, arguments: dict) -> EvaluationResult:
    """
    Evaluate tool call against LLM policy.
    
    Read-only tools bypass evaluation (safe to auto-approve).
    """
    # Bypass evaluation for read-only tools
    if tool_name in READ_ONLY_TOOLS:
        return EvaluationResult(
            approved=True,
            reasoning="Read-only tool, auto-approved by Tier 1 rules",
            confidence=1.0
        )
    
    # Check cache for non-read tools
    cache_key = self._make_cache_key(tool_name, arguments)
    cached = await self.cache.get(cache_key)
    if cached is not None:
        return cached
    
    # LLM evaluation with timeout
    try:
        result = await asyncio.wait_for(
            self._evaluate_with_llm(tool_name, arguments),
            timeout=10.0  # max 10s per evaluation
        )
    except asyncio.TimeoutError:
        # Fail-soft: deny on timeout (conservative)
        result = EvaluationResult(
            approved=False,
            reasoning="Evaluator timeout (fail-safe deny)",
            confidence=0.0
        )
    
    # Cache result with short TTL (5 min for write operations)
    await self.cache.set(cache_key, result, ttl=300)
    return result

def _make_cache_key(self, tool_name: str, arguments: dict) -> str:
    """Generate cache key for evaluation result"""
    import hashlib
    import json
    arg_str = json.dumps(arguments, sort_keys=True, default=str)
    h = hashlib.md5(arg_str.encode()).hexdigest()
    return f"eval:{tool_name}:{h}"
```

- [ ] **Step 3: Memory 取得と LLM 判定の並列化**

Modify `src/mcp_gateway/policy/llm_evaluator.py` to refactor `_evaluate_with_llm`:

```python
async def _evaluate_with_llm(
    self,
    tool_name: str,
    arguments: dict
) -> EvaluationResult:
    """Evaluate with LLM, potentially in parallel with context retrieval"""
    
    # Parallel fetch: memory context + LLM invocation
    # This avoids sequential waiting: retrieve(3s) → acompletion(10s) = 13s
    # Instead: gather(retrieve, acompletion) ≈ max(3s, 10s) = 10s
    try:
        context, decision = await asyncio.gather(
            self._retrieve_context(tool_name, arguments),
            self._get_llm_decision(tool_name, arguments),
            return_exceptions=True
        )
    except Exception as e:
        # If any parallel task fails, fall back to conservative deny
        return EvaluationResult(
            approved=False,
            reasoning=f"Evaluator error: {str(e)}",
            confidence=0.0
        )
    
    # Merge context into decision
    if isinstance(context, Exception):
        context = None
    if isinstance(decision, Exception):
        decision = None
    
    if decision is None:
        return EvaluationResult(
            approved=False,
            reasoning="LLM decision unavailable",
            confidence=0.0
        )
    
    # decision is already an EvaluationResult; augment with context
    decision.context = context
    return decision

async def _retrieve_context(
    self,
    tool_name: str,
    arguments: dict
) -> str | None:
    """Retrieve memory context for LLM evaluation (timeout: 3s)"""
    try:
        context = await asyncio.wait_for(
            self.memory_client.retrieve(
                query=arguments.get("query", ""),
                project=arguments.get("project")
            ),
            timeout=3.0
        )
        return context
    except asyncio.TimeoutError:
        return None

async def _get_llm_decision(
    self,
    tool_name: str,
    arguments: dict
) -> EvaluationResult:
    """Get LLM decision via LiteLLM (timeout: 10s)"""
    try:
        response = await asyncio.wait_for(
            litellm.acompletion(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Evaluate MCP tool safety..."
                    },
                    {
                        "role": "user",
                        "content": f"Tool: {tool_name}, Args: {arguments}"
                    }
                ],
                temperature=0,
                max_tokens=100
            ),
            timeout=10.0
        )
        # Parse response into EvaluationResult
        approved = "approved" in response.choices[0].message.content.lower()
        return EvaluationResult(
            approved=approved,
            reasoning=response.choices[0].message.content,
            confidence=0.8
        )
    except asyncio.TimeoutError:
        return None
```

- [ ] **Step 4: テスト作成**

Create `tests/unit/test_llm_evaluator_optimization.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.mcp_gateway.policy.llm_evaluator import LLMEvaluator, READ_ONLY_TOOLS

@pytest.mark.asyncio
async def test_read_only_tools_bypass_evaluation():
    """Read-only tools skip LLM evaluation"""
    evaluator = LLMEvaluator(model="gpt-4", cache=MagicMock())
    
    for tool_name in READ_ONLY_TOOLS:
        result = await evaluator.evaluate(tool_name, {"query": "test"})
        assert result.approved is True
        assert "auto-approved" in result.reasoning.lower()

@pytest.mark.asyncio
async def test_evaluation_result_cached():
    """Non-read tool evaluation results are cached"""
    evaluator = LLMEvaluator(model="gpt-4", cache=AsyncMock())
    evaluator.cache.get = AsyncMock(return_value=None)
    evaluator.cache.set = AsyncMock()
    
    # Mock LLM decision
    evaluator._evaluate_with_llm = AsyncMock(
        return_value={"approved": True, "reasoning": "safe"}
    )
    
    # First call: cache miss → evaluate → cache set
    result1 = await evaluator.evaluate("memory_save", {"content": "x"})
    assert evaluator.cache.set.called
    
    # Second call: cache hit
    evaluator.cache.get = AsyncMock(
        return_value={"approved": True, "reasoning": "cached"}
    )
    result2 = await evaluator.evaluate("memory_save", {"content": "x"})
    # Verify cache.get was called (cache hit)
    assert evaluator.cache.get.call_count == 2

@pytest.mark.asyncio
async def test_parallel_context_and_decision():
    """Memory retrieval and LLM decision run in parallel"""
    evaluator = LLMEvaluator(model="gpt-4", cache=AsyncMock())
    evaluator.cache.get = AsyncMock(return_value=None)
    evaluator.cache.set = AsyncMock()
    
    import time
    
    async def slow_retrieve(*args, **kwargs):
        await asyncio.sleep(0.5)
        return "context data"
    
    async def slow_llm(*args, **kwargs):
        await asyncio.sleep(0.5)
        return {"approved": True, "reasoning": "ok"}
    
    evaluator._retrieve_context = slow_retrieve
    evaluator._get_llm_decision = slow_llm
    
    start = time.time()
    result = await evaluator.evaluate("memory_save", {"content": "test"})
    elapsed = time.time() - start
    
    # With gather, total time ≈ max(0.5, 0.5) = 0.5s, not 1.0s
    assert elapsed < 0.9, f"Expected parallel (~0.5s), got {elapsed}s"
```

- [ ] **Step 5: テスト実行**

Run: `uv run pytest tests/unit/test_llm_evaluator_optimization.py -v`

Expected: All tests pass, parallel execution verified.

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/policy/llm_evaluator.py \
        tests/unit/test_llm_evaluator_optimization.py
git commit -m "feat(mcp_gateway): optimize LLM evaluator latency (D-2)

- Bypass LLM evaluation for read-only tools (memory_search, memory_stats)
- Add short-TTL caching (5 min) for evaluation results
- Parallelize memory context retrieval and LLM decision via asyncio.gather
- Reduce evaluation latency from 13s (sequential) to ~10s (parallel)
- Add timeout handling (3s context, 10s LLM) with fail-soft deny

Addresses SPEC.md §16.5 D-2"
```

---

## Task 3: D-3 承認モードのタイムアウト調整とバイパス分類

**Files:**
- Modify: `src/mcp_gateway/policy/intents.yaml`
- Modify: `src/mcp_gateway/server.py`
- Test: Integration test (optional for Phase 2)

承認バイパス対象ツール分類と可変タイムアウト実装。

- [ ] **Step 1: intents.yaml に承認バイパス分類を追加**

Modify `src/mcp_gateway/policy/intents.yaml` to add approval_required flag:

```yaml
intents:
  - name: memory_search
    category: read
    approval_required: false  # ← Read-only, safe
    description: "Search memory"
  
  - name: memory_stats
    category: read
    approval_required: false
    description: "Get memory statistics"
  
  - name: memory_save
    category: write
    approval_required: true   # ← Requires approval
    description: "Save new memory"
  
  - name: memory_delete
    category: write
    approval_required: true   # ← High-risk, requires approval
    description: "Delete memory"
```

- [ ] **Step 2: サーバーの承認タイムアウト可変化**

Modify `src/mcp_gateway/server.py` around line 448-518:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ApprovalPolicy:
    """Approval timing and timeout configuration"""
    approval_timeout_seconds: float = 30.0
    requires_approval_tools: set[str] = None
    bypass_approval_tools: set[str] = None
    
    def __post_init__(self):
        if self.requires_approval_tools is None:
            self.requires_approval_tools = {
                "memory_save",
                "memory_delete",
                "memory_save_url",
            }
        if self.bypass_approval_tools is None:
            self.bypass_approval_tools = {
                "memory_search",
                "memory_stats",
                "memory_search_graph",
            }
    
    def needs_approval(self, tool_name: str) -> bool:
        """Check if tool requires user approval"""
        if tool_name in self.bypass_approval_tools:
            return False
        if tool_name in self.requires_approval_tools:
            return True
        # Default: require approval for unknown tools (conservative)
        return True

class ChronosServer:
    def __init__(self, ...):
        # Load approval config from env or intents.yaml
        self.approval_policy = ApprovalPolicy(
            approval_timeout_seconds=float(
                os.getenv("APPROVAL_TIMEOUT_SECONDS", "30.0")
            )
        )
    
    async def handle_tool_call(
        self,
        tool_name: str,
        arguments: dict
    ) -> Any:
        """Handle MCP tool call with approval gate"""
        
        # Check if approval is needed
        if not self.approval_policy.needs_approval(tool_name):
            # Skip approval for read-only tools
            return await self.execute_tool(tool_name, arguments)
        
        # Require approval for write tools (with timeout)
        try:
            approved = await asyncio.wait_for(
                self.request_user_approval(tool_name, arguments),
                timeout=self.approval_policy.approval_timeout_seconds
            )
        except asyncio.TimeoutError:
            raise ApprovalError(
                code="APPROVAL_TIMEOUT",
                message=f"User approval timeout for {tool_name}",
                recoverable=True  # User can retry
            )
        
        if not approved:
            raise ApprovalError(
                code="APPROVAL_DENIED",
                message=f"User denied {tool_name}",
                recoverable=False
            )
        
        return await self.execute_tool(tool_name, arguments)
```

- [ ] **Step 3: テスト（簡易版）**

Modify or create integration test snippet in existing test file:

```python
@pytest.mark.asyncio
async def test_approval_bypassed_for_read_tools():
    """Read tools don't require approval"""
    server = ChronosServer(...)
    
    # Mock execute_tool to verify it's called without approval gate
    server.execute_tool = AsyncMock(return_value={"results": []})
    
    result = await server.handle_tool_call("memory_search", {"query": "test"})
    assert server.execute_tool.called
    # No approval request should have been made

@pytest.mark.asyncio
async def test_approval_required_for_write_tools():
    """Write tools require approval"""
    server = ChronosServer(...)
    server.request_user_approval = AsyncMock(return_value=True)
    server.execute_tool = AsyncMock(return_value={"id": "123"})
    
    result = await server.handle_tool_call("memory_save", {"content": "x"})
    assert server.request_user_approval.called
    assert server.execute_tool.called
```

- [ ] **Step 4: コミット**

```bash
git add src/mcp_gateway/policy/intents.yaml \
        src/mcp_gateway/server.py \
        tests/integration/test_approval_policy.py  # if created
git commit -m "feat(mcp_gateway): configurable approval timeout and read-tool bypass (D-3)

- Introduce ApprovalPolicy for fine-grained approval control
- Bypass approval for read-only tools (memory_search, memory_stats, etc.)
- Make approval timeout configurable via APPROVAL_TIMEOUT_SECONDS env var
- Default timeout remains 30s, configurable per environment
- Add integration tests for approval bypass logic

Addresses SPEC.md §16.5 D-3"
```

---

## Task 4: E-1 Ingestion Pipeline チャンク並列化

**Files:**
- Modify: `src/context_store/ingestion/pipeline.py`
- Test: `tests/unit/test_ingestion_parallel.py`

`_process_chunk` を並列化し、graph_enabled=false時のスループット向上。

- [ ] **Step 1: 並列化設定の追加**

Modify `src/context_store/ingestion/pipeline.py` to add constants near class definition:

```python
import asyncio
from typing import Optional

# Configuration for chunk processing parallelism
CHUNK_PARALLEL_SEMAPHORE_SIZE = 10  # Max concurrent chunk processing
CHUNK_PARALLEL_ENABLED_WITHOUT_GRAPH = True  # Enable parallel when graph disabled
```

- [ ] **Step 2: IngestionPipeline クラスへ Semaphore 追加**

Modify `src/context_store/ingestion/pipeline.py` in `__init__`:

```python
class IngestionPipeline:
    def __init__(self, ...):
        # ... existing code ...
        self.chunk_semaphore = asyncio.Semaphore(
            CHUNK_PARALLEL_SEMAPHORE_SIZE
        )
```

- [ ] **Step 3: _process_chunk 並列化実装**

Modify `src/context_store/ingestion/pipeline.py` around line 218-263:

```python
async def process_chunks(
    self,
    chunks: list[RawContent],
    source_metadata: dict
) -> list[Memory]:
    """
    Process list of chunks into memories.
    
    If graph is disabled, chunks are processed in parallel.
    If graph is enabled, sequential order is preserved for CHUNK_NEXT/PREV edges.
    """
    
    if self.storage.graph_enabled and CHUNK_PARALLEL_ENABLED_WITHOUT_GRAPH:
        # Sequential processing: preserve chunk order for graph edges
        results = []
        for chunk in chunks:
            memory = await self._process_chunk(chunk, source_metadata)
            results.append(memory)
        return results
    else:
        # Parallel processing: graph disabled, no ordering constraint
        async def process_with_limit(chunk):
            async with self.chunk_semaphore:
                return await self._process_chunk(chunk, source_metadata)
        
        results = await asyncio.gather(
            *[process_with_limit(chunk) for chunk in chunks],
            return_exceptions=False
        )
        return results

async def _process_chunk(
    self,
    chunk: RawContent,
    source_metadata: dict
) -> Memory:
    """
    Process single chunk:
    1. Classify
    2. Embed (already batched upstream, this is lookup)
    3. Store
    4. Link graph edges
    """
    # Classification
    memory_type = self.classifier.classify(chunk.content)
    
    # Embedding (already done in batch, retrieve here if needed)
    # For simplicity: assume embedding was done in parent method
    embedding = chunk.embedding  # passed from parent
    
    # Create Memory object
    memory = Memory(
        content=chunk.content,
        memory_type=memory_type,
        source_type=source_metadata.get("source_type"),
        source_metadata=source_metadata,
        embedding=embedding,
        importance_score=chunk.importance_score or 0.5
    )
    
    # Save to storage
    memory_id = await self.storage.save_memory(memory)
    memory.id = memory_id
    
    # (Graph linking is handled separately by GraphLinker, not here)
    
    return memory
```

- [ ] **Step 4: テスト作成**

Create `tests/unit/test_ingestion_parallel.py`:

```python
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock
from src.context_store.ingestion.pipeline import IngestionPipeline

@pytest.mark.asyncio
async def test_chunk_processing_sequential_with_graph():
    """Chunks are processed sequentially when graph is enabled"""
    pipeline = IngestionPipeline(...)
    pipeline.storage.graph_enabled = True
    
    # Mock slow _process_chunk
    call_times = []
    async def slow_process(chunk, metadata):
        call_times.append(asyncio.current_time())
        await asyncio.sleep(0.1)
        return MagicMock(id=chunk.id)
    
    pipeline._process_chunk = slow_process
    
    chunks = [MagicMock(id=f"c{i}", content=f"chunk{i}") for i in range(3)]
    
    start = time.time()
    results = await pipeline.process_chunks(chunks, {})
    elapsed = time.time() - start
    
    # Sequential: 3 × 0.1s = 0.3s
    assert elapsed >= 0.3, f"Expected sequential (~0.3s), got {elapsed}s"
    assert len(results) == 3

@pytest.mark.asyncio
async def test_chunk_processing_parallel_without_graph():
    """Chunks are processed in parallel when graph is disabled"""
    pipeline = IngestionPipeline(...)
    pipeline.storage.graph_enabled = False
    
    call_times = []
    
    async def slow_process(chunk, metadata):
        call_times.append(time.time())
        await asyncio.sleep(0.1)
        return MagicMock(id=chunk.id)
    
    pipeline._process_chunk = slow_process
    
    chunks = [MagicMock(id=f"c{i}", content=f"chunk{i}") for i in range(3)]
    
    start = time.time()
    results = await pipeline.process_chunks(chunks, {})
    elapsed = time.time() - start
    
    # Parallel (semaphore=10): 3 × 0.1s concurrently ≈ 0.1s
    assert elapsed < 0.25, f"Expected parallel (~0.1s), got {elapsed}s"
    assert len(results) == 3

@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Semaphore limits concurrent chunk processing"""
    pipeline = IngestionPipeline(...)
    pipeline.storage.graph_enabled = False
    pipeline.chunk_semaphore = asyncio.Semaphore(2)  # Only 2 concurrent
    
    concurrent_count = 0
    max_concurrent = 0
    
    async def track_concurrent(chunk, metadata):
        nonlocal concurrent_count, max_concurrent
        concurrent_count += 1
        max_concurrent = max(max_concurrent, concurrent_count)
        await asyncio.sleep(0.1)
        concurrent_count -= 1
        return MagicMock(id=chunk.id)
    
    pipeline._process_chunk = track_concurrent
    
    chunks = [MagicMock(id=f"c{i}") for i in range(5)]
    results = await pipeline.process_chunks(chunks, {})
    
    # With semaphore=2, max concurrent should be 2
    assert max_concurrent <= 2, f"Exceeded semaphore limit: {max_concurrent}"
```

- [ ] **Step 5: テスト実行**

Run: `uv run pytest tests/unit/test_ingestion_parallel.py -v`

Expected: All tests pass.

- [ ] **Step 6: コミット**

```bash
git add src/context_store/ingestion/pipeline.py \
        tests/unit/test_ingestion_parallel.py
git commit -m "feat(ingestion): parallelize chunk processing when graph disabled (E-1)

- Add asyncio.Semaphore-based chunk processing parallelization
- Sequential mode (10 chunks/sec): preserves CHUNK_NEXT/PREV order for graph
- Parallel mode: enables concurrent processing for Supabase (graph_enabled=false)
- Configurable semaphore size (default 10) to prevent resource exhaustion
- Improve throughput for large batch ingestion via session_flush

Addresses SPEC.md §16.5 E-1"
```

---

## Task 5: E-2 OpenAI / LiteLLM 埋め込みリトライ調整

**Files:**
- Create: `src/context_store/embedding/retry_config.py`
- Modify: `src/context_store/embedding/openai.py`
- Modify: `src/context_store/embedding/litellm.py`
- Test: `tests/unit/test_embedding_retry.py`

リトライ戦略統一、`Retry-After` 尊重、タイムアウト短縮。

- [ ] **Step 1: 統一リトライ設定モジュール作成**

Create `src/context_store/embedding/retry_config.py`:

```python
from dataclasses import dataclass
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
import httpx

@dataclass
class EmbeddingRetryPolicy:
    """Unified retry policy for embedding providers"""
    max_attempts: int = 3  # Reduced from 5
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 10.0  # Reduced from 60
    per_attempt_timeout_seconds: float = 10.0
    
    def get_retry_decorator(self):
        """
        Build tenacity retry decorator for embedding calls.
        
        Strategy:
        - Max 3 attempts (reduced from 5)
        - Exponential backoff: 1s → 2s → 4s (max 10s)
        - Fails fast on client errors (4xx)
        - Retries on server/timeout errors (5xx, TimeoutError)
        """
        return retry(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(
                multiplier=1,
                min=self.min_wait_seconds,
                max=self.max_wait_seconds
            ),
            retry=retry_if_exception_type(
                (httpx.HTTPError, TimeoutError)
            ),
            reraise=True
        )

def parse_retry_after_header(retry_after_header: str | None) -> float | None:
    """
    Parse Retry-After header from API response.
    
    Supports both:
    - Decimal-integer (seconds): "120"
    - HTTP-date: "Fri, 31 Dec 1999 23:59:59 GMT"
    
    Returns delay in seconds, or None if unparseable.
    """
    if not retry_after_header:
        return None
    
    try:
        # Try parsing as integer (seconds)
        return float(retry_after_header)
    except ValueError:
        pass
    
    # Try parsing as HTTP-date (RFC 2822)
    from email.utils import parsedate_to_datetime
    try:
        target_time = parsedate_to_datetime(retry_after_header)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        delay = (target_time - now).total_seconds()
        return max(delay, 0)  # Ensure non-negative
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 2: OpenAI プロバイダ更新**

Modify `src/context_store/embedding/openai.py` around line 101-117:

```python
from .retry_config import EmbeddingRetryPolicy, parse_retry_after_header
import asyncio
import httpx

class OpenAIEmbeddingProvider:
    def __init__(self, ...):
        # ... existing code ...
        self.retry_policy = EmbeddingRetryPolicy(
            max_attempts=int(os.getenv("EMBEDDING_MAX_RETRIES", "3")),
            max_wait_seconds=float(os.getenv("EMBEDDING_MAX_WAIT", "10.0")),
        )
    
    @self.retry_policy.get_retry_decorator()
    async def _embed_batch_single_attempt(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Single attempt at embedding batch (wrapped by retry decorator)"""
        timeout = httpx.Timeout(
            self.retry_policy.per_attempt_timeout_seconds
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                json={"input": texts, "model": self.model},
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
            
            # Handle rate limiting with Retry-After
            if response.status_code == 429:
                retry_after = parse_retry_after_header(
                    response.headers.get("Retry-After")
                )
                if retry_after:
                    # Wait before retry (tenacity will handle the retry)
                    await asyncio.sleep(retry_after)
                raise httpx.HTTPError(f"Rate limited: {response.status_code}")
            
            response.raise_for_status()
            data = response.json()
            return [item["embedding"] for item in data["data"]]
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed batch with automatic retry and Retry-After support"""
        try:
            return await self._embed_batch_single_attempt(texts)
        except Exception as e:
            # Final failure after retries
            raise EmbeddingError(
                code="EMBEDDING_FAILED",
                message=f"Failed to embed after {self.retry_policy.max_attempts} attempts: {str(e)}",
                recoverable=False  # Client should handle
            ) from e
```

- [ ] **Step 3: LiteLLM プロバイダ更新**

Modify `src/context_store/embedding/litellm.py` around line 107-117:

```python
from .retry_config import EmbeddingRetryPolicy, parse_retry_after_header
import asyncio

class LiteLLMEmbeddingProvider:
    def __init__(self, ...):
        # ... existing code ...
        self.retry_policy = EmbeddingRetryPolicy(
            max_attempts=int(os.getenv("EMBEDDING_MAX_RETRIES", "3")),
            max_wait_seconds=float(os.getenv("EMBEDDING_MAX_WAIT", "10.0")),
        )
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed batch using LiteLLM with retry policy.
        
        LiteLLM internally handles retries, but we wrap with timeout
        and Retry-After respect to cap total latency.
        """
        retry_decorator = self.retry_policy.get_retry_decorator()
        
        @retry_decorator
        async def attempt():
            try:
                # LiteLLM async embedding with per-attempt timeout
                response = await asyncio.wait_for(
                    litellm.aembedding(
                        model=self.model,
                        input=texts,
                        api_key=self.api_key
                    ),
                    timeout=self.retry_policy.per_attempt_timeout_seconds
                )
                return response["data"]  # List of {"embedding": [...]}
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"LiteLLM embedding timeout after "
                    f"{self.retry_policy.per_attempt_timeout_seconds}s"
                )
        
        try:
            embeddings = await attempt()
            return [item["embedding"] for item in embeddings]
        except Exception as e:
            raise EmbeddingError(
                code="EMBEDDING_FAILED",
                message=f"Failed to embed after {self.retry_policy.max_attempts} attempts: {str(e)}",
                recoverable=False
            ) from e
```

- [ ] **Step 4: テスト作成**

Create `tests/unit/test_embedding_retry.py`:

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.context_store.embedding.retry_config import (
    EmbeddingRetryPolicy,
    parse_retry_after_header
)

def test_retry_policy_defaults():
    """RetryPolicy has sane defaults"""
    policy = EmbeddingRetryPolicy()
    assert policy.max_attempts == 3
    assert policy.max_wait_seconds == 10.0
    assert policy.per_attempt_timeout_seconds == 10.0

def test_parse_retry_after_seconds():
    """Parse Retry-After as integer seconds"""
    delay = parse_retry_after_header("120")
    assert delay == 120.0

def test_parse_retry_after_http_date():
    """Parse Retry-After as HTTP-date"""
    # This is a future date, should parse and give positive delay
    from email.utils import formatdate
    future = "Fri, 31 Dec 2099 23:59:59 GMT"
    delay = parse_retry_after_header(future)
    assert delay is not None
    assert delay > 0

def test_parse_retry_after_invalid():
    """Invalid Retry-After returns None"""
    assert parse_retry_after_header("invalid") is None
    assert parse_retry_after_header(None) is None

@pytest.mark.asyncio
async def test_embedding_retry_exponential_backoff():
    """Retry decorator implements exponential backoff"""
    from src.context_store.embedding.openai import OpenAIEmbeddingProvider
    
    provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
    provider.retry_policy = EmbeddingRetryPolicy(
        max_attempts=3,
        min_wait_seconds=0.1,
        max_wait_seconds=0.5
    )
    
    # Track attempt timing
    attempt_times = []
    
    async def failing_attempt():
        attempt_times.append(asyncio.get_event_loop().time())
        if len(attempt_times) < 3:
            raise ValueError("Simulated failure")
        return [[0.1, 0.2, 0.3]]
    
    provider._embed_batch_single_attempt = provider.retry_policy.get_retry_decorator()(
        failing_attempt
    )
    
    result = await provider._embed_batch_single_attempt(["test"])
    
    # Should have 3 attempts (2 failures + 1 success)
    assert len(attempt_times) == 3
    
    # Check backoff: 0.1s, then 0.2s (or more)
    if len(attempt_times) > 1:
        backoff1 = attempt_times[1] - attempt_times[0]
        assert backoff1 >= 0.1, f"First backoff too short: {backoff1}s"

@pytest.mark.asyncio
async def test_embedding_respects_per_attempt_timeout():
    """Each embedding attempt respects per-attempt timeout"""
    from src.context_store.embedding.openai import OpenAIEmbeddingProvider
    
    provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
    provider.retry_policy = EmbeddingRetryPolicy(
        per_attempt_timeout_seconds=0.1
    )
    
    async def slow_embed(*args, **kwargs):
        await asyncio.sleep(1.0)  # Slower than timeout
        return [[0.1, 0.2]]
    
    provider._embed_batch_single_attempt = slow_embed
    
    from src.context_store.embedding.openai import EmbeddingError
    
    # Should timeout and fail after retries
    with pytest.raises(EmbeddingError) as exc_info:
        await provider.embed_batch(["test"])
    
    assert "Failed to embed" in str(exc_info.value)
```

- [ ] **Step 5: テスト実行**

Run: `uv run pytest tests/unit/test_embedding_retry.py -v`

Expected: All tests pass.

- [ ] **Step 6: コミット**

```bash
git add src/context_store/embedding/retry_config.py \
        src/context_store/embedding/openai.py \
        src/context_store/embedding/litellm.py \
        tests/unit/test_embedding_retry.py
git commit -m "feat(embedding): optimize retry strategy and per-attempt timeout (E-2)

- Reduce max retry attempts from 5 to 3, max backoff from 60s to 10s
- Add per-attempt timeout enforcement (10s) to cap total embedding latency
- Parse and respect Retry-After HTTP header for rate limiting
- Unified EmbeddingRetryPolicy for OpenAI and LiteLLM providers
- Fail fast on client errors (4xx), retry on server/timeout (5xx)
- Prevent embedding backend issues from blocking MCP for >30s

Addresses SPEC.md §16.5 E-2"
```

---

## Task 6: 統合テストと検証

**Files:**
- Test: `tests/integration/test_phase2_timeout_integration.py` (optional)

各改善項目の統合動作確認。

- [ ] **Step 1: 統合テスト作成（オプション）**

Create `tests/integration/test_phase2_timeout_integration.py` (簡易版):

```python
import pytest
import asyncio
from unittest.mock import AsyncMock
from src.mcp_gateway.upstream.context_store_client import UpstreamClient
from src.mcp_gateway.policy.llm_evaluator import LLMEvaluator
from src.context_store.ingestion.pipeline import IngestionPipeline

@pytest.mark.asyncio
async def test_timeout_improvements_reduce_latency():
    """
    Integration test: All improvements combined reduce end-to-end latency.
    
    Scenario: Complex memory save with approval + ingestion
    - D-1: Upstream timeout bounds network issues
    - D-2: Parallel LLM + context reduces evaluation from 13s to ~10s
    - D-3: Read tools bypass approval
    - E-1: Parallel chunk processing
    - E-2: Faster retries
    """
    # This is a high-level integration test; can be expanded post-implementation
    assert True  # Placeholder; implement based on actual setup
```

- [ ] **Step 2: 既存テストスイート実行**

Run: `uv run pytest tests/unit/ -v --tb=short`

Expected: All Phase 2 tests pass, no regressions.

- [ ] **Step 3: コミット（テスト）** （あれば）

```bash
git add tests/integration/test_phase2_timeout_integration.py
git commit -m "test(integration): add phase 2 timeout improvement integration test"
```

---

## Task 7: ドキュメント更新

**Files:**
- Modify: `README.md` (Configuration section)
- Modify: `docs/deployment-guide.md` (if exists)

環境変数とコンフィグの新規ドキュメント。

- [ ] **Step 1: README Configuration セクション更新**

Modify `README.md` Configuration section to add:

```markdown
### Phase 2: Timeout & Latency Optimizations (env vars)

| Env Var | Default | Description |
|---------|---------|-------------|
| `MCP_TOOL_TIMEOUT_SECONDS` | `30.0` | Upstream tool call timeout (D-1) |
| `APPROVAL_TIMEOUT_SECONDS` | `30.0` | User approval wait timeout (D-3) |
| `EMBEDDING_MAX_RETRIES` | `3` | Max embedding API retry attempts (E-2) |
| `EMBEDDING_MAX_WAIT` | `10.0` | Max wait between embedding retries (E-2) |
```

- [ ] **Step 2: コミット**

```bash
git add README.md
git commit -m "docs: add Phase 2 timeout configuration documentation"
```

---

## Summary

**改善項目カバレッジ:**

| ID | 項目 | Status | タスク |
|----|------|--------|--------|
| D-1 | Upstream タイムアウト | ✅ | Task 1 |
| D-2 | LLM Evaluator 並列化 | ✅ | Task 2 |
| D-3 | 承認 timeout + bypass | ✅ | Task 3 |
| E-1 | Chunk 並列化 | ✅ | Task 4 |
| E-2 | 埋め込みリトライ調整 | ✅ | Task 5 |
| E-3 | Supabase keyword 最適化 | 📋 | Phase 2b（低優先度） |
| E-4 | GraphLinker 重複呼び出し解消 | 📋 | Phase 2b（低優先度） |
| E-5 | Orchestrator RPC 統合 | 📋 | Phase 2b（低優先度） |
| E-6 | InMemory Cache cold-start | 📋 | Phase 2b（低優先度） |
| E-7 | ローカルモデル eager preload | 📋 | Phase 2c（中優先度） |

**High/Medium優先度の5項目を実装、Low優先度3項目は Phase 2b 以降へ。**

---

計画完成しました！📋

**実行方法:**
- **推奨**: `superpowers:subagent-driven-development` を使い、各タスクを独立したサブエージェントで実行
- **代替**: このセッションで `superpowers:executing-plans` を用いてインライン実行

どちらご希望ですか？