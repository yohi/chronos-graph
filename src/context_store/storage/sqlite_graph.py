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
import urllib.parse
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
    PRIMARY KEY (from_id, to_id, edge_type),
    FOREIGN KEY(from_id) REFERENCES memory_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(to_id) REFERENCES memory_nodes(id) ON DELETE CASCADE
);
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

    def __init__(self, db_path: str, settings: "Settings", *, read_only: bool = False) -> None:
        self._db_path = db_path
        self._settings = settings
        self._read_only = read_only
        self._disposed = False
        self._max_logical_depth: int = settings.graph_max_logical_depth
        self._max_physical_hops: int = settings.graph_max_physical_hops
        self._timeout: float = settings.graph_traversal_timeout_seconds

    # ------------------------------------------------------------------
    # Factory / lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables if they do not exist."""
        if self._read_only:
            # Skip schema creation for read-only mode
            return
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
        if not self._db_path:
            raise ValueError(
                "SQLite DB path is not set (received None or empty). "
                "Ensure sqlite_db_path is provided in Settings."
            )
        if self._read_only:
            encoded_path = urllib.parse.quote(self._db_path, safe="/:")
            async with aiosqlite.connect(f"file:{encoded_path}?mode=ro", uri=True) as conn:
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA busy_timeout=5000")
                yield conn
        else:
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
                """
                INSERT INTO memory_nodes (id, metadata) VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET metadata = excluded.metadata
                """,
                (memory_id, meta_json),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # GraphAdapter: create_edge
    # ------------------------------------------------------------------

    async def create_edge(
        self, from_id: str, to_id: str, edge_type: str, props: dict[str, Any]
    ) -> None:
        """Create a directed edge (idempotent — duplicate is ignored).

        Requires both nodes to exist (enforced by FOREIGN KEY constraints).
        """
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
                # NOTE: We access the private '_conn' attribute of aiosqlite.Connection
                # to obtain the underlying sqlite3.Connection. This is required for
                # low-level interrupt handling (sqlite3_interrupt). This dependency
                # on aiosqlite internals should be revisited if aiosqlite provides
                # an official API for accessing the raw connection or for
                # interrupt-based query cancellation.
                raw_conn = getattr(conn, "_conn", None)
                if raw_conn is None:
                    raise RuntimeError(
                        "aiosqlite._conn attribute not found; interrupt-based timeout unavailable"
                    )

                ctx = SafeSqliteInterruptCtx(raw_conn)

                async with ctx:
                    try:
                        result = await asyncio.wait_for(
                            self._traverse_inner(
                                conn, ctx, seed_ids, edge_types, effective_depth, partial_container
                            ),
                            timeout=self._timeout,
                        )
                        return result
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        if partial_container:
                            res = partial_container[0]
                            res.partial = True
                            res.timeout = True
                        ctx.interrupt()
                        raise
        except asyncio.TimeoutError:
            logger.warning(
                "graph_traversal_timeout: traversal from seed_count=%d "
                "exceeded %.2fs; returning partial result.",
                len(seed_ids),
                self._timeout,
            )
            if partial_container:
                return partial_container[0]
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

    def _parse_rows_to_graph_result(self, rows: list[Any]) -> GraphResult:
        """Helper to convert raw SQL rows into a GraphResult."""
        node_map: dict[str, dict[str, Any]] = {}
        edge_set: dict[tuple[str, str, str], Edge] = {}
        max_logical = 0
        max_physical_reached = False

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
                "Physical hops limit (%d) reached during graph traversal.",
                self._max_physical_hops,
            )

        return GraphResult(
            nodes=list(node_map.values()),
            edges=list(edge_set.values()),
            traversal_depth=max_logical,
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
        """Build and execute a recursive CTE; return GraphResult."""
        seed_placeholders = ",".join("?" * len(seed_ids))

        # Build edge-type filter fragment
        if edge_types:
            et_placeholders = ",".join("?" * len(edge_types))
            edge_type_filter = f"AND e.edge_type IN ({et_placeholders})"
            edge_type_params: list[Any] = list(edge_types)
        else:
            edge_type_filter = ""
            edge_type_params = []

        seed_params: list[Any] = list(seed_ids)

        sql_template = """
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
            WHERE n.id IN (__SEED_IDS__)

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
                json_insert(
                    cte.visited_ids,
                    '$[' || json_array_length(cte.visited_ids) || ']',
                    e.to_id
                ) AS visited_ids
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
        sql = sql_template.replace("__SEED_IDS__", seed_placeholders).format(
            edge_type_filter=edge_type_filter
        )

        params: list[Any] = [
            *seed_params,
            effective_depth,
            self._max_physical_hops,
            *edge_type_params,
        ]

        rows: list[Any] = []
        cursor = None

        try:
            async with conn.execute(sql, params) as cursor:
                async for row in cursor:
                    rows.append(row)
                    # Regularly update partial result if requested
                    if len(rows) % 100 == 0:
                        partial_container.clear()
                        partial_container.append(self._parse_rows_to_graph_result(rows))
        except asyncio.CancelledError:
            # On cancel, still try to save what we have
            if rows:
                partial_container.clear()
                partial_container.append(self._parse_rows_to_graph_result(rows))
            raise
        except Exception:
            # Sanitize params for logging
            safe_params = [f"<{type(p).__name__}>" for p in params]
            logger.exception(
                "Query execution failed. seed_count=%d, params_summary=%s",
                len(seed_ids),
                safe_params,
            )
            if rows:
                partial_container.clear()
                partial_container.append(self._parse_rows_to_graph_result(rows))
            raise

        res = self._parse_rows_to_graph_result(rows)
        partial_container.clear()
        partial_container.append(res)
        return res

    # ------------------------------------------------------------------
    # GraphAdapter: delete_node
    # ------------------------------------------------------------------

    async def delete_node(self, memory_id: str) -> None:
        """Delete a node and all its incident edges.

        Incident edges are automatically removed via FOREIGN KEY ON DELETE CASCADE,
        but we explicitly delete them here for double-safety and clarity.
        """
        async with self._connect() as conn:
            await conn.execute(
                "DELETE FROM memory_edges WHERE from_id = ? OR to_id = ?",
                (memory_id, memory_id),
            )
            await conn.execute(
                "DELETE FROM memory_nodes WHERE id = ?",
                (memory_id,),
            )
            await conn.commit()

    # ------------------------------------------------------------------
    # Dashboard graph queries (PR 3)
    # ------------------------------------------------------------------

    async def list_edges_for_memories(self, memory_ids: list[str]) -> list[Edge]:
        """Return all edges where BOTH endpoints are in ``memory_ids``.

        For large input lists that exceed SQLite's parameter limit (999),
        implementations MUST chunk the query internally (rev.10 §3.5).
        """
        if not memory_ids:
            return []

        ids_set = set(memory_ids)
        unique_ids = list(ids_set)
        # SQLite parameter limit (999) への対策
        CHUNK_SIZE = 900
        all_edges: list[Edge] = []

        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            for i in range(0, len(unique_ids), CHUNK_SIZE):
                chunk = unique_ids[i : i + CHUNK_SIZE]
                placeholders = ",".join("?" * len(chunk))
                sql_template = """
                    SELECT from_id, to_id, edge_type, props
                    FROM memory_edges
                    WHERE from_id IN (__PLACEHOLDERS__)
                """
                query = sql_template.replace("__PLACEHOLDERS__", placeholders)
                async with conn.execute(query, chunk) as cursor:
                    rows = await cursor.fetchall()

                for row in rows:
                    if row["to_id"] in ids_set:
                        all_edges.append(
                            Edge(
                                from_id=row["from_id"],
                                to_id=row["to_id"],
                                edge_type=row["edge_type"],
                                properties=json.loads(row["props"]) if row["props"] else {},
                            )
                        )
        return all_edges

    async def list_all_edges(self) -> list[Edge]:
        """Return all edges in the graph."""
        all_edges: list[Edge] = []
        async with self._connect() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT from_id, to_id, edge_type, props FROM memory_edges"
            ) as cursor:
                async for row in cursor:
                    all_edges.append(
                        Edge(
                            from_id=row["from_id"],
                            to_id=row["to_id"],
                            edge_type=row["edge_type"],
                            properties=json.loads(row["props"]) if row["props"] else {},
                        )
                    )
        return all_edges

    async def count_edges(self) -> int:
        """Return the total number of edges in the graph."""
        async with self._connect() as conn:
            async with conn.execute("SELECT COUNT(*) FROM memory_edges") as cursor:
                row = await cursor.fetchone()
                return int(row[0]) if row else 0
