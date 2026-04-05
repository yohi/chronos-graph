"""Result Fusion - RRF + 複合スコアリング"""

import logging
from datetime import datetime, timezone
from typing import Any, TypedDict, cast

from context_store.models.memory import Memory, MemorySource, ScoredMemory
from context_store.models.search import SearchStrategy

logger = logging.getLogger(__name__)


class MemoryScore(TypedDict):
    memory: Memory
    vector_rank: int | None
    keyword_rank: int | None
    graph_rank: int | None


class ResultFusion:
    """RRF (Reciprocal Rank Fusion) + 時間減衰 + 複合スコアリング"""

    def __init__(
        self,
        k: int = 60,
        half_life_days: int = 30,
        rrf_weight: float = 0.5,
        time_decay_weight: float = 0.3,
        importance_weight: float = 0.2,
    ) -> None:
        """
        初期化

        Args:
            k: RRF定数
            half_life_days: 時間減衰の半減期(日)
            rrf_weight: RRFスコアの重み
            time_decay_weight: 時間減衰スコアの重み
            importance_weight: 重要度スコアの重み
        """
        if half_life_days <= 0:
            raise ValueError("half_life_days must be greater than zero")

        # 重みのバリデーション: 全て 0 以上で、合計が 0 より大きいことを確認
        if rrf_weight < 0 or time_decay_weight < 0 or importance_weight < 0:
            raise ValueError("All weights must be non-negative")

        weights_sum = rrf_weight + time_decay_weight + importance_weight
        if weights_sum <= 0:
            raise ValueError("Sum of weights must be greater than zero")

        if abs(weights_sum - 1.0) > 1e-6:
            # 1.0 でない場合は正規化する
            logger.warning(
                "Weights (rrf=%.2f, time_decay=%.2f, importance=%.2f) sum to %.2f, normalizing to 1.0",
                rrf_weight,
                time_decay_weight,
                importance_weight,
                weights_sum,
            )
            rrf_weight /= weights_sum
            time_decay_weight /= weights_sum
            importance_weight /= weights_sum

        self.k = k
        self.half_life_days = half_life_days
        self.rrf_weight = rrf_weight
        self.time_decay_weight = time_decay_weight
        self.importance_weight = importance_weight

    def normalize_rrf(
        self,
        scores: list[float],
        weights_sum: float = 1.0,
        k: int | None = None,
    ) -> list[float]:
        """
        RRFスコアを正規化

        Args:
            scores: RRFスコアのリスト
            weights_sum: ウェイトの合計
            k: RRF定数

        Returns:
            正規化されたスコア([0.0, 1.0]の範囲)
        """
        if k is None:
            k = self.k

        if not scores:
            return []

        # 理論上の最大スコアを計算 (rank=0 の時: 1/(k+0+1) = 1/(k+1))
        max_possible_score = weights_sum * (1.0 / (k + 1))
        if max_possible_score <= 0.0:
            return [0.0] * len(scores)

        # スコアを正規化
        normalized = []
        for score in scores:
            normalized_score = score / max_possible_score
            # [0.0, 1.0]にクランプ
            clamped = max(0.0, min(1.0, normalized_score))
            normalized.append(clamped)

        return normalized

    def compute_rrf_score(
        self,
        vector_rank: int | None,
        keyword_rank: int | None,
        graph_rank: int | None,
        vector_weight: float,
        keyword_weight: float,
        graph_weight: float,
    ) -> float:
        """
        複数の検索結果のRRFスコアを計算(0.0~1.0 に正規化)

        Args:
            vector_rank: ベクトル検索でのランク(なければNone)
            keyword_rank: キーワード検索でのランク(なければNone)
            graph_rank: グラフ検索でのランク(なければNone)
            vector_weight: ベクトル検索の重み
            keyword_weight: キーワード検索の重み
            graph_weight: グラフ検索の重み

        Returns:
            RRFスコア(0.0~1.0 に正規化)
        """
        score = 0.0

        if vector_rank is not None:
            score += vector_weight * (1.0 / (self.k + vector_rank + 1))

        if keyword_rank is not None:
            score += keyword_weight * (1.0 / (self.k + keyword_rank + 1))

        if graph_rank is not None:
            score += graph_weight * (1.0 / (self.k + graph_rank + 1))

        # [0.0, 1.0] の範囲に正規化 (全ソースで 1 位だった場合を 1.0 とする)
        max_possible = (vector_weight + keyword_weight + graph_weight) / (self.k + 1)
        if max_possible > 0:
            return score / max_possible
        return 0.0

    def compute_time_decay(
        self,
        last_accessed_at: datetime,
    ) -> float:
        """
        時間減衰を計算(小数精度の経過時間を使用)

        Args:
            last_accessed_at: 最終アクセス日時

        Returns:
            時間減衰スコア([0.0, 1.0])
        """
        now = datetime.now(timezone.utc)
        if last_accessed_at.tzinfo is None:
            last_accessed_at = last_accessed_at.replace(tzinfo=timezone.utc)
        else:
            last_accessed_at = last_accessed_at.astimezone(timezone.utc)
        delta = now - last_accessed_at
        # 未来の日時などで負になるのを防ぐため 0.0 にクランプ
        days_elapsed = max(delta.total_seconds() / 86400.0, 0.0)

        recency: float = 0.5 ** (days_elapsed / self.half_life_days)
        return recency

    def fuse(
        self,
        results: list[ScoredMemory],
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        """
        検索結果を統合(単一ソース用)

        Args:
            results: ScoredMemoryのリスト
            strategy: 検索戦略

        Returns:
            統合されたスコア付き結果
        """
        if not results:
            return []

        fused_results = []

        for rank, result in enumerate(results):
            # RRFスコア(単一ソースなので、ランクを正規化)
            rrf_raw = (self.k + 1) / (self.k + rank + 1)

            # 複合スコア計算
            time_decay = (
                self.compute_time_decay(result.memory.last_accessed_at)
                if strategy.time_decay_enabled
                else 1.0
            )

            final_score = (
                self.rrf_weight * rrf_raw
                + self.time_decay_weight * time_decay
                + self.importance_weight * result.memory.importance_score
            )

            fused_results.append(
                {
                    "memory_id": str(result.memory.id),
                    "content": result.memory.content,
                    "final_score": final_score,
                    "rrf_score": rrf_raw,
                    "time_decay": time_decay,
                    "importance_score": result.memory.importance_score,
                }
            )

        # スコアの降順でソート
        fused_results.sort(key=lambda x: cast(float, x["final_score"]), reverse=True)

        return fused_results

    def fuse_multiple_sources(
        self,
        results_dict: dict[MemorySource, list[ScoredMemory]],
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        """
        複数ソースの検索結果を統合

        Args:
            results_dict: ソース別の検索結果
            strategy: 検索戦略

        Returns:
            統合されたスコア付き結果
        """
        # メモリIDごとに結果を集計
        memory_scores: dict[str, MemoryScore] = {}

        # ベクトル検索結果
        for rank, result in enumerate(results_dict.get(MemorySource.VECTOR, [])):
            mem_id = str(result.memory.id)
            if mem_id not in memory_scores:
                memory_scores[mem_id] = {
                    "memory": result.memory,
                    "vector_rank": rank,
                    "keyword_rank": None,
                    "graph_rank": None,
                }
            else:
                memory_scores[mem_id]["vector_rank"] = rank

        # キーワード検索結果
        for rank, result in enumerate(results_dict.get(MemorySource.KEYWORD, [])):
            mem_id = str(result.memory.id)
            if mem_id not in memory_scores:
                memory_scores[mem_id] = {
                    "memory": result.memory,
                    "vector_rank": None,
                    "keyword_rank": rank,
                    "graph_rank": None,
                }
            else:
                memory_scores[mem_id]["keyword_rank"] = rank

        # グラフ検索結果
        for rank, result in enumerate(results_dict.get(MemorySource.GRAPH, [])):
            mem_id = str(result.memory.id)
            if mem_id not in memory_scores:
                memory_scores[mem_id] = {
                    "memory": result.memory,
                    "vector_rank": None,
                    "keyword_rank": None,
                    "graph_rank": rank,
                }
            else:
                memory_scores[mem_id]["graph_rank"] = rank

        # 複合スコアを計算
        fused_results = []
        for mem_id, data in memory_scores.items():
            rrf_score = self.compute_rrf_score(
                vector_rank=data["vector_rank"],
                keyword_rank=data["keyword_rank"],
                graph_rank=data["graph_rank"],
                vector_weight=strategy.vector_weight,
                keyword_weight=strategy.keyword_weight,
                graph_weight=strategy.graph_weight,
            )

            time_decay = (
                self.compute_time_decay(data["memory"].last_accessed_at)
                if strategy.time_decay_enabled
                else 1.0
            )

            final_score = (
                self.rrf_weight * rrf_score
                + self.time_decay_weight * time_decay
                + self.importance_weight * data["memory"].importance_score
            )

            fused_results.append(
                {
                    "memory_id": mem_id,
                    "content": data["memory"].content,
                    "final_score": final_score,
                    "rrf_score": rrf_score,
                    "time_decay": time_decay,
                    "importance_score": data["memory"].importance_score,
                }
            )

        # スコアの降順でソート
        fused_results.sort(key=lambda x: cast(float, x["final_score"]), reverse=True)

        return fused_results
