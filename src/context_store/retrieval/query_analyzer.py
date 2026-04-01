"""Query Analyzer - クエリ意図解析と検索戦略決定"""

import re
from dataclasses import dataclass


@dataclass
class SearchStrategy:
    """検索戦略"""

    vector_weight: float  # ベクトル検索の重み
    keyword_weight: float  # キーワード検索の重み
    graph_weight: float  # グラフ検索の重み
    graph_depth: int  # グラフトラバーサルの深さ
    time_decay_enabled: bool  # 時間減衰の有効化


class QueryAnalyzer:
    """クエリの意図を解析し、最適な検索戦略を決定"""

    # パターンマッチング用の正規表現
    ERROR_PATTERNS = [
        r"(ERROR|WARN|Exception|Error|TypeError|SyntaxError|ValueError)",
        r"(ENOENT|ECONNREFUSED|ETIMEDOUT|ER_\w+|ORA-\d+)",
        r":\s*[A-Z][\w\s]+",  # "Error: message"
    ]

    CAUSALITY_PATTERNS = [
        r"(なぜ|どうして|原因|理由|何故)",
        r"(why|cause|reason|how did)",
    ]

    TIME_PATTERNS = [
        r"(昨日|今日|明日|先週|来週|先月|今月|来月|最近|最近の)",
        r"(\d+\s*日?前|先\s*\d+\s*日)",
        r"(yesterday|today|tomorrow|last\s+week|next\s+week|last\s+month|recently)",
        r"(\d+\s*days?\s+ago|previous\s+week)",
    ]

    def __init__(self):
        """初期化"""
        self._error_regex = self._compile_patterns(self.ERROR_PATTERNS)
        self._causality_regex = self._compile_patterns(self.CAUSALITY_PATTERNS)
        self._time_regex = self._compile_patterns(self.TIME_PATTERNS)

    @staticmethod
    def _compile_patterns(patterns: list[str]) -> re.Pattern:
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
        # パターンマッチング
        has_error = bool(self._error_regex.search(query))
        has_causality = bool(self._causality_regex.search(query))
        has_time = bool(self._time_regex.search(query))

        # デフォルト戦略（ベクトル検索重視）
        vector_weight = 0.5
        keyword_weight = 0.2
        graph_weight = 0.3
        graph_depth = 2
        time_decay_enabled = has_time

        # パターンに基づいて戦略を調整
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

        # 時間表現がある場合は時間減衰を有効化
        if has_time:
            time_decay_enabled = True

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
            time_decay_enabled=time_decay_enabled,
        )
