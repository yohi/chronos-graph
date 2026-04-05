"""記憶の減衰スコアを計算するモジュール。"""

from __future__ import annotations

from datetime import datetime, timezone

from context_store.config import Settings
from context_store.models.memory import Memory


class DecayScorer:
    """記憶の複合減衰スコアを計算するクラス。

    スコア計算式 (§5.3):
        recency   = 0.5 ^ (days_elapsed / half_life_days)
        composite = 0.5 * semantic_relevance
                  + 0.3 * recency
                  + 0.2 * importance_score

    Args:
        settings: アプリケーション設定。省略時はデフォルト値を使用。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        if settings is not None:
            self.half_life_days: int = settings.decay_half_life_days
            self.archive_threshold: float = settings.archive_threshold
        else:
            self.half_life_days = 30
            self.archive_threshold = 0.05

    def compute_composite_score(self, memory: Memory) -> float:
        """記憶の複合減衰スコアを計算する。

        Args:
            memory: スコアを計算する記憶オブジェクト。

        Returns:
            0.0 以上 1.0 以下の複合スコア。
        """
        now = datetime.now(timezone.utc)
        days_elapsed = (now - memory.last_accessed_at).total_seconds() / 86400.0
        recency = 0.5 ** (days_elapsed / self.half_life_days)
        composite = 0.5 * memory.semantic_relevance + 0.3 * recency + 0.2 * memory.importance_score
        return float(composite)

    def is_below_archive_threshold(self, memory: Memory) -> bool:
        """記憶のスコアがアーカイブ閾値を下回るかどうかを判定する。

        Args:
            memory: 判定対象の記憶オブジェクト。

        Returns:
            スコアが閾値未満の場合 True。
        """
        return self.compute_composite_score(memory) < self.archive_threshold
