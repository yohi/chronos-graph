"""Graph Traversal - グラフトラバーサル検索"""

import logging
from typing import Any
from uuid import UUID

from context_store.models.graph import GraphResult

logger = logging.getLogger(__name__)


class GraphTraversal:
    """グラフトラバーサルエンジン"""

    def __init__(
        self,
        graph_adapter: Any,
        default_depth: int = 2,
        fanout_limit: int = 100,
        max_physical_hops: int = 50,
    ):
        """
        初期化

        Args:
            graph_adapter: グラフアダプター
            default_depth: デフォルトのグラフ深さ
            fanout_limit: 各ノードからのエッジ展開上限
            max_physical_hops: 物理的な最大ホップ数
        """
        self.graph_adapter = graph_adapter
        self.default_depth = default_depth
        self.fanout_limit = fanout_limit
        self.max_physical_hops = max_physical_hops

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

        except Exception as e:
            # Graceful Degradation: グラフ検索失敗時は空結果を返す
            logger.warning(
                f"Graph traversal failed: {type(e).__name__}: {str(e)}. Returning empty results."
            )
            return GraphResult(nodes=[], edges=[], traversal_depth=0)
