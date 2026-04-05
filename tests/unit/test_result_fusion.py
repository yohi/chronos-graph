"""Result Fusion (RRF + 複合スコアリング) のテスト"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from context_store.models.memory import Memory, MemorySource, MemoryType, SourceType
from context_store.models.search import ScoredMemory
from context_store.retrieval.query_analyzer import SearchStrategy
from context_store.retrieval.result_fusion import ResultFusion


@pytest.fixture
def result_fusion():
    """ResultFusion インスタンス"""
    return ResultFusion(k=60, half_life_days=30)


@pytest.fixture
def sample_results():
    """テスト用のサンプル結果"""
    now = datetime.now(timezone.utc)
    results = [
        ScoredMemory(
            memory=Memory(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                content="JWT認証",
                memory_type=MemoryType.SEMANTIC,
                source_type=SourceType.MANUAL,
                semantic_relevance=0.8,
                importance_score=0.8,
                last_accessed_at=now,
            ),
            score=0.95,
            source=MemorySource.VECTOR,
        ),
        ScoredMemory(
            memory=Memory(
                id=UUID("00000000-0000-0000-0000-000000000002"),
                content="OAuth実装",
                memory_type=MemoryType.SEMANTIC,
                source_type=SourceType.MANUAL,
                semantic_relevance=0.7,
                importance_score=0.6,
                last_accessed_at=now - timedelta(days=30),
            ),
            score=0.85,
            source=MemorySource.VECTOR,
        ),
    ]
    return results


@pytest.fixture
def search_strategy():
    """テスト用の検索戦略"""
    return SearchStrategy(
        vector_weight=0.5,
        keyword_weight=0.2,
        graph_weight=0.3,
        graph_depth=2,
        time_decay_enabled=True,
    )


class TestResultFusion:
    """結果統合とスコアリングのテスト"""

    def test_rrf_calculation(self, result_fusion, sample_results, search_strategy):
        """RRF スコアの計算が正しいこと"""
        fused = result_fusion.fuse_multiple_sources(
            {
                MemorySource.VECTOR: sample_results,
                MemorySource.KEYWORD: sample_results,
                MemorySource.GRAPH: sample_results,
            },
            search_strategy,
        )

        expected_rrf = result_fusion.compute_rrf_score(
            vector_rank=0,
            keyword_rank=0,
            graph_rank=0,
            vector_weight=search_strategy.vector_weight,
            keyword_weight=search_strategy.keyword_weight,
            graph_weight=search_strategy.graph_weight,
        )
        assert fused[0]["rrf_score"] == pytest.approx(expected_rrf, abs=0.0001)

    def test_time_decay(self, result_fusion):
        """時間減衰の計算"""
        now = datetime.now(timezone.utc)
        recency_0 = result_fusion.compute_time_decay(now)
        assert recency_0 == pytest.approx(1.0, abs=0.0001)

        recency_30 = result_fusion.compute_time_decay(now - timedelta(days=30))
        assert recency_30 == pytest.approx(0.5, abs=0.0001)

        recency_60 = result_fusion.compute_time_decay(now - timedelta(days=60))
        assert recency_60 == pytest.approx(0.25, abs=0.0001)

    def test_composite_score_calculation(self, result_fusion, sample_results, search_strategy):
        """複合スコアの計算"""
        fused = result_fusion.fuse(sample_results[:1], search_strategy)
        expected_rrf = result_fusion.compute_rrf_score(
            vector_rank=0,
            keyword_rank=None,
            graph_rank=None,
            vector_weight=1.0,
            keyword_weight=0.0,
            graph_weight=0.0,
        )
        expected = 0.5 * expected_rrf + 0.3 * 1.0 + 0.2 * 0.8
        assert fused[0]["final_score"] == pytest.approx(expected, abs=0.0001)

    def test_fusion_with_empty_results(self, result_fusion, search_strategy):
        """空の結果に対応"""
        results = result_fusion.fuse([], search_strategy)
        assert results == []

    def test_fusion_returns_sorted_results(self, result_fusion, sample_results, search_strategy):
        """結果がスコア順にソートされること"""
        # 複数の検索結果を作成（異なるスコアで）
        results_dict = {
            MemorySource.VECTOR: sample_results,
            MemorySource.KEYWORD: [],
            MemorySource.GRAPH: [],
        }

        fused = result_fusion.fuse_multiple_sources(results_dict, search_strategy)

        # スコアが降順でソートされていることを確認
        for i in range(len(fused) - 1):
            assert fused[i]["final_score"] >= fused[i + 1]["final_score"]

    def test_normalize_rrf_edge_case_empty(self, result_fusion):
        """RRF正規化：空入力"""
        result = result_fusion.normalize_rrf([], 1.0, 60)
        assert result == []

    def test_normalize_rrf_clamp_to_range(self, result_fusion):
        """RRF正規化：[0.0, 1.0] にクランプ"""
        scores = [0.5, 1.5, -0.5]  # 正規化前のスコア
        normalized = result_fusion.normalize_rrf(scores, 1.0, 60)

        # すべて [0.0, 1.0] の範囲内
        for score in normalized:
            assert 0.0 <= score <= 1.0
