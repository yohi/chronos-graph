"""SQLite Storage Adapter using aiosqlite + sqlite-vec + FTS5."""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID

import aiosqlite

from context_store.config import Settings
from context_store.models.memory import Memory, MemorySource, MemoryType, ScoredMemory, SourceType
from context_store.storage.migrations.runner import MigrationRunner
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters, StorageError
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
    return dt.astimezone(timezone.utc).isoformat()


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

    def __init__(self, db_path: str, settings: Settings, *, read_only: bool = False) -> None:
        self._db_path = db_path
        self._settings = settings
        self._read_only = read_only
        self._disposed = False

        # Back-pressure control
        self._semaphore = asyncio.Semaphore(settings.sqlite_max_concurrent_connections)
        self._waiting_lock = asyncio.Lock()
        self._waiting_count: int = 0
        self._max_queued = settings.sqlite_max_queued_requests
        self._acquire_timeout = settings.sqlite_acquire_timeout

        # Cached vector dimension (avoids repeated DB queries)
        self._vector_dim: int | None = None
        # Dedicated executor to ensure acquire/release happen on the same thread
        self._lock_executor = ThreadPoolExecutor(max_workers=1)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, settings: Settings, *, read_only: bool = False) -> "SQLiteStorageAdapter":
        """Create and initialise the adapter (runs schema migration)."""
        db_path = os.path.expanduser(settings.sqlite_db_path)
        if not read_only:
            os.makedirs(
                os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True
            )
        adapter = cls(db_path, settings, read_only=read_only)
        try:
            if not read_only:
                lock = StaleAwareFileLock(
                    f"{db_path}.lock",
                    timeout=settings.sqlite_acquire_timeout,
                    stale_timeout_seconds=settings.stale_lock_timeout_seconds,
                )
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(adapter._lock_executor, lock.acquire)
                try:
                    await adapter._migrate()
                finally:
                    await loop.run_in_executor(adapter._lock_executor, lock.release)
        except Exception:
            await adapter.dispose()
            raise
        return adapter

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Open a raw aiosqlite connection with required PRAGMAs."""
        if self._read_only:
            encoded_path = urllib.parse.quote(self._db_path, safe="/:")
            async with aiosqlite.connect(f"file:{encoded_path}?mode=ro", uri=True) as conn:
                conn.row_factory = aiosqlite.Row
                await conn.execute("PRAGMA busy_timeout=5000")
                # Load sqlite-vec extension
                if _sqlite_vec is not None:
                    await conn.enable_load_extension(True)
                    await conn.load_extension(_sqlite_vec.loadable_path())
                    await conn.enable_load_extension(False)
                yield conn
        else:
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
        """Apply schema migrations."""
        async with self._connect() as conn:
            runner = MigrationRunner("sqlite", conn)
            await runner.run()

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

    async def get_memories_batch(self, memory_ids: list[str]) -> list[Memory]:
        """Retrieve multiple memories by ID efficiently."""
        if not memory_ids:
            return []

        # Unique IDs to avoid redundant fetching
        unique_ids = list(dict.fromkeys(memory_ids))
        all_found: dict[str, Memory] = {}

        # Chunk to respect SQLite parameter limit (default ~999)
        chunk_size = 900
        async with self._db() as conn:
            for i in range(0, len(unique_ids), chunk_size):
                chunk = unique_ids[i : i + chunk_size]
                placeholders = ", ".join("?" * len(chunk))
                sql_template = """
                    SELECT m.*, me.embedding
                    FROM memories m
                    LEFT JOIN memory_embeddings me ON me.memory_id = m.id
                    WHERE m.id IN (__PLACEHOLDERS__)
                """
                sql = sql_template.replace("__PLACEHOLDERS__", placeholders)
                try:
                    async with conn.execute(sql, chunk) as cursor:
                        rows = await cursor.fetchall()
                    for row in rows:
                        row_dict = dict(row)
                        emb_blob = row_dict.pop("embedding", None)
                        emb = decode_embedding(bytes(emb_blob)) if emb_blob else []
                        all_found[row_dict["id"]] = _row_to_memory(row_dict, emb)
                except aiosqlite.OperationalError as exc:
                    _raise_if_locked(exc)
                    raise

        # Return in the original order, omitting missing ones
        return [all_found[mid] for mid in memory_ids if mid in all_found]

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
            "embedding",
        }

        set_parts: list[str] = []
        params: list[Any] = []
        embedding: list[float] | None = None

        for col, val in updates.items():
            if col not in allowed_columns:
                continue

            if col == "embedding":
                if val is not None:
                    if not isinstance(val, list) or not all(
                        isinstance(v, (int, float)) for v in val
                    ):
                        raise StorageError("Invalid embedding", code="INVALID_PARAMETER")
                    if not val:
                        raise StorageError("Empty embedding not allowed", code="INVALID_PARAMETER")
                embedding = val
                continue

            # Serialise and validate special types
            if col in ("tags", "source_metadata"):
                if isinstance(val, str):
                    try:
                        parsed = json.loads(val)
                        if col == "tags" and not isinstance(parsed, list):
                            raise StorageError(
                                f"Invalid tags type: expected list, got {type(parsed).__name__}",
                                code="INVALID_PARAMETER",
                            )
                        if col == "source_metadata" and not isinstance(parsed, dict):
                            raise StorageError(
                                f"Invalid source_metadata type: "
                                f"expected dict, got {type(parsed).__name__}",
                                code="INVALID_PARAMETER",
                            )
                    except json.JSONDecodeError as exc:
                        raise StorageError(
                            f"Invalid JSON for {col}: {exc}",
                            code="INVALID_PARAMETER",
                        ) from exc
                else:
                    # Not a string, must be the actual object
                    if col == "tags" and not isinstance(val, list):
                        raise StorageError(
                            f"Invalid tags type: expected list, got {type(val).__name__}",
                            code="INVALID_PARAMETER",
                        )
                    if col == "source_metadata" and not isinstance(val, dict):
                        raise StorageError(
                            f"Invalid source_metadata type: "
                            f"expected dict, got {type(val).__name__}",
                            code="INVALID_PARAMETER",
                        )
                    try:
                        val = json.dumps(val)
                    except (TypeError, ValueError) as exc:
                        raise StorageError(
                            f"Failed to serialise {col}: {exc}",
                            code="INVALID_PARAMETER",
                        ) from exc
            elif col in ("last_accessed_at", "updated_at", "archived_at") and isinstance(
                val, datetime
            ):
                val = _dt_to_str(val)
            set_parts.append(f"{col} = ?")
            params.append(val)

        if not set_parts and embedding is None:
            return False

        async with self._db() as conn:
            try:
                updated = 0
                if set_parts:
                    params.append(memory_id)
                    async with conn.execute(
                        f"UPDATE memories SET {', '.join(set_parts)} WHERE id = ?",  # noqa: S608
                        params,
                    ) as cursor:
                        updated = cursor.rowcount

                    if updated == 0:
                        return False

                if embedding is not None:
                    # Explicitly validate type and elements
                    if not isinstance(embedding, list) or not all(
                        isinstance(v, (int, float)) for v in embedding
                    ):
                        raise StorageError("Invalid embedding", code="INVALID_PARAMETER")

                    # Unconditionally check if memory exists before inserting embedding
                    # to avoid FK violations
                    async with conn.execute(
                        "SELECT 1 FROM memories WHERE id = ?", (memory_id,)
                    ) as cursor:
                        if not await cursor.fetchone():
                            return False

                    # Validate dimension
                    # Use current connection directly to avoid deadlocks (re-entering self._db())
                    # and ensuring we bypass any potentially stale self._vector_dim cache.
                    async with conn.execute(
                        "SELECT dimension FROM vectors_metadata LIMIT 1"
                    ) as cursor:
                        row = await cursor.fetchone()
                        dim = row[0] if row else None

                    if dim is None:
                        # Auto-initialize dimension on first update with embedding
                        new_dim = len(embedding)
                        await conn.execute(
                            "INSERT OR IGNORE INTO vectors_metadata (dimension) VALUES (?)",
                            (new_dim,),
                        )
                        # Re-read authoritative dimension to handle race conditions
                        async with conn.execute(
                            "SELECT dimension FROM vectors_metadata LIMIT 1"
                        ) as cursor:
                            row = await cursor.fetchone()
                            dim = row[0] if row else None

                        if dim is None:
                            # Should not happen after INSERT
                            raise StorageError("Failed to initialize vector dimension")
                        self._vector_dim = dim

                    if len(embedding) != dim:
                        raise StorageError(
                            f"Dimension mismatch: expected {dim}, got {len(embedding)}",
                            code="INVALID_PARAMETER",
                        )
                    validate_embedding(embedding)
                    blob = encode_embedding(embedding)
                    await conn.execute(
                        "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding) "
                        "VALUES (?, ?)",
                        (memory_id, blob),
                    )
                    # If only embedding was updated, we still want to return True
                    if not set_parts:
                        updated = 1

                if updated == 0 and embedding is None:
                    return False

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
        """Full-text search using FTS5.

        FTS5 サニタイズ方針:
        - クエリをホワイトスペースでトークン分割し、各トークンを個別にダブルクォートで囲む
        - これにより FTS5 特殊文字 (`*`, `AND`, `OR`, `NOT`, `NEAR`, `?`) が
          トークン内でエスケープされつつ、トークン間は暗黙 AND として扱われる
        - マルチワードクエリ `"machine learning"` は各ワードがドキュメント内の任意の位置に
          存在すればマッチする(フレーズ一致ではない)
        """
        tokens = query.split()

        async with self._db() as conn:
            try:
                # 空クエリ / 空白のみは「すべてマッチ」として扱う (Postgres との互換性)
                if not tokens:
                    if project is not None:
                        sql = """
                            SELECT m.*, me.embedding, 1.0 AS score
                            FROM memories m
                            LEFT JOIN memory_embeddings me ON me.memory_id = m.id
                            WHERE m.archived_at IS NULL
                              AND m.content LIKE '%%'
                              AND m.project = ?
                            ORDER BY m.created_at DESC, m.id DESC
                            LIMIT ?
                        """
                        params_kw: tuple[Any, ...] = (project, top_k)
                    else:
                        sql = """
                            SELECT m.*, me.embedding, 1.0 AS score
                            FROM memories m
                            LEFT JOIN memory_embeddings me ON me.memory_id = m.id
                            WHERE m.archived_at IS NULL
                              AND m.content LIKE '%%'
                            ORDER BY m.created_at DESC, m.id DESC
                            LIMIT ?
                        """
                        params_kw = (top_k,)
                else:
                    # 各トークンを個別にクォートし、内部のダブルクォートをエスケープ。
                    # これにより FTS5 特殊文字がトークン内でエスケープされつつ、
                    # トークン間は暗黙 AND として扱われる。
                    fts_query = " ".join('"' + t.replace('"', '""') + '"' for t in tokens)
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
                        params_kw = (fts_query, project, top_k)
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
                        params_kw = (fts_query, top_k)

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

    def _build_where_clause(
        self, filters: MemoryFilters, prefix: str = "m."
    ) -> tuple[str, list[Any]]:
        """共通の WHERE 句とパラメータを生成する。"""
        conditions: list[str] = []
        params: list[Any] = []

        if filters.archived is None:
            conditions.append(f"{prefix}archived_at IS NULL")
        elif filters.archived is True:
            conditions.append(f"{prefix}archived_at IS NOT NULL")

        if filters.project is not None:
            params.append(filters.project)
            conditions.append(f"{prefix}project = ?")

        if filters.memory_type is not None:
            params.append(filters.memory_type)
            conditions.append(f"{prefix}memory_type = ?")

        if filters.tags:
            tag_conditions = []
            for tag in filters.tags:
                params.append(f'%"{tag}"%')
                tag_conditions.append(f"{prefix}tags LIKE ?")
            conditions.append("(" + " OR ".join(tag_conditions) + ")")

        if getattr(filters, "session_id", None) is not None:
            params.append(filters.session_id)
            conditions.append(
                f"CASE WHEN json_valid({prefix}source_metadata) "
                f"THEN json_extract({prefix}source_metadata, '$.session_id') END = ?"
            )

        if filters.min_importance is not None:
            params.append(filters.min_importance)
            conditions.append(f"{prefix}importance_score >= ?")

        if filters.created_after is not None:
            created_after_utc = filters.created_after.astimezone(timezone.utc).isoformat()
            if filters.id_after is not None:
                params.append(created_after_utc)
                params.append(filters.id_after)
                conditions.append(f"({prefix}created_at, {prefix}id) > (?, ?)")
            else:
                params.append(created_after_utc)
                conditions.append(f"{prefix}created_at >= ?")

        if filters.archived_after is not None:
            archived_after_utc = filters.archived_after.astimezone(timezone.utc).isoformat()
            if filters.id_after is not None:
                params.append(archived_after_utc)
                params.append(filters.id_after)
                conditions.append(f"({prefix}archived_at, {prefix}id) > (?, ?)")
            else:
                params.append(archived_after_utc)
                conditions.append(f"{prefix}archived_at >= ?")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, params

    async def list_by_filter(self, filters: MemoryFilters) -> list[Memory]:
        """List memories matching filters."""
        where_clause, params = self._build_where_clause(filters, prefix="m.")

        # ------------------------------------------------------------------
        # ORDER BY validation (whitelist)
        # ------------------------------------------------------------------
        allowed_sort_columns = ALLOWED_SORT_COLUMNS

        order_clause = "ORDER BY m.created_at DESC"
        if filters.order_by:
            order_parts = []
            # Support comma-separated columns
            for part in str(filters.order_by).split(","):
                tokens = part.strip().split()
                if not tokens:
                    continue
                col = tokens[0].replace("m.", "").lower()
                if col not in allowed_sort_columns:
                    raise StorageError(f"Invalid sort column: {col}", code="INVALID_PARAMETER")

                direction = "DESC"
                if len(tokens) > 1:
                    dir_part = tokens[1].upper()
                    if dir_part not in ("ASC", "DESC"):
                        raise StorageError(
                            f"Invalid sort direction: {dir_part}", code="INVALID_PARAMETER"
                        )
                    direction = dir_part

                if len(tokens) > 2:
                    raise StorageError(
                        f"Invalid order_by format: {part}. Extra tokens detected.",
                        code="INVALID_PARAMETER",
                    )
                order_parts.append(f"m.{col} {direction}")

            if order_parts:
                order_clause = f"ORDER BY {', '.join(order_parts)}"

        # ------------------------------------------------------------------
        # LIMIT and OFFSET validation
        # ------------------------------------------------------------------
        limit_clause = ""
        if filters.limit is not None:
            limit_val = filters.limit
            if not isinstance(limit_val, int) or limit_val < 0:
                raise StorageError(
                    message="Limit must be a non-negative integer",
                    code="INVALID_PARAMETER",
                )
            limit_clause = "LIMIT ?"
            params.append(limit_val)

        offset_clause = ""
        if filters.offset is not None:
            offset_val = filters.offset
            if not isinstance(offset_val, int) or offset_val < 0:
                raise StorageError(
                    message="Offset must be a non-negative integer",
                    code="INVALID_PARAMETER",
                )
            if filters.limit is None:
                # SQLite requires LIMIT when using OFFSET
                limit_clause = "LIMIT -1"
            offset_clause = "OFFSET ?"
            params.append(offset_val)

        sql = (
            "SELECT m.*, me.embedding "  # noqa: S608
            "FROM memories m "
            "LEFT JOIN memory_embeddings me ON me.memory_id = m.id "
            f"{where_clause} "
            f"{order_clause} "
            f"{limit_clause} "
            f"{offset_clause}"
        ).strip()

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

    async def count_by_filter(self, filters: MemoryFilters) -> int:
        """Count memories matching filters."""
        where_clause, params = self._build_where_clause(filters, prefix="m.")

        sql = (f"SELECT COUNT(*) FROM memories m {where_clause}").strip()  # noqa: S608

        async with self._db() as conn:
            try:
                async with conn.execute(sql, params) as cursor:
                    row = await cursor.fetchone()
                return row[0] if row else 0
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    async def list_projects(self) -> list[str]:
        """List all unique project names present in the storage."""
        sql = "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != ''"

        async with self._db() as conn:
            try:
                async with conn.execute(sql) as cursor:
                    rows = await cursor.fetchall()
                return [row[0] for row in rows]
            except aiosqlite.OperationalError as exc:
                _raise_if_locked(exc)
                raise

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        """Atomically increment the access count and update last_accessed_at."""
        async with self._db() as conn:
            try:
                now = datetime.now(timezone.utc).isoformat()
                async with conn.execute(
                    """
                    UPDATE memories
                    SET access_count = access_count + 1,
                        last_accessed_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, memory_id),
                ) as cursor:
                    updated_count: int = cursor.rowcount
                await conn.commit()
                return updated_count > 0
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
        self._lock_executor.shutdown(wait=True)
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
