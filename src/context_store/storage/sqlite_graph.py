"""SQLite Graph Adapter using adjacency-table + recursive CTE traversal.

Schema
------
memory_nodes  : stores graph node metadata (memory_id → metadata JSON).
memory_edges  : stores directed edges (from_id, to_id, edge_type, props JSON).

Traversal
---------
Uses recursive CTEs with dual-depth tracking:
- physical_depth: increments on every hop (hard-limit guard against runaway).
- logical_depth : only increments for non-SUPERSEDES edges.

Timeouts
--------
``graph_traversal_timeout_seconds`` controls query execution.
aiosqlite runs SQLite on a background thread; asyncio.wait_for cannot stop
the thread.  To interrupt the underlying sqlite3 connection we use
``SafeSqliteInterruptCtx`` from utils.sqlite_interrupt, which safely calls
``Connection.interrupt()`` only while a query is actually running.
On timeout, a partial (possibly empty) GraphResult is returned — no exception.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncGenerator

import aiosqlite

from context_store.models.graph import Edge, GraphResult
from context_store.utils.sqlite_interrupt import SafeSqliteInterruptCtx

if TYPE_CHECKING:
    from context_store.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_NODES = """
CREATE TABLE IF NOT EXISTS memory_nodes (
    id       TEXT PRIMARY KEY,
    metadata TEXT NOT NULL DEFAULT '{}'
);
"""

_DDL_EDGES = """
CREATE TABLE IF NOT EXISTS memory_edges (
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    props     TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (from_id, to_id, edge_type)
);
"""

_DDL_EDGES_IDX = """
CREATE INDEX IF NOT EXISTS memory_edges_to_idx ON memory_edges (to_id);
CREATE INDEX IF NOT EXISTS memory_edges_type_idx ON memory_edges (edge_type);
"""


# ---------------------------------------------------------------------------
# SQLiteGraphAdapter
# ---------------------------------------------------------------------------


class SQLiteGraphAdapter:
    """GraphAdapter backed by SQLite adjacency table + recursive CTE.

    Shares the same DB file as :class:`~context_store.storage.sqlite.SQLiteStorageAdapter`.
    PRAGMAs are expected to have already been applied by the storage adapter;
    this adapter applies them again on each connection for safety.
    """

    def __init__(self, db_path: str, settings: "Settings") -> None:
        self._db_path = db_path
        self._settings = settings
        self._disposed = False
        self._max_logical_depth: int = settings.graph_max_logical_depth
        self._max_physical_hops: int = settings.graph_max_physical_hops
        self._timeout: float = settings.graph_traversal_timeout_seconds

    # ------------------------------------------------------------------
    # Factory / lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables if they do not exist."""
        async with self._connect() as conn:
            await conn.execute(_DDL_NODES)
            await conn.execute(_DDL_EDGES)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS memory_edges_to_idx ON memory_edges (to_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS memory_edges_type_idx ON memory_edges (edge_type)"
            )
            await conn.commit()

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA synchronous=NORMAL")
            yield conn

    async def dispose(self) -> None:
        """Release resources (idempotent)."""
        self._disposed = True

    # ------------------------------------------------------------------
    # GraphAdapter: create_node
    # ------------------------------------------------------------------

    async def create_node(self, memory_id: str, metadata: dict[str, Any]) -> None:
        """Create or upsert a graph node."""
        meta_json = json.dumps(metadata)
        async with self._connect() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO memory_nodes (id, metadata) VALUES (?, ?)",
                (memory_id, meta_json),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # GraphAdapter: create_edge
    # ------------------------------------------------------------------

    async def create_edge(
        self, from_id: str, to_id: str, edge_type: str, props: dict[str, Any]
    ) -> None:
        """Create a directed edge (idempotent — duplicate is ignored)."""
        props_json = json.dumps(props)
        async with self._connect() as conn:
            await conn.execute(
                """
                INSERT OR IGNORE INTO memory_edges (from_id, to_id, edge_type, props)
                VALUES (?, ?, ?, ?)
                """,
                (from_id, to_id, edge_type, props_json),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # GraphAdapter: create_edges_batch
    # ------------------------------------------------------------------

    async def create_edges_batch(self, edges: list[dict[str, Any]]) -> None:
        """Insert multiple edges in a single transaction (N+1 prevention)."""
        if not edges:
            return
        rows = [
            (
                e["from_id"],
                e["to_id"],
                e["edge_type"],
                json.dumps(e.get("props") or {}),
            )
            for e in edges
        ]
        async with self._connect() as conn:
            await conn.executemany(
                """
                INSERT OR IGNORE INTO memory_edges (from_id, to_id, edge_type, props)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # GraphAdapter: traverse
    # ------------------------------------------------------------------

    async def traverse(self, seed_ids: list[str], edge_types: list[str], depth: int) -> GraphResult:
        """Traverse the graph using a recursive CTE.

        Args:
            seed_ids:   Starting node IDs.
            edge_types: Edge type allow-list; empty means all types.
            depth:      Maximum *logical* traversal depth (SUPERSEDES edges
                        do not consume logical depth).  Clamped to
                        ``graph_max_logical_depth``.

        Returns:
            GraphResult with reachable nodes and edges.
            On timeout, returns the partial result accumulated so far
            (possibly empty) — never raises.
        """
        if not seed_ids:
            return GraphResult(nodes=[], edges=[], traversal_depth=0)

        effective_depth = min(depth, self._max_logical_depth)
        partial_container: list[GraphResult] = []

        try:
            async with self._connect() as conn:
                raw_conn = getattr(conn, "_conn", None)
                if raw_conn is None:
                    raise RuntimeError(
                        "aiosqlite._conn attribute not found; interrupt-based timeout unavailable"
                    )

                ctx = SafeSqliteInterruptCtx(raw_conn)

                result = await asyncio.wait_for(
                    self._traverse_inner(
                        conn, ctx, seed_ids, edge_types, effective_depth, partial_container
                    ),
                    timeout=self._timeout,
                )
                return result
        except asyncio.TimeoutError:
            ctx.interrupt()
            logger.warning(
                "graph_traversal_timeout: traversal from seeds=%s "
                "exceeded %.2fs; returning partial result.",
                seed_ids,
                self._timeout,
            )
            if partial_container:
                res = partial_container[0]
                res.partial = True
                res.timeout = True
                return res
            return GraphResult(nodes=[], edges=[], traversal_depth=0, partial=True, timeout=True)

    async def _traverse_inner(
        self,
        conn: aiosqlite.Connection,
        ctx: SafeSqliteInterruptCtx,
        seed_ids: list[str],
        edge_types: list[str],
        effective_depth: int,
        partial_container: list[GraphResult],
    ) -> GraphResult:
        """Execute the recursive CTE traversal query."""
        return await self._run_traversal(
            conn, ctx, seed_ids, edge_types, effective_depth, partial_container
        )

    async def _run_traversal(
        self,
        conn: aiosqlite.Connection,
        ctx: SafeSqliteInterruptCtx,
        seed_ids: list[str],
        edge_types: list[str],
        effective_depth: int,
        partial_container: list[GraphResult],
    ) -> GraphResult:
        """Build and execute a recursive CTE; return GraphResult.

        The CTE dual-depth strategy:
        - physical_depth: always +1 per hop (guard against cycle / runaway).
        - logical_depth : +1 per hop UNLESS the edge_type is 'SUPERSEDES'.

        Stopping conditions:
        - logical_depth >= effective_depth
        - physical_depth >= graph_max_physical_hops
        - cycle detection via visited_ids (comma-separated path string)
        """
        seed_placeholders = ",".join("?" * len(seed_ids))

        # Build edge-type filter fragment
        if edge_types:
            et_placeholders = ",".join("?" * len(edge_types))
            edge_type_filter = f"AND e.edge_type IN ({et_placeholders})"
            edge_type_params: list[Any] = list(edge_types)
        else:
            edge_type_filter = ""
            edge_type_params = []

        # Parameters: [seed_ids..., effective_depth, max_physical_hops,
        #              edge_type_params..., effective_depth, max_physical_hops,
        #              seed_ids... (for final SELECT)]
        # We construct this carefully below.

        seed_params: list[Any] = list(seed_ids)

        sql = f"""
        WITH RECURSIVE graph_cte(
            node_id,
            from_id,
            to_id,
            edge_type,
            props,
            logical_depth,
            physical_depth,
            visited_ids
        ) AS (
            -- Base: seed nodes (no edges yet)
            SELECT
                n.id      AS node_id,
                NULL      AS from_id,
                NULL      AS to_id,
                NULL      AS edge_type,
                NULL      AS props,
                0         AS logical_depth,
                0         AS physical_depth,
                json_array(n.id) AS visited_ids
            FROM memory_nodes n
            WHERE n.id IN ({seed_placeholders})

            UNION

            -- Recursive: follow edges
            SELECT
                e.to_id   AS node_id,
                e.from_id AS from_id,
                e.to_id   AS to_id,
                e.edge_type,
                e.props,
                CASE
                    WHEN e.edge_type = 'SUPERSEDES' THEN cte.logical_depth
                    ELSE cte.logical_depth + 1
                END       AS logical_depth,
                cte.physical_depth + 1 AS physical_depth,
                json_insert(cte.visited_ids, '$[' || json_array_length(cte.visited_ids) || ']', e.to_id) AS visited_ids
            FROM graph_cte cte
            JOIN memory_edges e ON e.from_id = cte.node_id
            WHERE
                -- logical depth guard (SUPERSEDES doesn't consume depth)
                CASE
                    WHEN e.edge_type = 'SUPERSEDES' THEN cte.logical_depth
                    ELSE cte.logical_depth + 1
                END <= ?
                -- physical hop guard
                AND cte.physical_depth + 1 <= ?
                -- cycle guard
                AND e.to_id NOT IN (SELECT value FROM json_each(cte.visited_ids))
                {edge_type_filter}
        )
        SELECT DISTINCT
            cte.node_id,
            n.metadata,
            cte.from_id,
            cte.to_id,
            cte.edge_type,
            cte.props,
            cte.logical_depth,
            cte.physical_depth
        FROM graph_cte cte
        LEFT JOIN memory_nodes n ON n.id = cte.node_id
        """

        params: list[Any] = (
            seed_params + [effective_depth, self._max_physical_hops] + edge_type_params
        )

        # We pass ctx from outside now
        rows: list[Any] = []
        max_physical_reached = False
        cursor = None

        try:
            async with ctx:
                async with conn.execute(sql, params) as cursor:
                    async for row in cursor:
                        rows.append(row)
        except (Exception, asyncio.CancelledError) as exc:
            logger.debug(
                "Query execution failed or interrupted. sql=%s, params=%s, ctx=%s, cursor=%s, error=%s",
                sql,
                params,
                ctx,
                cursor,
                exc,
                exc_info=True,
            )

        # --- Parse results ---
        node_map: dict[str, dict[str, Any]] = {}
        edge_set: dict[tuple[str, str, str], Edge] = {}
        max_logical = 0

        for row in rows:
            rd = dict(row)
            node_id: str = rd["node_id"]
            physical_depth: int = rd.get("physical_depth") or 0
            logical_depth: int = rd.get("logical_depth") or 0

            if physical_depth >= self._max_physical_hops:
                max_physical_reached = True

            # Collect node
            if node_id not in node_map:
                meta: dict[str, Any] = {}
                if rd.get("metadata"):
                    try:
                        meta = json.loads(rd["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                meta["id"] = node_id
                node_map[node_id] = meta

            max_logical = max(max_logical, logical_depth)

            # Collect edge (skip seed rows where from_id is NULL)
            if rd.get("from_id") and rd.get("to_id") and rd.get("edge_type"):
                key = (rd["from_id"], rd["to_id"], rd["edge_type"])
                if key not in edge_set:
                    props: dict[str, Any] = {}
                    if rd.get("props"):
                        try:
                            props = json.loads(rd["props"])
                        except (json.JSONDecodeError, TypeError):
                            props = {}
                    edge_set[key] = Edge(
                        from_id=rd["from_id"],
                        to_id=rd["to_id"],
                        edge_type=rd["edge_type"],
                        properties=props,
                    )

        if max_physical_reached:
            logger.warning(
                "Physical hops limit (%d) reached during graph traversal. "
                "Result may be incomplete.",
                self._max_physical_hops,
            )

        res = GraphResult(
            nodes=list(node_map.values()),
            edges=list(edge_set.values()),
            traversal_depth=max_logical,
        )
        partial_container.append(res)
        return res

    # ------------------------------------------------------------------
    # GraphAdapter: delete_node
    # ------------------------------------------------------------------

    async def delete_node(self, memory_id: str) -> None:
        """Delete a node and all its incident edges."""
        async with self._connect() as conn:
            # Remove incident edges first (avoids FK issues if enabled)
            await conn.execute(
                "DELETE FROM memory_edges WHERE from_id = ? OR to_id = ?",
                (memory_id, memory_id),
            )
            await conn.execute(
                "DELETE FROM memory_nodes WHERE id = ?",
                (memory_id,),
            )
            await conn.commit()
