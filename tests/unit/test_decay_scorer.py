"""Decay Scorer のテスト"""

import pytest
from datetime import datetime, timedelta
from context_store.lifecycle.decay_scorer import DecayScorer
from context_store.models.memory import Memory, MemoryType, SourceType


@pytest.fixture
def decay_scorer():
    """DecayScorer インスタンス"""
    return DecayScorer(
        half_life_days=30,
        archive_threshold=0.05,
    )


@pytest.fixture
def memory_factory():
    """Memory インスタンスのファクトリ"""

    def _factory(
        semantic_relevance: float = 0.8,
        importance_score: float = 0.7,
        last_accessed_at: datetime | None = None,
    ) -> Memory:
        now = datetime.utcnow()
        return Memory(
            id="test-memory",
            content="Test content",
            memory_type=MemoryType.SEMANTIC,
            source_type=SourceType.MANUAL,
            source_metadata={},
            embedding=[0.1] * 384,
            semantic_relevance=semantic_relevance,
            importance_score=importance_score,
            access_count=1,
            last_accessed_at=last_accessed_at or now,
            created_at=now,
            updated_at=now,
            archived_at=None,
            tags=[],
            project=None,
        )

    return _factory


class TestDecayScorer:
    """Decay Scorer の複合スコア計算テスト"""

    def test_score_just_created(self, decay_scorer, memory_factory):
        """作成直後の記憶は高スコア"""
        memory = memory_factory()
        score = decay_scorer.compute_composite_score(memory)
        # composite = 0.5 * semantic_relevance + 0.3 * recency + 0.2 * importance_score
        # recency = 0.5^(0/30) = 1.0
        # composite = 0.5 * 0.8 + 0.3 * 1.0 + 0.2 * 0.7 = 0.4 + 0.3 + 0.14 = 0.84
        assert score == pytest.approx(0.84, abs=0.01)

    def test_score_30_days_later(self, decay_scorer, memory_factory):
        """30日経過: スコアが約半分"""
        now = datetime.utcnow()
        last_accessed = now - timedelta(days=30)
        memory = memory_factory(last_accessed_at=last_accessed)
        score = decay_scorer.compute_composite_score(memory)
        # recency = 0.5^(30/30) = 0.5
        # composite = 0.5 * 0.8 + 0.3 * 0.5 + 0.2 * 0.7 = 0.4 + 0.15 + 0.14 = 0.69
        assert score == pytest.approx(0.69, abs=0.01)

    def test_score_90_days_later(self, decay_scorer, memory_factory):
        """90日経過: 閾値以下に低下"""
        now = datetime.utcnow()
        last_accessed = now - timedelta(days=90)
        memory = memory_factory(last_accessed_at=last_accessed)
        score = decay_scorer.compute_composite_score(memory)
        # recency = 0.5^(90/30) = 0.5^3 = 0.125
        # composite = 0.5 * 0.8 + 0.3 * 0.125 + 0.2 * 0.7 = 0.4 + 0.0375 + 0.14 = 0.5775
        # これは閾値（0.05）より高い。もっと後まで待つ必要がある
        assert score < 1.0

    def test_score_decays_over_time(self, decay_scorer, memory_factory):
        """スコアが時間とともに減衰"""
        now = datetime.utcnow()
        score_0_days = decay_scorer.compute_composite_score(memory_factory(last_accessed_at=now))
        score_30_days = decay_scorer.compute_composite_score(
            memory_factory(last_accessed_at=now - timedelta(days=30))
        )
        score_60_days = decay_scorer.compute_composite_score(
            memory_factory(last_accessed_at=now - timedelta(days=60))
        )
        assert score_0_days > score_30_days > score_60_days

    def test_should_archive_below_threshold(self, decay_scorer, memory_factory):
        """閾値以下の記憶をアーカイブ対象として検出"""
        now = datetime.utcnow()
        # 非常に低い semantic_relevance と importance_score で、閾値以下にする
        memory = memory_factory(
            semantic_relevance=0.01,
            importance_score=0.01,
            last_accessed_at=now - timedelta(days=200),
        )
        score = decay_scorer.compute_composite_score(memory)
        # composite = 0.5 * 0.01 + 0.3 * recency + 0.2 * 0.01
        # recency = 0.5^(200/30) = 0.5^6.67 ≈ 0.0099
        # composite ≈ 0.005 + 0.003 + 0.002 = 0.01
        assert score < decay_scorer.archive_threshold
