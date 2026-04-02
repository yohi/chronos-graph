"""Retrieval Pipeline - 検索パイプライン統合"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypedDict

from context_store.models.memory import MemorySource, ScoredMemory
from context_store.retrieval.graph_traversal import GraphTraversal
from context_store.retrieval.keyword_search import KeywordSearch
from context_store.retrieval.post_processor import PostProcessor
from context_store.retrieval.query_analyzer import QueryAnalyzer
from context_store.retrieval.result_fusion import ResultFusion
from context_store.retrieval.vector_search import VectorSearch
from context_store.storage.protocols import StorageAdapter

logger = logging.getLogger(__name__)


class RetrievalResponse(TypedDict):
    query: str
    strategy: dict[str, Any]
    results: list[dict[str, Any]]
    total_count: int

SearchFunc = Callable[..., Awaitable[list[ScoredMemory]]]



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
        storage_adapter: StorageAdapter,
    ):
        self.query_analyzer = query_analyzer
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.graph_traversal = graph_traversal
        self.result_fusion = result_fusion
        self.post_processor = post_processor
        self.storage_adapter = storage_adapter

    async def search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 10,
        max_tokens: int | None = None,
    ) -> RetrievalResponse:
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

        # ステップ 2: ベクトル検索とキーワード検索を並列実行
        vector_task = self._safe_search(self.vector_search.search, query, top_k, strategy.vector_weight)
        keyword_task = self._safe_search(self.keyword_search.search, query, top_k, strategy.keyword_weight)
        vector_results, keyword_results = await asyncio.gather(vector_task, keyword_task)

        # ステップ 3: グラフ検索（ベクトル結果の上位3件を起点に実行）
        graph_memories: list[ScoredMemory] = []
        if strategy.graph_weight > 0 and vector_results:
            seed_ids = [r.memory.id for r in vector_results[:3]]
            graph_result = await self.graph_traversal.traverse(
                seed_ids=seed_ids,
                edge_types=None,
                depth=strategy.graph_depth,
            )
            # GraphResult のノードからメモリを取得し ScoredMemory に変換
            if graph_result.nodes:
                graph_memories = await self._resolve_graph_nodes(graph_result.nodes)

        logger.info(
            f"Search completed. Vector: {len(vector_results)}, "
            f"Keyword: {len(keyword_results)}, Graph: {len(graph_memories)}"
        )

        # ステップ 4: 結果統合 (RRF)
        results_dict: dict[MemorySource, list[ScoredMemory]] = {
            MemorySource.VECTOR: vector_results,
            MemorySource.KEYWORD: keyword_results,
            MemorySource.GRAPH: graph_memories,
        }
        fused = self.result_fusion.fuse_multiple_sources(results_dict, strategy)

        # ステップ 5: fused_results を ScoredMemory に戻す（ID で lookup）
        all_memories: dict[str, ScoredMemory] = {
            str(m.memory.id): m
            for src in results_dict.values()
            for m in src
        }
        scored: list[ScoredMemory] = []
        for item in fused[:top_k]:
            base = all_memories.get(item["memory_id"])
            if base:
                scored.append(base)

        # ステップ 6: 後処理（プロジェクトフィルタ・トークン制限・アクセス記録更新）
        scored = await self.post_processor.process(
            results=scored,
            project=project,
            max_tokens=max_tokens,
        )

        return {
            "query": query,
            "strategy": {
                "vector_weight": strategy.vector_weight,
                "keyword_weight": strategy.keyword_weight,
                "graph_weight": strategy.graph_weight,
                "graph_depth": strategy.graph_depth,
                "time_decay_enabled": strategy.time_decay_enabled,
            },
            "results": [
                {"memory_id": str(m.memory.id), "content": m.memory.content, "score": m.score}
                for m in scored
            ],
            "total_count": len(fused),
        }

    async def _safe_search(
        self,
        search_func: SearchFunc,
        query: str,
        top_k: int,
        weight: float,
    ) -> list[ScoredMemory]:
        """重みが 0 のソースをスキップし、例外を空リストに変換"""
        if weight <= 0:
            return []
        try:
            results: list[ScoredMemory] = list(await search_func(query, top_k=top_k))
            return results
        except Exception as e:
            logger.error("Search failed (%s): %s", getattr(search_func, "__qualname__", repr(search_func)), e)
            return []

    async def _resolve_graph_nodes(
        self,
        nodes: list[dict[str, Any]],
    ) -> list[ScoredMemory]:
        """GraphResult のノードリストから Memory を取得し ScoredMemory に変換"""
        results: list[ScoredMemory] = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            memory = await self.storage_adapter.get_memory(node_id)
            if memory:
                results.append(
                    ScoredMemory(
                        memory=memory,
                        score=float(node.get("score", 0.5)),
                        source=MemorySource.GRAPH,
                    )
                )
        return results
