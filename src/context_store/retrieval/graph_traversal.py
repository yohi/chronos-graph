"""Graph Traversal - グラフトラバーサル検索"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from context_store.models.graph import GraphResult

logger = logging.getLogger(__name__)


class GraphTraversalAdapter(Protocol):
    """GraphTraversal が依存する最小限のアダプター契約。"""

    async def traverse(self, seed_ids: list[str], edge_types: list[str], depth: int) -> GraphResult:
        """指定条件でグラフを探索する。"""
        ...


class GraphTraversal:
    """グラフトラバーサルエンジン"""

    def __init__(
        self,
        graph_adapter: GraphTraversalAdapter,
        default_depth: int = 2,
    ) -> None:
        """
        初期化

        Args:
            graph_adapter: グラフアダプター
            default_depth: デフォルトのグラフ深さ
        """
        self.graph_adapter = graph_adapter
        self.default_depth = default_depth

    async def traverse(
        self,
        seed_ids: list[UUID],
        edge_types: list[str] | None = None,
        depth: int | None = None,
    ) -> GraphResult:
        """
        グラフをトラバース

        Args:
            seed_ids: 起点ノードID
            edge_types: フィルタするエッジタイプ（Noneで全タイプ）
            depth: トラバーサルの深さ（Noneでデフォルト値）

        Returns:
            GraphResult: トラバーサル結果
        """
        if depth is None:
            depth = self.default_depth

        try:
            result: GraphResult = await self.graph_adapter.traverse(
                seed_ids=[str(sid) for sid in seed_ids],
                edge_types=edge_types or [],
                depth=depth,
            )
            return result

        except (ConnectionError, TimeoutError, OSError) as exc:
            # Graceful Degradation: 接続系の期待された障害のみ空結果に変換
            logger.warning(
                "Graph traversal failed: %s: %s. Returning empty results.",
                type(exc).__name__,
                str(exc),
                exc_info=exc,
            )
            return GraphResult(nodes=[], edges=[], traversal_depth=0)
