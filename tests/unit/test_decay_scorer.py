"""DecayScorer のユニットテスト。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from context_store.lifecycle.decay_scorer import DecayScorer
from context_store.models.memory import Memory, MemoryType, SourceType
from tests.unit.conftest import make_settings


def _make_memory(
    *,
    days_since_access: float = 0,
    semantic_relevance: float = 0.5,
    importance_score: float = 0.5,
) -> Memory:
    """テスト用 Memory を生成するヘルパー。"""
    now = datetime.now(timezone.utc)
    last_accessed_at = now - timedelta(days=days_since_access)
    return Memory(
        content="テスト記憶",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        semantic_relevance=semantic_relevance,
        importance_score=importance_score,
        last_accessed_at=last_accessed_at,
    )


class TestDecayScorerCompositeScore:
    """compute_composite_score のテスト。"""

    def test_fresh_memory_has_high_score(self):
        """作成直後の記憶は composite > 0.4 を返すこと。"""
        scorer = DecayScorer()
        memory = _make_memory(days_since_access=0, semantic_relevance=0.5, importance_score=0.5)
        score = scorer.compute_composite_score(memory)
        assert score > 0.4, f"Expected score > 0.4, got {score}"

    def test_score_halves_after_half_life(self):
        """30日経過後、recency コンポーネントが約半分になること。"""
        scorer = DecayScorer()

        # recency だけ変化させるため semantic_relevance=0, importance_score=0 にする
        memory_fresh = _make_memory(
            days_since_access=0, semantic_relevance=0.0, importance_score=0.0
        )
        memory_aged = _make_memory(
            days_since_access=30, semantic_relevance=0.0, importance_score=0.0
        )

        score_fresh = scorer.compute_composite_score(memory_fresh)
        score_aged = scorer.compute_composite_score(memory_aged)

        # recency が 0.3 の重みを持つので、30日後は 0.5^1 = 0.5 倍
        # fresh: 0.3 * 1.0 = 0.3
        # aged:  0.3 * 0.5 = 0.15
        assert abs(score_aged - score_fresh * 0.5) < 0.01, (
            f"Expected aged score ~= {score_fresh * 0.5:.4f}, got {score_aged:.4f}"
        )

    def test_score_is_very_low_after_90_days(self):
        """90日経過後、スコアが閾値 0.05 以下になりうること。"""
        scorer = DecayScorer()
        # semantic_relevance=0, importance_score=0 の場合は recency のみ
        memory = _make_memory(days_since_access=90, semantic_relevance=0.0, importance_score=0.0)
        score = scorer.compute_composite_score(memory)
        # recency = 0.5^(90/30) = 0.5^3 = 0.125; composite = 0.3 * 0.125 = 0.0375 < 0.05
        assert score <= 0.05, f"Expected score <= 0.05 after 90 days, got {score}"

    def test_score_formula_correctness(self):
        """合成スコアの数式が正しく計算されていること。"""
        scorer = DecayScorer()
        memory = _make_memory(
            days_since_access=30,
            semantic_relevance=0.8,
            importance_score=0.6,
        )
        score = scorer.compute_composite_score(memory)

        # 期待値: 0.5*0.8 + 0.3*(0.5^1) + 0.2*0.6 = 0.4 + 0.15 + 0.12 = 0.67
        expected = 0.5 * 0.8 + 0.3 * (0.5**1) + 0.2 * 0.6
        assert abs(score - expected) < 0.001, f"Expected {expected:.4f}, got {score:.4f}"

    def test_score_range_is_between_0_and_1(self):
        """スコアは常に 0.0 以上 1.0 以下であること。"""
        scorer = DecayScorer()
        test_cases = [
            (0, 1.0, 1.0),
            (0, 0.0, 0.0),
            (365, 1.0, 1.0),
            (365, 0.0, 0.0),
        ]
        for days, sem, imp in test_cases:
            memory = _make_memory(
                days_since_access=days, semantic_relevance=sem, importance_score=imp
            )
            score = scorer.compute_composite_score(memory)
            assert 0.0 <= score <= 1.0, f"Score out of range: {score} (days={days})"


class TestDecayScorerArchiveThreshold:
    """is_below_archive_threshold のテスト。"""

    def test_fresh_memory_is_not_below_threshold(self):
        """作成直後の記憶はアーカイブ閾値を下回らないこと。"""
        scorer = DecayScorer()
        memory = _make_memory(days_since_access=0)
        assert not scorer.is_below_archive_threshold(memory)

    def test_very_old_low_relevance_memory_is_below_threshold(self):
        """90日経過かつ低関連度の記憶はアーカイブ閾値を下回ること。"""
        scorer = DecayScorer()
        memory = _make_memory(days_since_access=90, semantic_relevance=0.0, importance_score=0.0)
        assert scorer.is_below_archive_threshold(memory)

    def test_high_importance_memory_stays_above_threshold(self):
        """重要度が高い記憶は古くてもアーカイブ閾値を下回らないこと。"""
        scorer = DecayScorer()
        memory = _make_memory(days_since_access=60, semantic_relevance=1.0, importance_score=1.0)
        assert not scorer.is_below_archive_threshold(memory)


class TestDecayScorerSettingsInjection:
    """Settings インジェクションのテスト。"""

    def test_custom_half_life_affects_score(self):
        """カスタム半減期が適用されること。"""
        # 半減期 10 日のスコアラー
        settings_short = make_settings(decay_half_life_days=10)
        # 半減期 60 日のスコアラー
        settings_long = make_settings(decay_half_life_days=60)

        scorer_short = DecayScorer(settings=settings_short)
        scorer_long = DecayScorer(settings=settings_long)

        memory = _make_memory(days_since_access=10, semantic_relevance=0.0, importance_score=0.0)

        # 半減期 10日なら 0.5^1 = 0.5; 半減期 60日なら 0.5^(10/60) ≈ 0.891
        score_short = scorer_short.compute_composite_score(memory)
        score_long = scorer_long.compute_composite_score(memory)
        assert score_short < score_long, (
            f"Short half-life score ({score_short}) should be less than long ({score_long})"
        )

    def test_custom_archive_threshold_affects_result(self):
        """カスタムアーカイブ閾値が is_below_archive_threshold に反映されること。"""
        # 非常に高い閾値で、通常は閾値以上のスコアもアーカイブ対象になる
        settings_high = make_settings(archive_threshold=0.9)
        scorer = DecayScorer(settings=settings_high)

        # 作成直後でも閾値 0.9 には届かないのでアーカイブ対象になるはず
        memory = _make_memory(days_since_access=0, semantic_relevance=0.5, importance_score=0.5)
        # composite ≈ 0.5*0.5 + 0.3*1.0 + 0.2*0.5 = 0.25 + 0.3 + 0.1 = 0.65 < 0.9
        assert scorer.is_below_archive_threshold(memory)

    def test_default_settings_uses_standard_values(self):
        """Settings を省略した場合、デフォルト値 (30日 / 0.05) が使われること。"""
        scorer = DecayScorer()
        assert scorer.half_life_days == 30
        assert scorer.archive_threshold == 0.05
