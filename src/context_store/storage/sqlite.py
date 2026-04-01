"""SQLite Storage Adapter using aiosqlite + sqlite-vec + FTS5."""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID

import aiosqlite

from context_store.config import Settings
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.protocols import MemoryFilters, StorageError
from context_store.utils.stale_lock import StaleAwareFileLock

# ---------------------------------------------------------------------------
# sqlite-vec integration
# ---------------------------------------------------------------------------

try:
    import sqlite_vec as _sqlite_vec  # type: ignore

    _USE_SQLITE_VEC_SERIALIZE = True
except ImportError:  # pragma: no cover
    _sqlite_vec = None
    _USE_SQLITE_VEC_SERIALIZE = False


def encode_embedding(embedding: list[float]) -> bytes:
    """Convert a float list to a sqlite-vec BLOB.

    Uses ``sqlite_vec.serialize_float32`` when available; falls back to
    ``struct.pack`` for portability.
    """
    if _USE_SQLITE_VEC_SERIALIZE and _sqlite_vec is not None:
        from typing import cast

        return cast(bytes, _sqlite_vec.serialize_float32(embedding))
    return struct.pack("<" + "f" * len(embedding), *embedding)


def decode_embedding(blob: bytes) -> list[float]:
    """Decode a sqlite-vec BLOB back to a Python float list (float32 precision)."""
    n = len(blob) // 4
    return list(struct.unpack("<" + "f" * n, blob))


def validate_embedding(
    embedding: list[float],
    expected_dim: int | None = None,
) -> None:
    """Validate an embedding vector.

    Raises:
        StorageError: If the embedding contains NaN/Inf or has the wrong dimension.
    """
    for v in embedding:
        if math.isnan(v):
            raise StorageError(
                "Embedding contains NaN values",
                code="INVALID_EMBEDDING",
                recoverable=False,
            )
        if math.isinf(v):
            raise StorageError(
                "Embedding contains Inf values",
                code="INVALID_EMBEDDING",
                recoverable=False,
            )
    if expected_dim is not None and len(embedding) != expected_dim:
        raise StorageError(
            f"Embedding dimension mismatch: expected {expected_dim}, got {len(embedding)}",
            code="DIMENSION_MISMATCH",
            recoverable=False,
        )


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id              TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    memory_type     TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_metadata TEXT NOT NULL DEFAULT '{}',
    semantic_relevance REAL NOT NULL DEFAULT 0.5,
    importance_score   REAL NOT NULL DEFAULT 0.5,
    access_count       INTEGER NOT NULL DEFAULT 0,
    last_accessed_at   TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    archived_at        TEXT,
    tags               TEXT NOT NULL DEFAULT '[]',
    project            TEXT
);
"""

_DDL_VECTORS_METADATA = """
CREATE TABLE IF NOT EXISTS vectors_metadata (
    dimension INTEGER NOT NULL UNIQUE
);
"""

_DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content=memories,
    content_rowid=rowid
);
"""

# Triggers to keep FTS in sync
_DDL_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS memories_ai
AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad
AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au
AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""

_DDL_EMBEDDINGS = """
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Row <-> Memory conversion helpers
# ---------------------------------------------------------------------------


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _row_to_memory(row: dict[str, Any], embedding: list[float] | None = None) -> Memory:
    tags: list[str] = json.loads(row.get("tags") or "[]")
    source_metadata: dict[str, object] = json.loads(row.get("source_metadata") or "{}")
    archived_at = _parse_dt(row.get("archived_at"))
    last_accessed_at = _parse_dt(row["last_accessed_at"]) or datetime.now(timezone.utc)
    created_at = _parse_dt(row["created_at"]) or datetime.now(timezone.utc)
    updated_at = _parse_dt(row["updated_at"]) or datetime.now(timezone.utc)

    return Memory(
        id=UUID(row["id"]),
        content=row["content"],
        memory_type=MemoryType(row["memory_type"]),
        source_type=SourceType(row["source_type"]),
        source_metadata=source_metadata,
        embedding=embedding if embedding is not None else [],
        semantic_relevance=float(row.get("semantic_relevance") or 0.5),
        importance_score=float(row.get("importance_score") or 0.5),
        access_count=int(row.get("access_count") or 0),
        last_accessed_at=last_accessed_at,
        created_at=created_at,
        updated_at=updated_at,
        archived_at=archived_at,
        tags=tags,
        project=row.get("project"),
    )


# ---------------------------------------------------------------------------
# SQLite Storage Adapter
# ---------------------------------------------------------------------------


class SQLiteStorageAdapter:
    """StorageAdapter backed by SQLite with sqlite-vec vector search and FTS5."""

    def __init__(self, db_path: str, settings: Settings) -> None:
        self._db_path = db_path
        self._settings = settings
        self._disposed = False

        # Back-pressure control
        self._semaphore = asyncio.Semaphore(settings.sqlite_max_concurrent_connections)
        self._waiting_lock = asyncio.Lock()
        self._waiting_count: int = 0
        self._max_queued = settings.sqlite_max_queued_requests
        self._acquire_timeout = settings.sqlite_acquire_timeout

        # Cached vector dimension (avoids repeated DB queries)
        self._vector_dim: int | None = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, settings: Settings) -> "SQLiteStorageAdapter":
        """Create and initialise the adapter (runs schema migration)."""
        db_path = os.path.expanduser(settings.sqlite_db_path)
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        adapter = cls(db_path, settings)
        lock = StaleAwareFileLock(
            f"{db_path}.lock",
            timeout=settings.sqlite_acquire_timeout,
            stale_timeout_seconds=settings.stale_lock_timeout_seconds,
        )
        with lock:
            await adapter._migrate()
        return adapter

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Open a raw aiosqlite connection with required PRAGMAs."""
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            # Apply required PRAGMAs
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA synchronous=NORMAL")
            # Load sqlite-vec extension
            if _sqlite_vec is not None:
                await conn.enable_load_extension(True)
                await conn.load_extension(_sqlite_vec.loadable_path())
                await conn.enable_load_extension(False)
            yield conn

    # ------------------------------------------------------------------
    # Back-pressure semaphore context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _with_semaphore(self) -> AsyncGenerator[None, None]:
        """Acquire the semaphore with back-pressure control.

        Capacity model:
        - ``max_concurrent`` semaphore slots (active requests)
        - ``max_queued`` requests may wait for a semaphore slot
        - Total tolerated = max_concurrent + max_queued

        Algorithm (TOCTOU-safe):
        1. Under Lock, check if _waiting_count >= max_queued → STORAGE_BUSY immediately.
        2. Increment _waiting_count under Lock (this request now occupies a queue slot).
        3. asyncio.wait_for(semaphore.acquire(), timeout=acquire_timeout).
        4. On successful acquire, decrement _waiting_count under Lock (no longer queued).
        5. On acquire failure (timeout), decrement _waiting_count under Lock in finally.
        6. After yield, release the semaphore.

        This ensures ``_waiting_count`` tracks only requests waiting for the semaphore,
        while the semaphore itself tracks active requests, giving the correct total of
        ``max_concurrent + max_queued`` admitted requests at any point in time.
        """
        # Step 1 & 2: gate check + enqueue (TOCTOU-safe)
        async with self._waiting_lock:
            if self._waiting_count >= self._max_queued:
                raise StorageError(
                    f"Storage busy: too many queued requests ({self._waiting_count})",
                    code="STORAGE_BUSY",
                    recoverable=True,
                )
            self._waiting_count += 1

        acquired = False
        try:
            # Step 3: acquire with timeout
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=self._acquire_timeout,
                )
                acquired = True
            except asyncio.TimeoutError as exc:
                raise StorageError(
                    "Storage busy: semaphore acquire timed out",
                    code="STORAGE_BUSY",
                    recoverable=True,
                ) from exc
            finally:
                # Step 4/5: decrement _waiting_count once acquire attempt is resolved
                # (regardless of success or failure) to free the queue slot.
                async with self._waiting_lock:
                    self._waiting_count -= 1

            # Step 6: run caller code while holding the semaphore
            yield
        finally:
            if acquired:
                self._semaphore.release()

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    async def _migrate(self) -> None:
        """Create tables and indexes if they do not exist."""
        async with self._connect() as conn:
            await conn.execute(_DDL_MEMORIES)
            await conn.execute(_DDL_VECTORS_METADATA)
            await conn.execute(_DDL_EMBEDDINGS)
            await conn.executescript(_DDL_FTS + _DDL_FTS_TRIGGERS)
            await conn.commit()

        # Warm the dimension cache
        self._vector_dim = await self._load_vector_dim()

    async def _load_vector_dim(self) -> int | None:
        async with self._connect() as conn:
            async with conn.execute("SELECT dimension FROM vectors_metadata LIMIT 1") as cursor:
                row = await cursor.fetchone()
        return int(row["dimension"]) if row else None

    # ------------------------------------------------------------------
    # Locked DB operation wrapper
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _db(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Semaphore-guarded connection context manager."""
        self._ensure_not_disposed()
        async with self._with_semaphore():
            async with self._connect() as conn:
                yield conn

    def _ensure_not_disposed(self) -> None:
        if self._disposed:
            raise RuntimeError("storage disposed")

    # ------------------------------------------------------------------
    # StorageAdapter: save_memory
    # ------------------------------------------------------------------

    async def save_memory(self, memory: Memory) -> str:
        """Persist a memory and return its string ID."""
        embedding = memory.embedding
        dim = len(embedding) if embedding else None

        # Validate embedding if present
        if embedding:
            validate_embedding(embedding)
            # Dimension consistency check
            if self._vector_dim is not None and dim != self._vector_dim:
                raise StorageError(
                    f"Embedding dimension mismatch: expected {self._vector_dim}, got {dim}",
                    code="DIMENSION_MISMATCH",
                    recoverable=False,
                )

        async with self._db() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO memories (
                        id, content, memory_type, source_type, source_metadata,
                        semantic_relevance, importance_score, access_count,
                        last_accessed_at, created_at, updated_at, archived_at,
                        tags, project
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(memory.id),
                        memory.content,
                        memory.memory_type.value,
                        memory.source_type.value,
                        json.dumps(memory.source_metadata),
                        memory.semantic_relevance,
                        memory.importance_score,
                        memory.access_count,
                        _dt_to_str(memory.last_accessed_at),
                        _dt_to_str(memory.created_at),
                        _dt_to_str(memory.updated_at),
                        _dt_to_str(memory.archived_at),
                        json.dumps(memory.tags),
                        memory.project,
                    ),
                )

                # Store embedding if present
                if embedding:
                    blob = encode_embedding(embedding)
                    await conn.execute(
                        "INSERT INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
                        (str(memory.id), blob),
                    )
                    # Update dimension metadata if this is the first embedding
                    if self._vector_dim is None:
                        await conn.execute(
                            "INSERT OR IGNORE INTO vectors_metadata (dimension) VALUES (?)",
                            (dim,),
                        )
                        self._vector_dim = dim

                await conn.commit()
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

        return str(memory.id)

    # ------------------------------------------------------------------
    # StorageAdapter: get_memory
    # ------------------------------------------------------------------

    async def get_memory(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by ID."""
        async with self._db() as conn:
            try:
                async with conn.execute(
                    "SELECT * FROM memories WHERE id = ?", (memory_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    return None
                row_dict = dict(row)

                # Load embedding
                async with conn.execute(
                    "SELECT embedding FROM memory_embeddings WHERE memory_id = ?",
                    (memory_id,),
                ) as ecursor:
                    erow = await ecursor.fetchone()
                embedding = decode_embedding(bytes(erow["embedding"])) if erow else []
                return _row_to_memory(row_dict, embedding)
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: delete_memory
    # ------------------------------------------------------------------

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory. Returns True if deleted, False if not found."""
        async with self._db() as conn:
            try:
                async with conn.execute(
                    "SELECT id FROM memories WHERE id = ?", (memory_id,)
                ) as cursor:
                    exists = await cursor.fetchone()
                if exists is None:
                    return False
                await conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                await conn.commit()
                return True
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: update_memory
    # ------------------------------------------------------------------

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        """Apply partial updates. Returns True on success, False if not found."""
        if not updates:
            return False

        allowed_columns = {
            "content",
            "memory_type",
            "source_type",
            "source_metadata",
            "semantic_relevance",
            "importance_score",
            "access_count",
            "last_accessed_at",
            "updated_at",
            "archived_at",
            "tags",
            "project",
        }

        set_parts: list[str] = []
        params: list[Any] = []
        for col, val in updates.items():
            if col not in allowed_columns:
                continue
            # Serialise special types
            if col == "tags" and isinstance(val, list):
                val = json.dumps(val)
            elif col == "source_metadata" and isinstance(val, dict):
                val = json.dumps(val)
            elif col in ("last_accessed_at", "updated_at", "archived_at") and isinstance(
                val, datetime
            ):
                val = _dt_to_str(val)
            set_parts.append(f"{col} = ?")
            params.append(val)

        if not set_parts:
            return False

        params.append(memory_id)

        async with self._db() as conn:
            try:
                async with conn.execute(
                    f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ?",
                    params,
                ) as cursor:
                    updated = cursor.rowcount

                if updated == 0:
                    return False

                # FTS is maintained by triggers for INSERT/DELETE/UPDATE OF content,
                # but we need to manually handle content update because we do a generic UPDATE.
                # The trigger memories_au fires on UPDATE OF content, so this is handled.
                await conn.commit()
                return True
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: vector_search
    # ------------------------------------------------------------------

    async def vector_search(
        self, embedding: list[float], top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Search by cosine similarity via sqlite-vec."""
        if not embedding:
            return []
        if _sqlite_vec is None:  # pragma: no cover
            return []

        validate_embedding(embedding)

        query_blob = encode_embedding(embedding)

        async with self._db() as conn:
            try:
                # Use vec_distance_cosine for similarity scoring
                if project is not None:
                    sql = """
                        SELECT m.*, me.embedding,
                               (1.0 - vec_distance_cosine(me.embedding, ?)) AS score
                        FROM memories m
                        JOIN memory_embeddings me ON me.memory_id = m.id
                        WHERE m.archived_at IS NULL
                          AND m.project = ?
                        ORDER BY score DESC
                        LIMIT ?
                    """
                    params: tuple[Any, ...] = (query_blob, project, top_k)
                else:
                    sql = """
                        SELECT m.*, me.embedding,
                               (1.0 - vec_distance_cosine(me.embedding, ?)) AS score
                        FROM memories m
                        JOIN memory_embeddings me ON me.memory_id = m.id
                        WHERE m.archived_at IS NULL
                        ORDER BY score DESC
                        LIMIT ?
                    """
                    params = (query_blob, top_k)

                async with conn.execute(sql, params) as cursor:
                    rows = await cursor.fetchall()

                results: list[ScoredMemory] = []
                for row in rows:
                    row_dict = dict(row)
                    score = float(row_dict.pop("score", 0.0))
                    emb_blob = row_dict.pop("embedding", None)
                    emb = decode_embedding(bytes(emb_blob)) if emb_blob else []
                    memory = _row_to_memory(row_dict, emb)
                    results.append(
                        ScoredMemory(memory=memory, score=score, source=MemorySource.VECTOR)
                    )
                return results
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: keyword_search
    # ------------------------------------------------------------------

    async def keyword_search(
        self, query: str, top_k: int, project: str | None = None
    ) -> list[ScoredMemory]:
        """Full-text search using FTS5."""
        async with self._db() as conn:
            try:
                if project is not None:
                    sql = """
                        SELECT m.*, me.embedding, (-bm25(memories_fts)) AS score
                        FROM memories_fts f
                        JOIN memories m ON m.rowid = f.rowid
                        LEFT JOIN memory_embeddings me ON me.memory_id = m.id
                        WHERE memories_fts MATCH ?
                          AND m.archived_at IS NULL
                          AND m.project = ?
                        ORDER BY score DESC
                        LIMIT ?
                    """
                    params_kw: tuple[Any, ...] = (query, project, top_k)
                else:
                    sql = """
                        SELECT m.*, me.embedding, (-bm25(memories_fts)) AS score
                        FROM memories_fts f
                        JOIN memories m ON m.rowid = f.rowid
                        LEFT JOIN memory_embeddings me ON me.memory_id = m.id
                        WHERE memories_fts MATCH ?
                          AND m.archived_at IS NULL
                        ORDER BY score DESC
                        LIMIT ?
                    """
                    params_kw = (query, top_k)

                async with conn.execute(sql, params_kw) as cursor:
                    rows = await cursor.fetchall()

                results: list[ScoredMemory] = []
                for row in rows:
                    row_dict = dict(row)
                    score = float(row_dict.pop("score", 0.0))
                    emb_blob = row_dict.pop("embedding", None)
                    emb = decode_embedding(bytes(emb_blob)) if emb_blob else []
                    memory = _row_to_memory(row_dict, emb)
                    results.append(
                        ScoredMemory(memory=memory, score=score, source=MemorySource.KEYWORD)
                    )
                return results
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: list_by_filter
    # ------------------------------------------------------------------

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if filters.archived is None:
            conditions.append("archived_at IS NULL")
        elif filters.archived is True:
            conditions.append("archived_at IS NOT NULL")
        # archived=False → both active and archived, no condition

        if filters.project is not None:
            params.append(filters.project)
            conditions.append("project = ?")

        if filters.memory_type is not None:
            params.append(filters.memory_type)
            conditions.append("memory_type = ?")

        if filters.tags:
            # SQLite JSON tag matching: check if any tag is present
            tag_conditions = []
            for tag in filters.tags:
                params.append(f'%"{tag}"%')
                tag_conditions.append("tags LIKE ?")
            conditions.append("(" + " OR ".join(tag_conditions) + ")")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        prefixed_where = ""
        if where_clause:
            prefixed_where = where_clause
            replacements = {
                "archived_at IS NULL": "m.archived_at IS NULL",
                "archived_at IS NOT NULL": "m.archived_at IS NOT NULL",
                "project = ?": "m.project = ?",
                "memory_type = ?": "m.memory_type = ?",
                "tags LIKE ?": "m.tags LIKE ?",
            }
            for original, prefixed in replacements.items():
                prefixed_where = prefixed_where.replace(original, prefixed)
        sql = (
            "SELECT m.*, me.embedding "
            "FROM memories m "
            "LEFT JOIN memory_embeddings me ON me.memory_id = m.id "
            f"{prefixed_where} "
            "ORDER BY m.created_at DESC"
        )

        async with self._db() as conn:
            try:
                async with conn.execute(sql, params) as cursor:
                    rows = await cursor.fetchall()
                memories: list[Memory] = []
                for row in rows:
                    row_dict = dict(row)
                    emb_blob = row_dict.pop("embedding", None)
                    emb = decode_embedding(bytes(emb_blob)) if emb_blob else []
                    memories.append(_row_to_memory(row_dict, emb))
                return memories
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    # ------------------------------------------------------------------
    # StorageAdapter: get_vector_dimension
    # ------------------------------------------------------------------

    async def get_vector_dimension(self) -> int | None:
        """Return the stored vector dimension."""
        if self._vector_dim is not None:
            return self._vector_dim
        self._vector_dim = await self._load_vector_dim()
        return self._vector_dim

    # ------------------------------------------------------------------
    # StorageAdapter: dispose
    # ------------------------------------------------------------------

    async def dispose(self) -> None:
        """Release all resources (idempotent)."""
        if self._disposed:
            return
        self._disposed = True
        # aiosqlite connections are context-managed; nothing persistent to close.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _raise_if_locked(exc: aiosqlite.OperationalError) -> None:
    """Re-raise as StorageError if this is a 'database is locked' error."""
    msg = str(exc).lower()
    if "database is locked" in msg or "locked" in msg or "busy" in msg:
        raise StorageError(
            f"Storage busy: {exc}",
            code="STORAGE_BUSY",
            recoverable=True,
        ) from exc
