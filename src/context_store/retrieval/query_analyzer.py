"""Query Analyzer - クエリ意図解析と検索戦略決定"""

import re
from typing import Pattern

from context_store.models.search import SearchStrategy

__all__ = ["QueryAnalyzer", "SearchStrategy"]


class QueryAnalyzer:
    """クエリの意図を解析し、最適な検索戦略を決定"""

    # パターンマッチング用の正規表現
    ERROR_PATTERNS: tuple[str, ...] = (
        r"(ERROR|WARN|Exception|Error|TypeError|SyntaxError|ValueError)",
        r"(ENOENT|ECONNREFUSED|ETIMEDOUT|ER_\w+|ORA-\d+)",
    )

    CAUSALITY_PATTERNS: tuple[str, ...] = (
        r"(なぜ|どうして|原因|理由|何故)",
        r"(why|cause|reason|how did)",
    )

    TIME_PATTERNS: tuple[str, ...] = (
        r"(昨日|今日|明日|先週|来週|先月|今月|来月|最近|最近の)",
        r"(\d+\s*日?前|先\s*\d+\s*日)",
        r"(yesterday|today|tomorrow|last\s+week|next\s+week|last\s+month|recently)",
        r"(\d+\s*days?\s+ago|previous\s+week)",
    )

    def __init__(self) -> None:
        """初期化"""
        self._error_regex = self._compile_patterns(self.ERROR_PATTERNS)
        self._causality_regex = self._compile_patterns(self.CAUSALITY_PATTERNS)
        self._time_regex = self._compile_patterns(self.TIME_PATTERNS)

    @staticmethod
    def _compile_patterns(patterns: tuple[str, ...]) -> Pattern[str]:
        """複数のパターンを1つの正規表現に結合"""
        combined = "|".join(f"({p})" for p in patterns)
        return re.compile(combined, re.IGNORECASE)

    def analyze(self, query: str) -> SearchStrategy:
        """
        クエリを分析し、検索戦略を決定

        Args:
            query: ユーザーのクエリ

        Returns:
            SearchStrategy: 検索戦略
        """
        has_error = bool(self._error_regex.search(query))
        has_causality = bool(self._causality_regex.search(query))
        has_time = bool(self._time_regex.search(query))

        # デフォルト戦略（ベクトル検索重視）
        vector_weight = 0.5
        keyword_weight = 0.2
        graph_weight = 0.3
        graph_depth = 2

        if has_error:
            # エラー/コード片 → キーワード検索重視
            vector_weight = 0.2
            keyword_weight = 0.6
            graph_weight = 0.2
            graph_depth = 1
        elif has_causality:
            # 因果関係 → グラフ検索重視
            vector_weight = 0.2
            keyword_weight = 0.1
            graph_weight = 0.7
            graph_depth = 3

        # 重みを正規化（合計が1.0になるように）
        weights_sum = vector_weight + keyword_weight + graph_weight
        if weights_sum > 0:
            vector_weight /= weights_sum
            keyword_weight /= weights_sum
            graph_weight /= weights_sum

        return SearchStrategy(
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
            graph_weight=graph_weight,
            graph_depth=graph_depth,
            time_decay_enabled=has_time,
        )
