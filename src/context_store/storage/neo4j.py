"""Neo4j Graph Adapter using the official neo4j async driver."""

from __future__ import annotations

import logging
from typing import Any

from context_store.models.graph import Edge, GraphResult

logger = logging.getLogger(__name__)


class Neo4jGraphAdapter:
    """GraphAdapter implementation backed by Neo4j.

    All methods implement Graceful Degradation: connection/query failures are
    logged and silently ignored so that the rest of the system continues to
    function without graph capabilities.
    """

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, uri: str, user: str, password: str) -> "Neo4jGraphAdapter":
        """Create a new adapter by connecting to Neo4j."""
        import neo4j

        driver = neo4j.AsyncGraphDatabase.driver(
            uri, auth=(user, password)
        )
        return cls(driver)

    # ------------------------------------------------------------------
    # GraphAdapter Protocol
    # ------------------------------------------------------------------

    async def create_node(self, memory_id: str, metadata: dict[str, Any]) -> None:
        """Create or upsert a graph node for the given memory ID."""
        cypher = """
            MERGE (m:Memory {id: $id})
            ON CREATE SET m += $props
            ON MATCH  SET m += $props
        """
        try:
            async with self._driver.session() as session:
                await session.run(cypher, id=memory_id, props=metadata)
        except Exception as exc:
            logger.warning("Neo4j create_node failed (degraded): %s", exc)

    async def create_edge(
        self, from_id: str, to_id: str, edge_type: str, props: dict[str, Any]
    ) -> None:
        """Create a directed edge between two nodes."""
        cypher = f"""
            MATCH (a:Memory {{id: $from_id}})
            MATCH (b:Memory {{id: $to_id}})
            MERGE (a)-[r:{edge_type}]->(b)
            ON CREATE SET r += $props
            ON MATCH  SET r += $props
        """
        try:
            async with self._driver.session() as session:
                await session.run(cypher, from_id=from_id, to_id=to_id, props=props)
        except Exception as exc:
            logger.warning("Neo4j create_edge failed (degraded): %s", exc)

    async def create_edges_batch(self, edges: list[dict[str, Any]]) -> None:
        """Create multiple edges in a single UNWIND operation."""
        if not edges:
            return

        # Build per-type batches to avoid dynamic relationship type in UNWIND
        # (Neo4j does not support parameterised rel types without APOC)
        batches: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            t = edge["edge_type"]
            batches.setdefault(t, []).append(edge)

        try:
            async with self._driver.session() as session:
                for edge_type, batch in batches.items():
                    cypher = f"""
                        UNWIND $edges AS e
                        MATCH (a:Memory {{id: e.from_id}})
                        MATCH (b:Memory {{id: e.to_id}})
                        MERGE (a)-[r:{edge_type}]->(b)
                        ON CREATE SET r += e.props
                        ON MATCH  SET r += e.props
                    """
                    await session.run(cypher, edges=batch)
        except Exception as exc:
            logger.warning("Neo4j create_edges_batch failed (degraded): %s", exc)

    async def traverse(
        self, seed_ids: list[str], edge_types: list[str], depth: int
    ) -> GraphResult:
        """Traverse the graph from seed nodes up to the given depth."""
        if edge_types:
            rel_filter = "|".join(edge_types)
            rel_pattern = f"[*1..{depth}:{rel_filter}]"
        else:
            rel_pattern = f"[*1..{depth}]"

        cypher = f"""
            MATCH (start:Memory)
            WHERE start.id IN $seed_ids
            CALL {{
                WITH start
                MATCH path = (start)-{rel_pattern}-(other:Memory)
                RETURN nodes(path) AS nodes, relationships(path) AS rels
            }}
            RETURN nodes, rels
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(cypher, seed_ids=seed_ids)
                nodes: list[dict[str, Any]] = []
                edges: list[Edge] = []
                seen_node_ids: set[str] = set()
                async for record in result:
                    for node in record["nodes"]:
                        node_dict = dict(node)
                        nid = node_dict.get("id", "")
                        if nid and nid not in seen_node_ids:
                            seen_node_ids.add(nid)
                            nodes.append(node_dict)
                    for rel in record["rels"]:
                        edges.append(
                            Edge(
                                from_id=str(rel.start_node["id"]),
                                to_id=str(rel.end_node["id"]),
                                edge_type=rel.type,
                                properties=dict(rel),
                            )
                        )
        except Exception as exc:
            logger.warning("Neo4j traverse failed (degraded): %s", exc)
            return GraphResult(nodes=[], edges=[], traversal_depth=depth)

        return GraphResult(nodes=nodes, edges=edges, traversal_depth=depth)

    async def delete_node(self, memory_id: str) -> None:
        """Delete a node and all its incident edges."""
        cypher = "MATCH (m:Memory {id: $id}) DETACH DELETE m"
        try:
            async with self._driver.session() as session:
                await session.run(cypher, id=memory_id)
        except Exception as exc:
            logger.warning("Neo4j delete_node failed (degraded): %s", exc)

    async def dispose(self) -> None:
        """Close the driver."""
        await self._driver.close()
