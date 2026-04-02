"""Graph Linker: 記憶間のリレーションシップを自動推定してエッジを作成する。

エッジタイプ:
- SEMANTICALLY_RELATED: ベクトル類似度 >= 0.70
- TEMPORAL_NEXT/PREV: 同一セッション/プロジェクトの時系列リンク
- SUPERSEDES: Append-only 置換時（新記憶 → 旧記憶）
- REFERENCES: URL/ファイルパス抽出からリンク
- CHUNK_NEXT/PREV: 同一ドキュメント内の連続チャンクをリンク

すべてのエッジは create_edges_batch でバルクインサート（N+1問題回避）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from context_store.models.memory import Memory
from context_store.storage.protocols import GraphAdapter, StorageAdapter

logger = logging.getLogger(__name__)

# SEMANTICALLY_RELATED の閾値
SEMANTIC_RELATION_THRESHOLD = 0.70

# URL と ファイルパスの検出パターン
_URL_PATTERN = re.compile(
    r"https?://[^\s\"\'<>()\[\]{}]+?(?<![.,!?:;)\]}'\"])",
    re.IGNORECASE,
)
_FILE_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"\(])(/(?:[a-zA-Z0-9_\-./]+))",
    re.MULTILINE,
)


class EdgeType:
    """グラフエッジのタイプ定数。"""

    SEMANTICALLY_RELATED = "SEMANTICALLY_RELATED"
    TEMPORAL_NEXT = "TEMPORAL_NEXT"
    TEMPORAL_PREV = "TEMPORAL_PREV"
    SUPERSEDES = "SUPERSEDES"
    REFERENCES = "REFERENCES"
    CHUNK_NEXT = "CHUNK_NEXT"
    CHUNK_PREV = "CHUNK_PREV"


class GraphLinker:
    """記憶間のリレーションシップを推定してグラフに登録する。"""

    def __init__(self, storage: StorageAdapter, graph: GraphAdapter) -> None:
        self._storage = storage
        self._graph = graph

    async def link(
        self,
        new_memory: Memory,
        *,
        previous_memories: list[Memory] | None = None,
        supersedes: Memory | None = None,
        chunk_neighbors: dict[str, list[Memory]] | None = None,
    ) -> None:
        """新しい記憶に対してエッジ候補を推定し、バルクインサートする。

        Args:
            new_memory: 新しく追加された記憶
            previous_memories: 同一セッション/プロジェクトの直前の記憶リスト
            supersedes: Append-only 置換で置き換えられた旧記憶
            chunk_neighbors: document_id → 同一ドキュメントのチャンクリスト
        """
        edges: list[dict[str, Any]] = []

        # 1. SEMANTICALLY_RELATED エッジ
        edges.extend(await self._build_semantic_edges(new_memory))

        # 2. TEMPORAL_NEXT/PREV エッジ
        if previous_memories:
            edges.extend(self._build_temporal_edges(new_memory, previous_memories))

        # 3. SUPERSEDES エッジ
        if supersedes:
            edges.extend(self._build_supersedes_edges(new_memory, supersedes))

        # 4. REFERENCES エッジ（URL/ファイルパス抽出）
        edges.extend(self._build_reference_stubs(new_memory))

        # 5. CHUNK_NEXT/PREV エッジ
        if chunk_neighbors:
            edges.extend(self._build_chunk_edges(new_memory, chunk_neighbors))

        # バルクインサート（N+1問題回避）
        await self._graph.create_edges_batch(edges)

        logger.debug(
            "Graph Linker: memory_id=%s に %d 件のエッジを作成",
            new_memory.id,
            len(edges),
        )

    async def _build_semantic_edges(self, new_memory: Memory) -> list[dict[str, Any]]:
        """ベクトル類似度 >= 0.70 の記憶に SEMANTICALLY_RELATED エッジを作成する。"""
        if not new_memory.embedding:
            return []

        similar_memories = await self._storage.vector_search(
            embedding=new_memory.embedding,
            top_k=10,
            project=new_memory.project,
        )

        edges: list[dict[str, Any]] = []
        for scored in similar_memories:
            if scored.score >= SEMANTIC_RELATION_THRESHOLD:
                # 自己参照を避ける
                if scored.memory.id == new_memory.id:
                    continue
                edges.append(
                    {
                        "from_id": str(new_memory.id),
                        "to_id": str(scored.memory.id),
                        "edge_type": EdgeType.SEMANTICALLY_RELATED,
                        "props": {"similarity": scored.score},
                    }
                )
        return edges

    def _build_temporal_edges(
        self, new_memory: Memory, previous_memories: list[Memory]
    ) -> list[dict[str, Any]]:
        """同一セッション/プロジェクトの時系列リンクを作成する。"""
        edges: list[dict[str, Any]] = []

        new_session = new_memory.source_metadata.get("session_id")
        new_project = new_memory.project

        for prev in previous_memories:
            # セッションID一致チェック
            prev_session = prev.source_metadata.get("session_id")

            if new_session and prev_session and new_session == prev_session:
                # TEMPORAL_NEXT: prev → new
                edges.append(
                    {
                        "from_id": str(prev.id),
                        "to_id": str(new_memory.id),
                        "edge_type": EdgeType.TEMPORAL_NEXT,
                        "props": {},
                    }
                )
                # TEMPORAL_PREV: new → prev
                edges.append(
                    {
                        "from_id": str(new_memory.id),
                        "to_id": str(prev.id),
                        "edge_type": EdgeType.TEMPORAL_PREV,
                        "props": {},
                    }
                )
            elif (
                not new_session
                and not prev_session
                and new_project
                and prev.project
                and new_project == prev.project
            ):
                # セッションIDがない場合はプロジェクトで判断
                edges.append(
                    {
                        "from_id": str(prev.id),
                        "to_id": str(new_memory.id),
                        "edge_type": EdgeType.TEMPORAL_NEXT,
                        "props": {},
                    }
                )
                edges.append(
                    {
                        "from_id": str(new_memory.id),
                        "to_id": str(prev.id),
                        "edge_type": EdgeType.TEMPORAL_PREV,
                        "props": {},
                    }
                )

        return edges

    def _build_supersedes_edges(
        self, new_memory: Memory, supersedes: Memory
    ) -> list[dict[str, Any]]:
        """Append-only 置換時の SUPERSEDES エッジを作成する。

        新ノード → 旧ノード の方向。
        """
        return [
            {
                "from_id": str(new_memory.id),
                "to_id": str(supersedes.id),
                "edge_type": EdgeType.SUPERSEDES,
                "props": {},
            }
        ]

    def _build_reference_stubs(self, new_memory: Memory) -> list[dict[str, Any]]:
        """コンテンツ内の URL/ファイルパスを検出してスタブエッジを記録する。

        実際の参照先ノードが存在する場合にのみ有効になる。
        現時点では参照URLをメタデータとして props に記録する。
        """
        edges: list[dict[str, Any]] = []
        content = new_memory.content

        # URLの検出
        urls = _URL_PATTERN.findall(content)
        for url in urls:
            edges.append(
                {
                    "from_id": str(new_memory.id),
                    "to_id": f"url:{url}",  # 実際のノードIDに解決される前のスタブ
                    "edge_type": EdgeType.REFERENCES,
                    "props": {"reference_url": url, "stub": True},
                }
            )

        # ファイルパスの検出（最低3セグメント以上のパスのみ）
        file_paths = _FILE_PATH_PATTERN.findall(content)
        for path in file_paths:
            if path.count("/") >= 2:  # /a/b 以上のパス
                edges.append(
                    {
                        "from_id": str(new_memory.id),
                        "to_id": f"file:{path}",
                        "edge_type": EdgeType.REFERENCES,
                        "props": {"reference_path": path, "stub": True},
                    }
                )

        return edges

    def _build_chunk_edges(
        self, new_memory: Memory, chunk_neighbors: dict[str, list[Memory]]
    ) -> list[dict[str, Any]]:
        """同一ドキュメント内の連続チャンク間の CHUNK_NEXT/PREV エッジを作成する。"""
        edges: list[dict[str, Any]] = []

        doc_id = new_memory.source_metadata.get("document_id")
        if not doc_id:
            return []

        doc_id_str = str(doc_id)
        if doc_id_str not in chunk_neighbors:
            return []

        chunks = chunk_neighbors[doc_id_str]
        # chunk_index でソート
        sorted_chunks = sorted(
            chunks,
            key=self._get_chunk_index,
        )

        for i in range(len(sorted_chunks) - 1):
            curr = sorted_chunks[i]
            next_chunk = sorted_chunks[i + 1]

            # CHUNK_NEXT: curr → next
            edges.append(
                {
                    "from_id": str(curr.id),
                    "to_id": str(next_chunk.id),
                    "edge_type": EdgeType.CHUNK_NEXT,
                    "props": {"document_id": doc_id_str},
                }
            )
            # CHUNK_PREV: next → curr
            edges.append(
                {
                    "from_id": str(next_chunk.id),
                    "to_id": str(curr.id),
                    "edge_type": EdgeType.CHUNK_PREV,
                    "props": {"document_id": doc_id_str},
                }
            )

        return edges

    @staticmethod
    def _get_chunk_index(memory: Memory) -> int:
        """source_metadata の chunk_index を int に正規化する。"""
        raw_value = memory.source_metadata.get("chunk_index", 0)
        if isinstance(raw_value, bool):
            return int(raw_value)
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            return int(raw_value)
        if isinstance(raw_value, str):
            try:
                return int(raw_value)
            except ValueError:
                return 0
        try:
            return int(str(raw_value))
        except (TypeError, ValueError):
            return 0
