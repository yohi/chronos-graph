"""パフォーマンスベンチマークスイート。

pytest-benchmark を使用した各パイプラインコンポーネントの性能計測。

実行方法:
    pytest tests/benchmark/ -v --benchmark-only
    pytest tests/benchmark/ -v --benchmark-json=results.json
    pytest tests/benchmark/ -v --benchmark-compare  # 前回結果との比較
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Generator
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from context_store.config import Settings
from context_store.orchestrator import Orchestrator, create_orchestrator
from context_store.retrieval.pipeline import RetrievalResponse
from tests.conftest import make_mock_embedding_provider


# ---------------------------------------------------------------------------
# 共通フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory: pytest.TempPathFactory) -> str:
    """モジュールスコープの一時 DB パス。"""
    return str(tmp_path_factory.mktemp("bench") / "bench.db")


@pytest.fixture(scope="module")
def settings(tmp_db: str) -> Settings:
    """ベンチマーク用 Settings。"""
    return Settings(
        storage_backend="sqlite",
        sqlite_db_path=tmp_db,
        embedding_provider="openai",
        openai_api_key=SecretStr("bench-key"),
        graph_enabled=True,
    )


@pytest.fixture(scope="module")
def orchestrator(
    settings: Settings, event_loop: asyncio.AbstractEventLoop
) -> Generator[Orchestrator, None, None]:
    """モジュールスコープの Orchestrator（ベンチマーク間で共有）。"""
    mock_provider = make_mock_embedding_provider(dim=16)
    with patch("context_store.embedding.create_embedding_provider", return_value=mock_provider):
        orch = event_loop.run_until_complete(create_orchestrator(settings))
    yield orch
    event_loop.run_until_complete(orch.dispose())


@pytest.fixture(scope="module", autouse=True)
def seed_data(orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop) -> None:
    """ベンチマーク前にデータを投入する。"""
    contents = [
        f"ベンチマーク用データ {i}: システムアーキテクチャの設計決定事項を記録する。"
        for i in range(50)
    ]

    async def _seed() -> None:
        for c in contents:
            await orchestrator.save(c)

    event_loop.run_until_complete(_seed())


# ---------------------------------------------------------------------------
# ベンチマーク: Ingestion (memory_save)
# ---------------------------------------------------------------------------


def bench_save(
    orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop, content: str
) -> Any:
    """単一 save の実行時間を計測するヘルパー。"""
    return event_loop.run_until_complete(orchestrator.save(content))


@pytest.mark.benchmark(group="ingestion")
def test_bench_memory_save_single(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """1件の memory_save レイテンシを計測する。"""
    i = 0

    def run() -> Any:
        nonlocal i
        i += 1
        return bench_save(orchestrator, event_loop, f"ベンチマーク保存テスト {i}")

    benchmark(run)


@pytest.mark.benchmark(group="ingestion")
def test_bench_memory_save_with_metadata(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """メタデータ付き memory_save のレイテンシを計測する。"""
    i = 0

    def run() -> Any:
        nonlocal i
        i += 1
        return event_loop.run_until_complete(
            orchestrator.save(
                f"メタデータ付き保存テスト {i}",
                metadata={"project": "benchmark", "session_id": "bench-001"},
            )
        )

    benchmark(run)


# ---------------------------------------------------------------------------
# ベンチマーク: Retrieval (memory_search)
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="retrieval")
def test_bench_memory_search_top10(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """top_k=10 の memory_search レイテンシを計測する。"""

    def run() -> Any:
        return event_loop.run_until_complete(
            orchestrator.search("システムアーキテクチャ", top_k=10)
        )

    benchmark(run)


@pytest.mark.benchmark(group="retrieval")
def test_bench_memory_search_top50(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """top_k=50 の memory_search レイテンシを計測する。"""

    def run() -> Any:
        return event_loop.run_until_complete(orchestrator.search("設計決定", top_k=50))

    benchmark(run)


@pytest.mark.benchmark(group="retrieval")
def test_bench_memory_search_with_project_filter(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """プロジェクトフィルタ付き memory_search のレイテンシを計測する。"""

    def run() -> Any:
        return event_loop.run_until_complete(
            orchestrator.search("アーキテクチャ", project="benchmark", top_k=10)
        )

    benchmark(run)


# ---------------------------------------------------------------------------
# ベンチマーク: Stats
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="stats")
def test_bench_memory_stats(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """memory_stats のレイテンシを計測する。"""

    def run() -> Any:
        return event_loop.run_until_complete(orchestrator.stats())

    benchmark(run)


@pytest.mark.benchmark(group="stats")
def test_bench_memory_stats_with_project(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """プロジェクトフィルタ付き memory_stats のレイテンシを計測する。"""

    def run() -> Any:
        return event_loop.run_until_complete(orchestrator.stats(project="benchmark"))

    benchmark(run)


# ---------------------------------------------------------------------------
# ベンチマーク: 並行アクセス
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="concurrency")
def test_bench_concurrent_search(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """5並行 memory_search のスループットを計測する。"""

    async def run_concurrent() -> list[RetrievalResponse]:
        tasks = [orchestrator.search(f"並行検索テスト {i}", top_k=5) for i in range(5)]
        return list(await asyncio.gather(*tasks))

    def run() -> Any:
        return event_loop.run_until_complete(run_concurrent())

    benchmark(run)


@pytest.mark.benchmark(group="concurrency")
def test_bench_mixed_read_write(
    benchmark: Any, orchestrator: Orchestrator, event_loop: asyncio.AbstractEventLoop
) -> None:
    """読み書き混合アクセス（3 save + 2 search）の合計レイテンシを計測する。"""
    counter = [0]

    async def run_mixed() -> list[Any]:
        counter[0] += 1
        tasks: list[Coroutine[Any, Any, Any]] = [
            orchestrator.save(f"混合テスト保存 {counter[0]}-{i}") for i in range(3)
        ] + [orchestrator.search("混合テスト", top_k=3) for _ in range(2)]
        return list(await asyncio.gather(*tasks))

    def run() -> Any:
        return event_loop.run_until_complete(run_mixed())

    benchmark(run)
