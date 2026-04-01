"""Retrieval Pipeline - 検索パイプライン統合"""

import logging
from context_store.retrieval.query_analyzer import QueryAnalyzer
from context_store.retrieval.vector_search import VectorSearch
from context_store.retrieval.keyword_search import KeywordSearch
from context_store.retrieval.graph_traversal import GraphTraversal
from context_store.retrieval.result_fusion import ResultFusion
from context_store.retrieval.post_processor import PostProcessor
from context_store.models.memory import MemorySource
from context_store.models.search import ScoredMemory

logger = logging.getLogger(__name__)


class RetrievalPipeline:
    """検索パイプライン統合"""

    def __init__(
        self,
        query_analyzer: QueryAnalyzer,
        vector_search: VectorSearch,
        keyword_search: KeywordSearch,
        graph_traversal: GraphTraversal,
        result_fusion: ResultFusion,
        post_processor: PostProcessor,
    ):
        """
        初期化

        Args:
            query_analyzer: クエリ分析器
            vector_search: ベクトル検索エンジン
            keyword_search: キーワード検索エンジン
            graph_traversal: グラフトラバーサルエンジン
            result_fusion: 結果統合エンジン
            post_processor: 後処理
        """
        self.query_analyzer = query_analyzer
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.graph_traversal = graph_traversal
        self.result_fusion = result_fusion
        self.post_processor = post_processor

    async def search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 10,
        max_tokens: int | None = None,
    ) -> dict:
        """
        統合検索を実行

        Args:
            query: クエリ
            project: プロジェクトフィルタ
            top_k: 返す結果数
            max_tokens: 最大トークン数

        Returns:
            検索結果
        """
        # ステップ 1: クエリ分析
        strategy = self.query_analyzer.analyze(query)
        logger.info(
            f"Query analyzed. Strategy: vector={strategy.vector_weight:.2f}, "
            f"keyword={strategy.keyword_weight:.2f}, graph={strategy.graph_weight:.2f}"
        )

        # ステップ 2: 並列検索実行
        vector_results = await self._search_with_weight(
            self.vector_search.search,
            query,
            top_k,
            strategy.vector_weight,
        )

        keyword_results = await self._search_with_weight(
            self.keyword_search.search,
            query,
            top_k,
            strategy.keyword_weight,
        )

        # グラフ検索は、ベクトル検索の結果から起点を取得
        graph_results = []
        if strategy.graph_weight > 0 and vector_results:
            seed_ids = [r.memory.id for r in vector_results[:3]]  # Top 3から起点を選択
            graph_results = await self.graph_traversal.traverse(
                seed_ids=seed_ids,
                edge_types=None,
                depth=strategy.graph_depth,
            )
            # グラフ検索結果をScoredMemoryに変換（仮）
            # 実装ではStorageAdapterでメモリを取得

        logger.info(
            f"Parallel search completed. Vector: {len(vector_results)}, "
            f"Keyword: {len(keyword_results)}, Graph: {len(graph_results)}"
        )

        # ステップ 3: 結果統合
        results_dict = {
            MemorySource.VECTOR: vector_results,
            MemorySource.KEYWORD: keyword_results,
            MemorySource.GRAPH: graph_results,
        }

        fused_results = self.result_fusion.fuse_multiple_sources(results_dict, strategy)
        logger.info(f"Results fused. Total: {len(fused_results)}")

        # ステップ 4: 後処理（フィルタ、トークン制限、アクセス記録）
        # 注: ここではfused_resultsは辞書なので、簡略化
        # 実装では適切なモデル変換が必要

        return {
            "query": query,
            "strategy": {
                "vector_weight": strategy.vector_weight,
                "keyword_weight": strategy.keyword_weight,
                "graph_weight": strategy.graph_weight,
                "graph_depth": strategy.graph_depth,
                "time_decay_enabled": strategy.time_decay_enabled,
            },
            "results": fused_results[:top_k],
            "total_count": len(fused_results),
        }

    async def _search_with_weight(
        self,
        search_func,
        query: str,
        top_k: int,
        weight: float,
    ) -> list[ScoredMemory]:
        """
        重み付き検索を実行

        Args:
            search_func: 検索関数
            query: クエリ
            top_k: 結果数
            weight: 検索の重み

        Returns:
            検索結果
        """
        if weight <= 0:
            return []

        try:
            results = await search_func(query, top_k=top_k)
            return results
        except Exception as e:
            logger.error(f"Search failed: {type(e).__name__}: {str(e)}")
            return []
