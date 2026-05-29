"""Phase 2 timeout improvements end-to-end integration tests.

各テストは Phase 2 で導入された 2 つ以上のコンポーネントを実際に結線して検証する:

- **D-1**: ``UpstreamClient`` + ``asyncio.wait_for`` + ``UpstreamError`` 正規化
- **D-2**: ``CompositeEvaluator`` + ``PolicyEngine`` + ``READ_ONLY_TOOLS`` バイパス
- **E-1**: ``IngestionPipeline`` + ``asyncio.Semaphore`` + ``asyncio.gather`` (graph=None 分岐)
- **E-2**: ``OpenAIEmbeddingProvider`` + ``EmbeddingRetryPolicy`` + ``AsyncRetrying`` + ``httpx``

外部サービス (Docker / Postgres / network) は不要。``httpx.MockTransport`` /
``unittest.mock`` で境界をスタブし、内部のコンポーネントは実装を実行する。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from context_store.config import Settings
from context_store.embedding.openai import OpenAIEmbeddingProvider
from context_store.embedding.retry_config import EmbeddingRetryPolicy
from context_store.ingestion.pipeline import IngestionPipeline
from context_store.models.memory import Memory, ScoredMemory, SourceType
from context_store.storage.protocols import StorageAdapter
from mcp_gateway.errors import UpstreamError
from mcp_gateway.policy.composite import CompositeEvaluator
from mcp_gateway.policy.engine import PolicyEngine
from mcp_gateway.policy.models import (
    AgentPolicy,
    GatewayPolicy,
    IntentPolicy,
    OutputFilterDef,
)
from mcp_gateway.policy.models_evaluator import Decision, ToolCallInput
from mcp_gateway.upstream.context_store_client import UpstreamClient
from mcp_gateway.upstream.timeout_client import TimeoutConfig

# =============================================================================
# Helpers
# =============================================================================


def _make_settings(max_tokens_per_chunk: int = 1000) -> Settings:
    """テスト用 Settings インスタンス。chunker サイズを調整可能。"""
    from pydantic import SecretStr

    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        storage_backend="sqlite",
        graph_enabled=False,
        cache_backend="inmemory",
        sqlite_db_path=":memory:",
        sqlite_max_concurrent_connections=5,
        sqlite_max_queued_requests=20,
        sqlite_acquire_timeout=2.0,
        stale_lock_timeout_seconds=600,
        graph_max_logical_depth=5,
        graph_max_physical_hops=50,
        graph_traversal_timeout_seconds=2.0,
        cache_coherence_poll_interval_seconds=5.0,
        postgres_host="localhost",
        postgres_password="test",
        postgres_port=5435,
        postgres_user="postgres",
        postgres_db="testdb",
        redis_url="redis://localhost:6379",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="test",
        embedding_provider="openai",
        openai_api_key=SecretStr("sk-test"),
        local_model_name="cl-nagoya/ruri-v3-310m",
        litellm_api_base="http://localhost:4000",
        custom_api_endpoint="http://localhost:8080/embed",
        supabase_url="https://example.supabase.co",
        supabase_key="test-service-role-key",
        max_tokens_per_chunk=max_tokens_per_chunk,
        chars_per_token=3,
    )


def _make_mock_storage_with_save_delay(delay_seconds: float) -> StorageAdapter:
    """``save_memory`` に遅延を入れたモック storage。並列度測定に使用。"""
    storage = MagicMock(spec=StorageAdapter)
    saved_memories: list[Memory] = []

    async def save_memory(memory: Memory) -> str:
        await asyncio.sleep(delay_seconds)
        mid = str(uuid4())
        persisted = memory.model_copy(update={"id": mid})
        saved_memories.append(persisted)
        return mid

    async def vector_search(
        embedding: list[float],
        top_k: int,
        project: str | None = None,
        filters: Any = None,
    ) -> list[ScoredMemory]:
        # 重複検出をスキップさせるため空を返す
        return []

    storage.save_memory = AsyncMock(side_effect=save_memory)
    storage.vector_search = AsyncMock(side_effect=vector_search)
    storage.list_by_filter = AsyncMock(return_value=[])
    storage.update_memory = AsyncMock(return_value=True)
    return storage


def _make_mock_embedding_provider_no_delay() -> Any:
    """並列度測定用: 遅延なしの軽量 embedding provider。"""
    provider = MagicMock()
    provider.dimension = 4

    async def embed(text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    async def embed_batch(texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    provider.embed = embed
    provider.embed_batch = embed_batch
    return provider


def _build_minimal_policy() -> GatewayPolicy:
    """READ_ONLY_TOOLS バイパス検証用の最小ポリシー。"""
    return GatewayPolicy(
        version=1,
        output_filters={"rs": OutputFilterDef(type="none")},
        intents={
            "default": IntentPolicy(
                description="default intent",
                allowed_tools=["memory_search", "memory_save"],
                output_filter="rs",
            ),
        },
        agents={
            "claude-code": AgentPolicy(allowed_intents=["default"]),
        },
    )


# =============================================================================
# E-2: Embedding retry end-to-end via httpx layer
# =============================================================================


class TestE2EmbeddingRetryEndToEnd:
    """``OpenAIEmbeddingProvider`` のリトライが httpx 層まで結線されている検証。"""

    @pytest.mark.asyncio
    async def test_provider_recovers_from_transient_429_within_bounded_time(self) -> None:
        """429 一時エラー後 200 で復帰、合計時間が境界内であることを検証。"""
        call_count = 0
        success_payload = {
            "data": [{"embedding": [0.1] * 1536, "index": 0}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"error": "rate limit"},
                )
            return httpx.Response(200, json=success_payload)

        retry_policy = EmbeddingRetryPolicy(
            max_attempts=3,
            min_wait_seconds=0.01,
            max_wait_seconds=0.1,
            per_attempt_timeout_seconds=2.0,
        )
        # 内部 httpx クライアントを MockTransport 付きで DI する (Issue 2 修正)
        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test",
            model="text-embedding-3-small",
            retry_policy=retry_policy,
            http_client=mock_client,
        )

        try:
            start = time.monotonic()
            embeddings = await provider.embed_batch(["hello"])
            elapsed = time.monotonic() - start
        finally:
            await provider.close()

        # 1 回目 429 → 2 回目 200 の合計 2 リクエスト
        assert call_count == 2
        # 復帰したベクトルが返る
        assert len(embeddings) == 1
        assert len(embeddings[0]) == 1536
        # 合計時間境界: per_attempt 2.0s + max_wait 0.1s x (max_attempts-1) = 2.2s 上限。
        # 実環境では Retry-After=0 + 軽量モックなので 0.5s 未満で完了する。
        assert elapsed < 1.5, f"Recovery should complete quickly, took {elapsed}s"

    @pytest.mark.asyncio
    async def test_provider_fails_within_bounded_time_on_persistent_500(self) -> None:
        """永続的な 500 エラーで max_attempts 試行後に bounded time で失敗。"""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, json={"error": "internal"})

        retry_policy = EmbeddingRetryPolicy(
            max_attempts=3,
            min_wait_seconds=0.01,
            max_wait_seconds=0.05,
            per_attempt_timeout_seconds=2.0,
        )
        # 内部 httpx クライアントを MockTransport 付きで DI する (Issue 2 修正)
        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test",
            model="text-embedding-3-small",
            retry_policy=retry_policy,
            http_client=mock_client,
        )

        try:
            start = time.monotonic()
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await provider.embed_batch(["hello"])
            elapsed = time.monotonic() - start
        finally:
            await provider.close()

        # max_attempts=3 で 3 回試行
        assert call_count == 3
        # reraise=True なので生の HTTPStatusError が伝搬する
        assert exc_info.value.response.status_code == 500
        # 上限: max_wait=0.05 x 2 (attempts-1) + 各試行軽量 ≈ 0.5s 未満
        assert elapsed < 1.0, f"Failure should be bounded, took {elapsed}s"


# =============================================================================
# E-1: Chunk parallel processing via IngestionPipeline (graph=None)
# =============================================================================


class TestE1ChunkParallelIngestion:
    """``IngestionPipeline`` が graph=None で実際に並列化することの検証。"""

    @pytest.mark.asyncio
    async def test_parallel_mode_completes_faster_than_sequential_baseline(self) -> None:
        """5 チャンクの save_memory 100ms x 5 が並列実行で 1 シーケンシャル分以下に収まる。"""
        per_save_delay = 0.1  # 100ms
        chunks_target = 5

        storage = _make_mock_storage_with_save_delay(per_save_delay)
        embedding_provider = _make_mock_embedding_provider_no_delay()
        # max_tokens_per_chunk=10, chars_per_token=3 → max_chars=30
        # 約 200 文字を入れて 5+ チャンクに分割させる
        settings = _make_settings(max_tokens_per_chunk=10)

        pipeline = IngestionPipeline(
            storage=storage,
            graph=None,  # parallel 分岐をトリガー
            embedding_provider=embedding_provider,
            settings=settings,
        )

        # チャンカーが分割しやすいよう段落区切りで多めに用意
        long_source = "\n\n".join(f"段落 {i}: " + "あ" * 25 for i in range(chunks_target))

        start = time.monotonic()
        results = await pipeline.ingest(long_source, source_type=SourceType.MANUAL)
        elapsed = time.monotonic() - start

        # 期待: 5 チャンク前後が処理される
        assert len(results) >= chunks_target, (
            f"Expected >= {chunks_target} chunks, got {len(results)}"
        )

        # 並列実行: per_save_delay x チャンク数 が逐次想定。並列ならこの程度で済むはず。
        # CI 環境の負荷を考慮し、閾値を 0.8 に緩和 (Issue 1 修正)
        sequential_estimate = per_save_delay * len(results)
        assert elapsed < sequential_estimate * 0.8, (
            f"Parallel ingestion took {elapsed:.3f}s, "
            f"expected < {sequential_estimate * 0.8:.3f}s "
            f"(sequential baseline {sequential_estimate:.3f}s)"
        )


# =============================================================================
# D-1: Upstream timeout normalization
# =============================================================================


class TestD1UpstreamTimeoutNormalization:
    """``UpstreamClient.call_tool`` がハング時 ``UpstreamError`` に正規化されることを検証。"""

    @pytest.mark.asyncio
    async def test_hanging_upstream_normalizes_to_upstream_timeout_error(self) -> None:
        """ClientSession ハングを asyncio.wait_for で打ち切り UpstreamError に正規化。"""
        timeout_config = TimeoutConfig(
            default_timeout_seconds=0.1,  # 100ms
            max_timeout_seconds=300.0,
        )
        client = UpstreamClient(
            command=["dummy"],
            env={},
            timeout_config=timeout_config,
        )

        # 開始済みセッションをスタブして start() の stdio 起動を回避
        mock_session = AsyncMock()

        async def hang(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(10.0)  # asyncio.wait_for にキャンセルされる

        mock_session.call_tool = hang
        client._session = mock_session
        client._started = True

        try:
            start = time.monotonic()
            with pytest.raises(UpstreamError) as exc_info:
                await client.call_tool("any_tool", {"q": 1})
            elapsed = time.monotonic() - start
        finally:
            await client.stop()  # クリーンアップ (Issue 3 修正)

        # タイムアウト正規化を検証
        assert exc_info.value.code == "UPSTREAM_TIMEOUT"
        assert exc_info.value.recoverable is True
        # default_timeout=0.1s に従って早期に切り上げられる
        assert elapsed < 1.0, f"Timeout should fire within 1s, took {elapsed}s"
        assert "any_tool" in str(exc_info.value)


# =============================================================================
# D-2: Read-only tool LLM bypass
# =============================================================================


class TestD2ReadOnlyToolBypass:
    """``CompositeEvaluator`` が READ_ONLY_TOOLS について LLM 呼び出しをスキップする検証。"""

    @pytest.mark.asyncio
    async def test_read_only_tool_returns_allow_without_invoking_llm(self) -> None:
        """``memory_search`` は Tier-1 ALLOW 後すぐ allow 、LLM/memory は呼ばれない。"""
        engine = PolicyEngine(_build_minimal_policy())

        mock_llm = MagicMock()
        mock_llm.judge = AsyncMock(
            return_value=Decision(decision="allow", reason="should not be called"),
        )
        mock_memory = MagicMock()
        mock_memory.retrieve = AsyncMock(return_value=[])

        evaluator = CompositeEvaluator(
            engine=engine,
            memory_client=mock_memory,
            llm_evaluator=mock_llm,
            default_intent="default",
            default_agent_id="claude-code",
            evaluation_cache_ttl_seconds=300.0,
            memory_timeout_seconds=3.0,
        )

        # READ_ONLY_TOOLS のひとつ
        input_ = ToolCallInput(
            tool_name="memory_search",
            tool_input={"query": "test"},
            context={"intent": "default", "agent_id": "claude-code"},
        )

        decision = await evaluator.evaluate(input_)

        assert decision.decision == "allow"
        # LLM / memory はバイパスされ呼ばれない
        mock_llm.judge.assert_not_called()
        mock_memory.retrieve.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_read_only_tool_still_invokes_llm_path(self) -> None:
        """``memory_save`` (非 READ_ONLY) はバイパスされず LLM 経路を通る (回帰防止)。"""
        engine = PolicyEngine(_build_minimal_policy())

        mock_llm = MagicMock()
        mock_llm.judge = AsyncMock(
            return_value=Decision(decision="allow", reason="llm allowed"),
        )
        mock_memory = MagicMock()
        mock_memory.retrieve = AsyncMock(return_value=[])

        evaluator = CompositeEvaluator(
            engine=engine,
            memory_client=mock_memory,
            llm_evaluator=mock_llm,
            default_intent="default",
            default_agent_id="claude-code",
            evaluation_cache_ttl_seconds=300.0,
            memory_timeout_seconds=3.0,
        )

        input_ = ToolCallInput(
            tool_name="memory_save",
            tool_input={"content": "test memo"},
            context={"intent": "default", "agent_id": "claude-code"},
        )

        decision = await evaluator.evaluate(input_)

        assert decision.decision == "allow"
        # 非 READ_ONLY なので LLM が確実に呼ばれる (バイパス回帰防止)
        mock_llm.judge.assert_called_once()
