"""E2E 統合テスト - SQLite ライトウェイトモード。

外部サービス不要。一時ファイルを使用して Ingestion → Retrieval 全フローを検証する。

カバー範囲:
  A) ライトウェイトモード(SQLite)
  B) 並行書き込みストレステスト(SQLite)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from context_store.config import Settings
from context_store.orchestrator import Orchestrator, create_orchestrator
from tests.conftest import make_mock_embedding_provider

if TYPE_CHECKING:
    from context_store.server import ChronosServer


# ---------------------------------------------------------------------------
# 共通フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """テスト用一時SQLiteデータベースパス。"""
    return str(tmp_path / "test_e2e.db")


@pytest.fixture
def sqlite_settings(tmp_db_path: str) -> Settings:
    """SQLiteバックエンドのテスト用Settings。"""
    return Settings(
        storage_backend="sqlite",
        sqlite_db_path=tmp_db_path,
        embedding_provider="openai",
        openai_api_key=SecretStr("test-key"),
        graph_enabled=True,  # SQLiteGraphAdapter を使う (sqlite モードでは常に有効)
    )


@pytest.fixture
async def orchestrator(sqlite_settings: Settings) -> AsyncGenerator[Orchestrator, None]:
    """テスト用 Orchestrator(モック Embedding Provider 使用)。

    各クラス内の重複を削除し、一元化したモジュールレベルのフィクスチャ。
    """
    mock_provider = make_mock_embedding_provider(dim=16)

    with patch(
        "context_store.embedding.create_embedding_provider",
        return_value=mock_provider,
    ):
        orch = await create_orchestrator(sqlite_settings)
        yield orch
        await orch.dispose()


# ---------------------------------------------------------------------------
# A) ライトウェイトモード E2E テスト
# ---------------------------------------------------------------------------


class TestLightweightE2E:
    """SQLiteバックエンドを使用した外部サービス不要のE2Eテスト。"""

    async def test_memory_save_and_search(self, orchestrator: Orchestrator) -> None:
        """memory_save → memory_search の基本フロー。"""
        # 保存
        results = await orchestrator.save(
            "JWT認証をベースに統一する方針に決定した",
            metadata={"project": "myproject"},
        )
        assert len(results) >= 1
        memory_id = results[0].memory_id
        assert memory_id

        # 検索
        search_result = await orchestrator.search(
            "JWT認証",
            project="myproject",
            top_k=5,
        )
        assert isinstance(search_result, dict)
        assert "results" in search_result
        found_ids = [r["memory_id"] for r in search_result["results"]]
        # 保存したメモリが検索結果に含まれるか(ベクトル/キーワード検索)
        assert memory_id in found_ids, (
            f"Saved memory {memory_id} not found in search results: {found_ids}"
        )

    async def test_memory_stats(self, orchestrator: Orchestrator) -> None:
        """memory_stats の動作確認。"""
        # 事前に保存
        await orchestrator.save("テスト記憶1")
        await orchestrator.save("テスト記憶2")

        stats = await orchestrator.stats()
        assert isinstance(stats, dict)
        assert "active_count" in stats
        assert "archived_count" in stats
        assert "total_count" in stats
        assert stats["active_count"] >= 2

    async def test_memory_delete(self, orchestrator: Orchestrator) -> None:
        """memory_delete の動作確認。"""
        results = await orchestrator.save("削除対象のテスト記憶")
        assert len(results) >= 1
        memory_id = results[0].memory_id

        # 削除
        deleted = await orchestrator.delete(memory_id)
        assert deleted is True

        # 再削除は False
        deleted_again = await orchestrator.delete(memory_id)
        assert deleted_again is False

    async def test_memory_prune_dry_run(self, orchestrator: Orchestrator) -> None:
        """memory_prune dry_run の動作確認。"""
        # dry_run=True はエラーなく件数を返す
        count = await orchestrator.prune(older_than_days=90, dry_run=True)
        assert isinstance(count, int)
        assert count >= 0

    async def test_multiple_memories_ingestion(self, orchestrator: Orchestrator) -> None:
        """複数記憶の連続保存と検索。"""
        memories = [
            "Dockerで全サービスをコンテナ化した",
            "PostgreSQLのマイグレーションスクリプトを実行した",
            "Redisキャッシュの設定を最適化した",
            "FastAPIを使用してAPIを構築した",
            "pytest-asyncioでE2Eテストを追加した",
        ]

        saved_ids = []
        for content in memories:
            results = await orchestrator.save(content)
            assert len(results) >= 1
            saved_ids.append(results[0].memory_id)

        assert len(saved_ids) == 5

        # 統計確認
        stats = await orchestrator.stats()
        assert stats["active_count"] >= 5

    async def test_search_returns_normalized_rrf_scores(self, orchestrator: Orchestrator) -> None:
        """検索結果のRRFスコアが [0.0, 1.0] に正規化されていること。"""
        await orchestrator.save("GraphQLとRESTの比較検討を行った")
        await orchestrator.save("APIデザインのベストプラクティスを記録した")

        result = await orchestrator.search("API設計", top_k=10)
        hits = result.get("results", [])
        assert len(hits) > 0, "No results returned, cannot validate score normalization."

        for item in hits:
            score = item.get("score", 0.0)
            assert 0.0 <= score <= 1.0, f"Score {score} is out of [0.0, 1.0]"

    async def test_deduplication_append_only(self, orchestrator: Orchestrator) -> None:
        """Deduplicator の Append-only 動作確認。類似データをDELETEせず SUPERSEDES を作成。"""
        content = "JWTトークンの有効期限は24時間に設定した"

        # 初期件数を取得
        initial_stats = await orchestrator.stats()
        initial_count = initial_stats["total_count"]

        # 同じコンテンツを2回保存
        results1 = await orchestrator.save(content)
        results2 = await orchestrator.save(content)

        # エラーなく保存できること
        assert len(results1) >= 1
        assert len(results2) >= 1

        # 統計が正常に取得できること。Append-onlyなので件数が2増える
        stats = await orchestrator.stats()
        assert stats["total_count"] == initial_count + 2


# ---------------------------------------------------------------------------
# B) 並行書き込みストレステスト
# ---------------------------------------------------------------------------


class TestConcurrentWriteStress:
    """並行書き込み時のSQLite WAL動作確認。"""

    async def test_concurrent_writes_no_busy_errors(self, orchestrator: Orchestrator) -> None:
        """複数の並行 memory_save が SQLITE_BUSY なしで成功すること。"""
        N = 5

        async def save_one(i: int) -> str:
            results = await orchestrator.save(f"並行書き込みテスト記憶 {i}")
            return results[0].memory_id if results else ""

        tasks = [save_one(i) for i in range(N)]
        ids = await asyncio.gather(*tasks)

        assert all(ids)  # すべて成功すること(SQLITE_BUSY 回避の検証)

    async def test_search_during_concurrent_writes(self, orchestrator: Orchestrator) -> None:
        """書き込み中でも memory_search がブロックされないこと。"""
        # 事前データ保存
        await orchestrator.save("検索テスト用データ")

        start_event = asyncio.Event()
        search_during_write = False

        async def write_loop() -> None:
            # 書き込みループ開始を通知
            start_event.set()
            for i in range(5):
                await orchestrator.save(f"書き込み中テスト {i}")
                # 検索が並走する時間を稼ぐためにスリープを入れる
                await asyncio.sleep(0.05)

        async def search_loop(w_task: asyncio.Task) -> list[dict]:
            nonlocal search_during_write
            # 最初の書き込みが開始されるのを待つ
            try:
                await asyncio.wait_for(start_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pytest.fail("Search loop timed out waiting for start_event")

            results = []
            for _ in range(3):
                # タイムアウトを設定し、ブロックされないことを検証
                r = await asyncio.wait_for(orchestrator.search("テスト", top_k=3), timeout=2.0)
                # 書き込みタスクがまだ実行中かチェック
                if not w_task.done():
                    search_during_write = True
                results.append(r)
                await asyncio.sleep(0.01)
            return results

        # 並行実行
        # write_loop を先に作成し、search_loop に渡す
        write_task = asyncio.create_task(write_loop())
        search_task = asyncio.create_task(search_loop(write_task))

        # 両方のタスクの終了を待つ
        await write_task
        search_results = await search_task

        # 検索が3回ともエラーなく実行できること
        assert len(search_results) == 3
        # 書き込み中に少なくとも1回は検索が完了したこと
        assert search_during_write is True

    async def test_db_integrity_after_stress(self, orchestrator: Orchestrator) -> None:
        """ストレステスト(並行書き込み)後にDBの整合性が保たれていること。"""
        # 並行書き込みによる負荷
        N = 10

        async def save_one(i: int) -> None:
            await orchestrator.save(f"整合性テスト記憶 {i}")

        tasks = [save_one(i) for i in range(N)]
        await asyncio.gather(*tasks)

        # 統計が取れること
        stats = await orchestrator.stats()
        # 少なくとも N 件以上(以前のテストデータが含まれる可能性があるため >= N)
        assert stats["total_count"] >= N
        # アーカイブとアクティブの合計が total と一致
        assert stats["active_count"] + stats["archived_count"] == stats["total_count"]


# ---------------------------------------------------------------------------
# C) MCP Server E2E(ChronosServer ラッパー経由)
# ---------------------------------------------------------------------------


class TestMCPServerE2E:
    """ChronosServer(MCPラッパー)経由の全ツール動作確認。"""

    @pytest.fixture
    async def server_with_mock(self, tmp_db_path: str) -> AsyncGenerator[ChronosServer, None]:
        """ChronosServerとモックプロバイダーを設定する。"""
        from context_store.orchestrator import create_orchestrator
        from context_store.server import ChronosServer

        server = ChronosServer()
        mock_provider = make_mock_embedding_provider(dim=16)

        settings = Settings(
            storage_backend="sqlite",
            sqlite_db_path=tmp_db_path,
            embedding_provider="openai",
            openai_api_key=SecretStr("test-key"),
            graph_enabled=True,  # SQLiteGraphAdapter を使う
        )

        # create_orchestrator を実際の SQLite + MockProvider で実行
        with patch("context_store.embedding.create_embedding_provider", return_value=mock_provider):
            orch = await create_orchestrator(settings)

        await server.initialize_for_test(orch)

        yield server

        if server._orchestrator:
            await server._orchestrator.dispose()

    async def test_memory_save_default_source(self, server_with_mock: ChronosServer) -> None:
        """memory_save の source デフォルト値が 'conversation' であること。"""
        server = server_with_mock
        content = "テストコンテンツ"
        result = await server.memory_save(content=content)

        data = json.loads(result)
        assert data.get("saved", 0) >= 1

        # 保存されたアイテムを検索して source を検証
        search_res = json.loads(await server.memory_search(query=content))
        assert len(search_res["results"]) > 0, (
            "Search results should not be empty before testing for 'conversation' source_type"
        )
        assert any(item["source_type"] == "conversation" for item in search_res["results"])

    async def test_memory_save_explicit_source(self, server_with_mock: ChronosServer) -> None:
        """memory_save に source='manual' を指定したとき正しく保持されること。"""
        server = server_with_mock
        content = "手動入力テスト"
        result = await server.memory_save(content=content, source="manual")

        data = json.loads(result)
        assert data.get("saved", 0) >= 1

        # 保存されたアイテムを検索して source を検証
        search_res = json.loads(await server.memory_search(query=content))
        assert len(search_res["results"]) > 0, (
            "Search results should not be empty before testing for 'manual' source_type"
        )
        assert any(item["source_type"] == "manual" for item in search_res["results"])

    async def test_memory_search(self, server_with_mock: ChronosServer) -> None:
        """memory_search がJSON文字列を返すこと。"""
        server = server_with_mock
        await server.memory_save(content="検索テスト用コンテンツ")
        result = await server.memory_search(query="テスト")

        data = json.loads(result)
        assert "results" in data

    async def test_memory_stats(self, server_with_mock: ChronosServer) -> None:
        """memory_stats がJSON文字列を返すこと。"""
        server = server_with_mock
        result = await server.memory_stats()

        data = json.loads(result)
        assert "total_count" in data

    async def test_memory_prune_dry_run(self, server_with_mock: ChronosServer) -> None:
        """memory_prune dry_run がJSON文字列を返すこと。"""
        server = server_with_mock
        result = await server.memory_prune(older_than_days=90, dry_run=True)

        data = json.loads(result)
        assert "count" in data
        assert data["dry_run"] is True
