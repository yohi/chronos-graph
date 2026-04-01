"""Result Fusion - RRF + 複合スコアリング"""

from datetime import datetime, timezone
from typing import Any, cast
from context_store.models.search import SearchStrategy, ScoredMemory
from context_store.models.memory import MemorySource


class ResultFusion:
    """RRF (Reciprocal Rank Fusion) + 時間減衰 + 複合スコアリング"""

    def __init__(self, k: int = 60, half_life_days: int = 30):
        """
        初期化

        Args:
            k: RRF定数
            half_life_days: 時間減衰の半減期（日）
        """
        self.k = k
        self.half_life_days = half_life_days

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
            正規化されたスコア（[0.0, 1.0]の範囲）
        """
        if k is None:
            k = self.k

        if not scores:
            return []

        # 理論上の最大スコアを計算
        max_possible_score = weights_sum * (1.0 / (k + 2))
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
        複数の検索結果のRRFスコアを計算

        Args:
            vector_rank: ベクトル検索でのランク（なければNone）
            keyword_rank: キーワード検索でのランク（なければNone）
            graph_rank: グラフ検索でのランク（なければNone）
            vector_weight: ベクトル検索の重み
            keyword_weight: キーワード検索の重み
            graph_weight: グラフ検索の重み

        Returns:
            RRFスコア
        """
        score = 0.0

        if vector_rank is not None:
            score += vector_weight * (1.0 / (self.k + vector_rank + 1))

        if keyword_rank is not None:
            score += keyword_weight * (1.0 / (self.k + keyword_rank + 1))

        if graph_rank is not None:
            score += graph_weight * (1.0 / (self.k + graph_rank + 1))

        return score

    def compute_time_decay(
        self,
        last_accessed_at: datetime,
    ) -> float:
        """
        時間減衰を計算

        Args:
            last_accessed_at: 最終アクセス日時

        Returns:
            時間減衰スコア（[0.0, 1.0]）
        """
        now = datetime.now(timezone.utc)
        delta = now - last_accessed_at
        days_elapsed = delta.days

        recency: float = 0.5 ** (days_elapsed / self.half_life_days)
        return recency

    def fuse(
        self,
        results: list[ScoredMemory],
        strategy: SearchStrategy,
    ) -> list[dict[str, Any]]:
        """
        検索結果を統合（単一ソース用）

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
            # RRFスコア（単一ソースなので、ランクが同じ）
            rrf_raw = 1.0 / (self.k + rank + 1)

            # 複合スコア計算
            time_decay = (
                self.compute_time_decay(result.memory.last_accessed_at)
                if strategy.time_decay_enabled
                else 1.0
            )

            final_score = 0.5 * rrf_raw + 0.3 * time_decay + 0.2 * result.memory.importance_score

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
        memory_scores: dict[str, dict[str, Any]] = {}

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

            final_score = 0.5 * rrf_score + 0.3 * time_decay + 0.2 * data["memory"].importance_score

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
