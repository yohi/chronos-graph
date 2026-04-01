"""Query Analyzer のテスト"""
import pytest
from context_store.retrieval.query_analyzer import QueryAnalyzer, SearchStrategy


@pytest.fixture
def analyzer():
    """QueryAnalyzer インスタンス"""
    return QueryAnalyzer()


class TestQueryAnalyzer:
    """クエリ意図解析と戦略決定のテスト"""

    def test_code_snippet_triggers_keyword_search(self, analyzer):
        """コード片やエラーコードはキーワード検索を重視"""
        query = "TypeError: Cannot read property 'map' of undefined"
        strategy = analyzer.analyze(query)
        # keyword_weight > vector_weight, graph_weight
        assert strategy.keyword_weight >= strategy.vector_weight
        assert strategy.keyword_weight >= strategy.graph_weight

    def test_specific_error_code_keyword_search(self, analyzer):
        """エラーコード（ER_PARSE_ERROR等）はキーワード検索"""
        query = "TypeORMのエラー ER_PARSE_ERROR"
        strategy = analyzer.analyze(query)
        assert strategy.keyword_weight > 0.4

    def test_why_question_triggers_graph_search(self, analyzer):
        """「なぜ」「原因」などの質問はグラフ検索を重視"""
        query = "なぜReactからSvelteに移行した？"
        strategy = analyzer.analyze(query)
        # graph_weight が高い
        assert strategy.graph_weight >= strategy.vector_weight
        assert strategy.graph_weight >= strategy.keyword_weight

    def test_causality_question_graph_search(self, analyzer):
        """因果関係の質問はグラフ検索"""
        query = "これはどんな原因で発生している？"
        strategy = analyzer.analyze(query)
        assert strategy.graph_weight > 0.5

    def test_general_query_triggers_vector_search(self, analyzer):
        """一般的なクエリはベクトル検索を重視"""
        query = "JWT認証の実装方針"
        strategy = analyzer.analyze(query)
        # vector_weight が高い、またはバランス型
        assert strategy.vector_weight >= 0.3

    def test_time_expression_enables_decay(self, analyzer):
        """時間表現を含むクエリは時間減衰を有効化"""
        # 「先週」「去月」などの時間表現
        query = "先週決めたAPI設計"
        strategy = analyzer.analyze(query)
        assert strategy.time_decay_enabled is True

    def test_specific_time_decay_enabled(self, analyzer):
        """「昨日」「3日前」など具体的な時間表現"""
        query = "3日前に修正されたバグ"
        strategy = analyzer.analyze(query)
        assert strategy.time_decay_enabled is True

    def test_recent_time_expression(self, analyzer):
        """「最近」「今月」などの最近性表現"""
        query = "最近の議論"
        strategy = analyzer.analyze(query)
        assert strategy.time_decay_enabled is True

    def test_strategy_weights_sum_to_one(self, analyzer):
        """各戦略の重みを合計すると 1.0 に近い"""
        queries = [
            "JWT認証の実装方針",
            "TypeError: Cannot read property",
            "なぜこうなった？",
            "先週決めた設計",
        ]
        for query in queries:
            strategy = analyzer.analyze(query)
            weights_sum = strategy.vector_weight + strategy.keyword_weight + strategy.graph_weight
            # 許容誤差 0.01
            assert abs(weights_sum - 1.0) < 0.01, f"Query: {query}, Sum: {weights_sum}"

    def test_graph_depth_for_causal_queries(self, analyzer):
        """因果関係の質問はグラフ深さが深い"""
        query = "なぜこれが発生したのか？"
        strategy = analyzer.analyze(query)
        # graph_depth >= 2
        assert strategy.graph_depth >= 2

    def test_default_graph_depth(self, analyzer):
        """デフォルトのグラフ深さ"""
        query = "JWT認証"
        strategy = analyzer.analyze(query)
        # デフォルトは 1〜2
        assert 1 <= strategy.graph_depth <= 3

    def test_graph_depth_why_question(self, analyzer):
        """「なぜ」の質問は深いグラフ検索"""
        query = "なぜこの仕様に決めたのか？"
        strategy = analyzer.analyze(query)
        assert strategy.graph_depth >= 2

    def test_multiple_keyword_patterns(self, analyzer):
        """複数のキーワードパターンが検出される"""
        query = "ERROR: Connection timeout in database"
        strategy = analyzer.analyze(query)
        # キーワード検索を重視
        assert strategy.keyword_weight >= 0.3
