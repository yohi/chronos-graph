"""Retrieval Pipeline - 検索パイプライン統合."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypedDict

from context_store.models.memory import MemorySource, ScoredMemory
from context_store.models.search import SearchStrategy
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


def _coerce_graph_score(raw_score: Any) -> float:
    """グラフノード由来の score を安全に float へ変換する。"""
    score = 0.5
    if isinstance(raw_score, (int, float)):
        score = float(raw_score)
    elif isinstance(raw_score, str):
        try:
            score = float(raw_score)
        except ValueError:
            score = 0.5
    return max(0.0, min(1.0, score))


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
    ) -> None:
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
        strategy: SearchStrategy | None = None,
    ) -> RetrievalResponse:
        """
        統合検索を実行

        Args:
            query: クエリ
            project: プロジェクトフィルタ
            top_k: 返す結果数
            max_tokens: 最大トークン数
            strategy: 検索戦略 (None の場合は QueryAnalyzer で生成)

        Returns:
            検索結果
        """
        # ステップ 0: 入力バリデーションとクランプ
        if not isinstance(top_k, int) or top_k < 1:
            top_k = 10
        if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
            max_tokens = None

        # ステップ 1: クエリ分析
        if strategy is None:
            strategy = self.query_analyzer.analyze(query)
            logger.info(
                "Query analyzed. Strategy: vector=%0.2f, keyword=%0.2f, graph=%0.2f",
                strategy.vector_weight,
                strategy.keyword_weight,
                strategy.graph_weight,
            )
        else:
            logger.info(
                "Using provided strategy. Strategy: vector=%0.2f, keyword=%0.2f, graph=%0.2f",
                strategy.vector_weight,
                strategy.keyword_weight,
                strategy.graph_weight,
            )

        # ステップ 2: ベクトル検索とキーワード検索を並列実行
        vector_task = self._safe_search(
            self.vector_search.search, query, top_k, strategy.vector_weight
        )
        keyword_task = self._safe_search(
            self.keyword_search.search, query, top_k, strategy.keyword_weight
        )
        vector_results, keyword_results = await asyncio.gather(vector_task, keyword_task)

        # ステップ 3: グラフ検索 (ベクトル結果の上位3件を起点に実行)
        graph_memories: list[ScoredMemory] = []
        if strategy.graph_weight > 0 and vector_results:
            seed_ids = [r.memory.id for r in vector_results[:3]]
            try:
                graph_result = await self.graph_traversal.traverse(
                    seed_ids=seed_ids,
                    edge_types=None,
                    depth=strategy.graph_depth,
                )
                # GraphResult のノードからメモリを取得し ScoredMemory に変換
                if graph_result.nodes:
                    graph_memories = await self._resolve_graph_nodes(graph_result.nodes)
            except Exception as exc:
                logger.error("Graph traversal failed: %s", exc, exc_info=True)
                # グラフ検索失敗時は空リストのまま続行 (degraded behavior)

        logger.info(
            "Search completed. Vector: %d, Keyword: %d, Graph: %d",
            len(vector_results),
            len(keyword_results),
            len(graph_memories),
        )

        # ステップ 4: 結果統合 (RRF)
        results_dict: dict[MemorySource, list[ScoredMemory]] = {
            MemorySource.VECTOR: vector_results,
            MemorySource.KEYWORD: keyword_results,
            MemorySource.GRAPH: graph_memories,
        }
        fused = self.result_fusion.fuse_multiple_sources(results_dict, strategy)

        # ステップ 5: fused_results を ScoredMemory に戻す (ID で lookup)
        all_memories: dict[str, ScoredMemory] = {
            str(m.memory.id): m for src in results_dict.values() for m in src
        }
        filtered = self._filter_fused_by_project(fused, all_memories, project)
        scored: list[ScoredMemory] = []
        for item in filtered[:top_k]:
            base = all_memories.get(item["memory_id"])
            if base:
                scored.append(
                    ScoredMemory(
                        memory=base.memory,
                        score=float(item["final_score"]),
                        source=base.source,
                    )
                )

        # ステップ 6: 後処理 (トークン制限・アクセス記録更新)
        scored = await self.post_processor.process(
            results=scored,
            project=None,  # すでに _filter_fused_by_project でフィルタ済み
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
            "total_count": len(filtered),
        }

    def _filter_fused_by_project(
        self,
        fused: list[dict[str, Any]],
        all_memories: dict[str, ScoredMemory],
        project: str | None,
    ) -> list[dict[str, Any]]:
        """project フィルタを top_k 適用前の fused 結果へ反映する。"""
        if project is None:
            return fused
        return [
            item
            for item in fused
            if (base := all_memories.get(item["memory_id"])) is not None
            and base.memory.project == project
        ]

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
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                "Search failed (%s, type=%s): %s",
                getattr(search_func, "__qualname__", repr(search_func)),
                type(e).__name__,
                e,
                exc_info=True,
            )
            return []

    async def _resolve_graph_nodes(
        self,
        nodes: list[dict[str, Any]],
    ) -> list[ScoredMemory]:
        """GraphResult のノードリストから Memory を取得し ScoredMemory に変換"""
        node_ids = [str(node.get("id", "")) for node in nodes if str(node.get("id", ""))]
        memory_by_id: dict[str, Any] = {}
        if node_ids:
            batch_memories = await self.storage_adapter.get_memories_batch(node_ids)
            memory_by_id = {str(memory.id): memory for memory in batch_memories}

        results: list[ScoredMemory] = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            if not node_id:
                continue
            memory = memory_by_id.get(node_id)
            if memory:
                results.append(
                    ScoredMemory(
                        memory=memory,
                        score=_coerce_graph_score(node.get("score")),
                        source=MemorySource.GRAPH,
                    )
                )
        return results
