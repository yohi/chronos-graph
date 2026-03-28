# Context Store MCP v2.0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** AIエージェント向けMCPベース長期記憶システムをPython + FastMCPで全面構築する

**Architecture:** パイプライン指向アーキテクチャ。Ingestion / Retrieval / Lifecycle の3パイプラインを Orchestrator が統合。Storage Layer は Protocol ベースの抽象層を介して PostgreSQL + Neo4j + Redis に接続。

**Tech Stack:** Python 3.12+, FastMCP, aiosqlite, sqlite-vec, FTS5, sentence-transformers, pydantic-settings, pytest, Docker Compose (Optional adapters: asyncpg, neo4j-python-driver, redis-py)

**Spec:** `SPEC.md` (プロジェクトルート)

---

## Phase 1: プロジェクト基盤

### Task 1.1: Python プロジェクト初期化

**Files:**
- Create: `pyproject.toml`
- Create: `src/context_store/__init__.py`
- Create: `.python-version`
- Create: `.gitignore` (Python用に更新)

**Step 1: pyproject.toml を作成**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "context-store-mcp"
version = "2.0.0"
description = "MCP-based long-term memory system for AI agents"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "aiosqlite>=0.20.0",
    "sqlite-vec>=0.1.0",
    "tenacity>=8.0.0",
    "tiktoken>=0.6.0",
]

[project.optional-dependencies]
storage-postgres = [
    "asyncpg>=0.29.0",
    "neo4j>=5.0.0",
    "redis>=5.0.0",
]
embedding-local = [
    "sentence-transformers>=3.0.0",
    "numpy>=1.26.0",
]
embedding-openai = [
    "openai>=1.0.0",
]
embedding-litellm = [
    "litellm>=1.0.0",
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-benchmark>=4.0.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.mypy]
python_version = "3.12"
strict = true
```

**Step 2: `src/context_store/__init__.py` を作成**

```python
"""Context Store MCP - Long-term memory system for AI agents."""

__version__ = "2.0.0"
```

**Step 3: .python-version を作成**

```text
3.12
```

**Step 4: 依存パッケージのインストール確認**

Run: `pip install -e ".[dev]"`
Expected: 正常にインストールされること

**Step 5: Commit**

```bash
git add pyproject.toml src/ .python-version
git commit -m "feat: Python プロジェクト基盤を初期化"
```

---

### Task 1.2: Docker Compose 環境構築

**Files:**
- Create: `docker-compose.yml`
- Create: `docker/postgres/init.sql`

**Step 1: docker-compose.yml を作成**

PostgreSQL (pgvector + pg_bigm), Neo4j, Redis の3サービスを定義。

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: context_store
      POSTGRES_USER: context_store
      POSTGRES_PASSWORD: dev_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U context_store -d context_store"]
      interval: 5s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/dev_password
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "cypher-shell -u neo4j -p dev_password 'RETURN 1'"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  neo4j_data:
  redis_data:
```

**Step 2: docker/postgres/init.sql を作成**

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
```

**Step 3: Docker起動確認**

Run: `docker compose up -d`
Run: `docker compose ps`
Expected: 3サービスとも healthy / running

**Step 4: Commit**

```bash
git add docker-compose.yml docker/
git commit -m "feat: Docker Compose 環境を構築 (PostgreSQL + Neo4j + Redis)"
```

---

### Task 1.3: 設定管理 (pydantic-settings)

**Files:**
- Create: `src/context_store/config.py`
- Create: `.env.example`
- Create: `tests/unit/test_config.py`

**Step 1: テストを書く**

```python
# tests/unit/test_config.py
import pytest
from context_store.config import Settings

def test_default_settings():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
    )
    assert settings.postgres_port == 5432
    assert settings.embedding_provider == "openai"
    assert settings.decay_half_life_days == 30
    assert settings.archive_threshold == 0.05
    assert settings.similarity_threshold == 0.70
    assert settings.dedup_threshold == 0.90
    assert settings.graph_fanout_limit == 50
    assert settings.graph_max_logical_depth == 5
    assert settings.graph_max_physical_hops == 50
    assert settings.sqlite_max_concurrent_connections == 5
    assert settings.sqlite_acquire_timeout == 2.0

def test_embedding_provider_validation():
    settings = Settings(
        postgres_host="localhost",
        postgres_password="test",
        neo4j_password="test",
        embedding_provider="local-model",
    )
    assert settings.embedding_provider == "local-model"

def test_postgres_password_required_when_backend_selected():
    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings(storage_backend="postgres", postgres_password="", neo4j_password="test")

def test_neo4j_password_required_when_graph_enabled():
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        Settings(graph_enabled=True, neo4j_password="", postgres_password="test")
```

**Step 2: テスト失敗確認**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: config.py を実装**

```python
# src/context_store/config.py
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    # --- Storage Backend ---
    storage_backend: Literal["sqlite", "postgres"] = "sqlite"
    graph_enabled: bool = False
    cache_backend: Literal["inmemory", "redis"] = "inmemory"

    # --- SQLite (storage_backend=sqlite の場合) ---
    sqlite_db_path: str = "~/.context-store/memories.db"

    # --- PostgreSQL (storage_backend=postgres の場合) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "context_store"
    postgres_user: str = "context_store"
    postgres_password: str = ""

    # --- Neo4j (graph_enabled=true の場合) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Redis (cache_backend=redis の場合) ---
    redis_url: str = "redis://localhost:6379"

    # --- Embedding ---
    embedding_provider: Literal["openai", "local-model", "litellm", "custom-api"] = "openai"
    openai_api_key: str = ""
    local_model_name: str = "cl-nagoya/ruri-v3-310m"
    litellm_api_base: str = "http://localhost:4000"
    custom_api_endpoint: str = ""

    # --- Lifecycle ---
    decay_half_life_days: int = 30
    archive_threshold: float = 0.05
    consolidation_threshold: float = 0.85
    purge_retention_days: int = 90

    # --- Search ---
    default_top_k: int = 10
    similarity_threshold: float = 0.70
    dedup_threshold: float = 0.90
    graph_fanout_limit: int = 50
    graph_max_logical_depth: int = 5
    graph_max_physical_hops: int = 50

    # --- SQLite specific ---
    sqlite_max_concurrent_connections: int = 5
    sqlite_acquire_timeout: float = 2.0  # seconds

    # --- URL Fetch (SSRF 対策) ---
    url_fetch_concurrency: int = 3
    allow_private_urls: bool = False
    url_max_redirects: int = 3
    url_max_response_bytes: int = 10 * 1024 * 1024  # 10MB
    url_timeout_seconds: int = 30
    url_allowed_content_types: list[str] = Field(
        default_factory=lambda: ["text/*", "application/json", "application/pdf"]
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @model_validator(mode="after")
    def validate_credentials(self) -> "Settings":
        if self.storage_backend == "postgres" and not self.postgres_password:
            raise ValueError("POSTGRES_PASSWORD は storage_backend=postgres の場合に必須です。")
        if self.storage_backend == "postgres" and self.graph_enabled and not self.neo4j_password:
            raise ValueError("NEO4J_PASSWORD は graph_enabled=true の場合に必須です。")
        return self
```

**Step 4: .env.example を作成**

```bash
# === Core ===
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=context_store
POSTGRES_USER=context_store
POSTGRES_PASSWORD=dev_password

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=dev_password

REDIS_URL=redis://localhost:6379

# === Embedding ===
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m

# === Lifecycle ===
DECAY_HALF_LIFE_DAYS=30
ARCHIVE_THRESHOLD=0.05
PURGE_RETENTION_DAYS=90

# === Search ===
DEFAULT_TOP_K=10
SIMILARITY_THRESHOLD=0.70
DEDUP_THRESHOLD=0.90
GRAPH_FANOUT_LIMIT=50
GRAPH_MAX_LOGICAL_DEPTH=5
GRAPH_MAX_PHYSICAL_HOPS=50
SQLITE_MAX_CONCURRENT_CONNECTIONS=5
SQLITE_ACQUIRE_TIMEOUT=2.0

# === URL Fetch (SSRF 対策) ===
URL_FETCH_CONCURRENCY=3
ALLOW_PRIVATE_URLS=false
URL_MAX_REDIRECTS=3
URL_MAX_RESPONSE_BYTES=10485760
URL_TIMEOUT_SECONDS=30
```

**Step 5: テスト成功確認**

Run: `pytest tests/unit/test_config.py -v`
Expected: PASS

*Deployment & Testing Validation*:
テスト実行時および本番デプロイ時において、環境変数で指定（または省略）された `GRAPH_MAX_PHYSICAL_HOPS` 等の各設定値が期待通りにロードされ、トラバーサル制限として機能するかどうかを検証すること。
具体的には、Task 5.4 の自動テスト（`tests/unit/test_graph_traversal.py`）を拡張し、`GRAPH_MAX_PHYSICAL_HOPS` に小さい値をオーバーライド設定してトラバーサルアルゴリズムを実行する。指定されたホップ上限内で到達するケース（success case）と、上限を超過するためトラバーサルが設定レイヤで正確に停止するケース（failure/halt case）の両方のアサーションを実装し、必ずCIのパス要件として自動実行させること。

**Step 6: Commit**

```bash
git add src/context_store/config.py .env.example tests/
git commit -m "feat: pydantic-settings による設定管理を実装"
```

---

### Task 1.4: データモデル定義

**Files:**
- Create: `src/context_store/models/__init__.py`
- Create: `src/context_store/models/memory.py`
- Create: `src/context_store/models/search.py`
- Create: `src/context_store/models/graph.py`
- Create: `tests/unit/test_models.py`

**Step 1: テストを書く**

```python
# tests/unit/test_models.py
from uuid import uuid4
from datetime import datetime, timezone
from context_store.models.memory import Memory, MemoryType, SourceType

def test_memory_creation():
    m = Memory(
        id=uuid4(),
        content="JWT認証をベースに統一する方針に決定",
        memory_type=MemoryType.EPISODIC,
        source_type=SourceType.CONVERSATION,
        source_metadata={"agent": "claude-code", "project": "/my/project"},
        embedding=[0.1] * 768,
        importance_score=0.8,
        tags=["auth", "backend"],
    )
    assert m.memory_type == MemoryType.EPISODIC
    assert m.archived_at is None
    assert m.access_count == 0

def test_memory_type_enum():
    assert MemoryType.EPISODIC.value == "episodic"
    assert MemoryType.SEMANTIC.value == "semantic"
    assert MemoryType.PROCEDURAL.value == "procedural"
```

**Step 2: テスト失敗確認**

Run: `pytest tests/unit/test_models.py -v`
Expected: FAIL

**Step 3: models/memory.py を実装**

```python
# src/context_store/models/memory.py
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class SourceType(str, Enum):
    CONVERSATION = "conversation"
    MANUAL = "manual"
    URL = "url"


class Memory(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    content: str
    memory_type: MemoryType
    source_type: SourceType
    source_metadata: dict = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=list)
    semantic_relevance: float = 0.5
    importance_score: float = 0.5
    access_count: int = 0
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    archived_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    project: str | None = None


class ScoredMemory(BaseModel):
    memory: Memory
    score: float
    source: str = ""  # "vector" | "keyword" | "graph"
```

**Step 4: models/search.py, models/graph.py を実装**

```python
# src/context_store/models/search.py
from __future__ import annotations

from pydantic import BaseModel

from context_store.models.memory import ScoredMemory


class SearchStrategy(BaseModel):
    vector_weight: float = 0.5
    keyword_weight: float = 0.2
    graph_weight: float = 0.3
    graph_depth: int = 2
    time_decay_enabled: bool = True


class SearchFilters(BaseModel):
    project: str | None = None
    memory_type: str | None = None
    top_k: int = 10
    max_tokens: int | None = None


class SearchResult(BaseModel):
    results: list[ScoredMemory]
    total_count: int
    strategy_used: SearchStrategy
```

```python
# src/context_store/models/graph.py
from __future__ import annotations

from pydantic import BaseModel, Field


class Edge(BaseModel):
    from_id: str
    to_id: str
    edge_type: str
    properties: dict = Field(default_factory=dict)


class GraphResult(BaseModel):
    nodes: list[dict]
    edges: list[Edge]
    traversal_depth: int
```

**Step 5: models/__init__.py を作成**

```python
# src/context_store/models/__init__.py
from context_store.models.memory import Memory, MemoryType, SourceType, ScoredMemory
from context_store.models.search import SearchStrategy, SearchFilters, SearchResult
from context_store.models.graph import Edge, GraphResult

__all__ = [
    "Memory", "MemoryType", "SourceType", "ScoredMemory",
    "SearchStrategy", "SearchFilters", "SearchResult",
    "Edge", "GraphResult",
]
```

**Step 6: テスト成功確認**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/context_store/models/ tests/unit/test_models.py
git commit -m "feat: データモデル (Memory, Search, Graph) を定義"
```

---

### Task 1.5: CI/CD パイプライン構築

**Files:**
- Create: `bitbucket-pipelines.yml` (または `.github/workflows/ci.yml`)

**Step 1: 実装**

- `ruff check`, `ruff format --check`
- `mypy src/`
- `pytest tests/unit`

**Step 2: Commit**

```bash
git add bitbucket-pipelines.yml
git commit -m "ci: CI/CD パイプラインを追加"
```

---

## Phase 2: Storage Layer

### Task 2.1: Storage Protocol 定義

**Files:**
- Create: `src/context_store/storage/__init__.py`
- Create: `src/context_store/storage/protocols.py`

**Step 1: Protocol を定義**

SPEC.md §8 の StorageAdapter / GraphAdapter / CacheAdapter Protocol をそのまま実装。

**ベクトル次元数フェイルファストチェック（SPEC.md §9.1）:**

StorageAdapter に `get_vector_dimension() -> int | None` メソッドを追加する。
EmbeddingProvider の `dimension` と不一致の場合、起動時にフェイルファストで
例外を投げる。例外メッセージには、v2.0で未実装の自動マイグレーションへの誘導ではなく、
DB変更等による手動復旧手順を含める。チェックは Orchestrator（Task 8.1）の初期化時に実行。

**Step 2: Commit**

```bash
git add src/context_store/storage/
git commit -m "feat: Storage Layer の Protocol を定義"
```

**Verification:**

```bash
Run: python -c "from context_store.storage.protocols import StorageAdapter, GraphAdapter, CacheAdapter"
Expected: インポート成功（エラーなし）
```

---

### Task 2.1a: PostgreSQL 初期スキーマとインデックス定義

**Files:**
- Create: `docker/postgres/schema.sql`
- Modify: `docker/postgres/init.sql`（`\i /docker-entrypoint-initdb.d/schema.sql` を追記）
- Create: `tests/integration/test_postgres_schema.py`

**Step 1: schema.sql を作成**

SPEC.md §3.1 および §6.2 に準拠したテーブル定義:

- `memories` テーブル（全フィールド、`embedding` vector カラム含む）
- `lifecycle_state` テーブル（`last_cleanup_at`, `save_count`, `cleanup_running`, `updated_at`）
- B-tree インデックス: `memory_type`, `source_type`, `archived_at`, `project`
- HNSW ベクトルインデックス: `embedding` カラム
- pg_bigm / pgroonga による FTS 設定

**Step 2: 統合テストを書く**

- `docker/postgres/schema.sql` を `session` スコープ fixture で 1 回だけ適用する
- 各テストは専用 connection + transaction fixture 内で実行し、終了時にロールバックする
- `SERIAL` / sequence の固定値に依存しない assertion を使う（必要なら session setup で `ALTER SEQUENCE ... RESTART`）
- 全テーブルが存在すること
- 全インデックスが存在すること
- vector 拡張が有効であること
- FTS 拡張が有効であること
- `lifecycle_state` テーブル名・sequence 名は `schema.sql` の実名を参照すること

**Step 3: Commit**

```bash
git commit -m "feat: PostgreSQL 初期スキーマとインデックスを定義"
```

**Verification:**

```bash
Run: docker compose up -d postgres
Run: pytest tests/integration/test_postgres_schema.py -v
Expected: PASS
```

---

### Task 2.2: PostgreSQL Storage Adapter

**前提条件:** Task 2.1a のスキーマが適用済みであること。

**Files:**
- Create: `src/context_store/storage/postgres.py`
- Create: `tests/unit/test_postgres_storage.py`
- Create: `tests/integration/test_postgres_integration.py`
- Create: `tests/integration/conftest.py`

**Step 1: ユニットテストを書く（モック利用）**

PostgresStorageAdapter の各メソッドのテスト。asyncpg の Pool をモックして
SQL クエリの組み立てロジックとレコードの変換ロジックを検証。

**Step 2: 実装**

- `asyncpg.create_pool()` で接続プール管理
- `save_memory`: INSERT（単純挿入。重複検出は Ingestion Pipeline の Deduplicator が担当）
- `vector_search`: `ORDER BY embedding <=> $1 LIMIT $2`
- `keyword_search`: pg_bigm/pgroonga の全文検索クエリ
- `get_vector_dimension`: `SELECT vector_dims(embedding) FROM memories LIMIT 1`
- `dispose`: プールの close

**Step 3: 統合テスト + conftest.py**

Docker 上の PostgreSQL に接続して実際に CRUD + 検索を実行。

**テストデータ隔離戦略:**
- 各テストケースを DB トランザクション内で実行し、終了時にロールバック
- `tests/integration/conftest.py` に以下の fixture を定義:

```python
@pytest.fixture
async def db_session(postgres_pool):
    conn = await postgres_pool.acquire()
    tx = conn.transaction()
    await tx.start()
    yield conn
    await tx.rollback()
    await postgres_pool.release(conn)
```

- テスト間のデータ汚染を防ぎ、並列テスト実行時の競合を回避

**Step 4: テスト確認 & Commit**

```bash
git commit -m "feat: PostgreSQL Storage Adapter を実装"
```

**Verification:**

```bash
Run: pytest tests/unit/test_postgres_storage.py -v
Expected: PASS

Run: docker compose up -d postgres
Run: pytest tests/integration/test_postgres_integration.py -v
Expected: PASS
```

---

### Task 2.3: Neo4j Graph Adapter

**Files:**
- Create: `src/context_store/storage/neo4j.py`
- Create: `tests/unit/test_neo4j_storage.py`
- Create: `tests/integration/test_neo4j_integration.py`

**Step 1: テストを書く**

create_node, create_edge, traverse, delete_node のテスト。

**Step 2: 実装**

- `neo4j.AsyncDriver` でセッション管理
- `create_node`: Cypher `MERGE (:Memory {id: $id})`
- `create_edge`: Cypher `MATCH ... CREATE (a)-[r:TYPE]->(b)`
- `create_edges_batch`: Cypher の `UNWIND` 等を用いて複数エッジを1回のクエリでバルク登録（N+1問題対策）
- `traverse`: 深さ可変の Cypher パス検索
- Graceful Degradation: 接続失敗時に例外を投げずにログ出力

**Step 3: テスト確認 & Commit**

```bash
git commit -m "feat: Neo4j Graph Adapter を実装"
```

---

### Task 2.4: Redis Cache Adapter

**Files:**
- Create: `src/context_store/storage/redis.py`
- Create: `tests/unit/test_redis_storage.py`

**Step 1: テストを書く**

get/set/invalidate のテスト。

**Step 2: 実装**

- `redis.asyncio.from_url()` で接続
- JSON シリアライズ/デシリアライズ
- TTL ベースのキャッシュ管理
- 接続失敗時の Graceful Degradation

**Step 3: テスト確認 & Commit**

```bash
git commit -m "feat: Redis Cache Adapter を実装"
```

---

### Task 2.5: SQLite Storage Adapter（ライトウェイト版）

**Files:**
- Create: `src/context_store/storage/sqlite.py`
- Create: `tests/unit/test_sqlite_storage.py`

**Step 1: テストを書く**

- save_memory / get_memory / delete_memory の CRUD テスト
- vector_search: `sqlite-vec` によるコサイン類似度ベクトル検索
- keyword_search: `FTS5` による全文検索（N-gram トークナイザ）
- 単一ファイルで動作すること（一時ディレクトリで検証）
- WAL モードが有効であることの検証（`PRAGMA journal_mode` の戻り値チェック）
- 並行処理 & バックプレッシャーテスト: `sqlite_max_concurrent_connections=2` に設定し、10 個の同時リクエストを発行。アクティブな DB 処理が常に 2 以下であることを検証（セマフォの acquire/release をラップしたカウンタ等で計測）。
- セマフォ取得タイムアウトテスト: セマフォ取得に `sqlite_acquire_timeout` 以上かかる状況を作り、`StorageError(code="STORAGE_BUSY", ...)` が送出されることを検証。
- シリアライズ・デシリアライズ関連テスト: `serialize_float32`, `encode_embedding`, `save_embedding`, `decode_embedding`, `load_embedding`, `validate_embedding` を対象に、1) 保存→読み戻しでの一致（float32 キャスト含む）、2) 次元不一致時のエラー（保存・検索時）、3) NaN/Inf を含む入力の拒否、4) 公式APIフォールバック経路の動作確認（シリアライズ整合性とエラー処理）の単体テストを追加すること

**Step 2: 実装**

- `aiosqlite` で非同期接続管理
  - **注意**: `aiosqlite` ではワーカースレッド数の明示は不可。
  - **スレッドプール枯渇・コンテンション対策**として、以下の代替実装を行う:
    - **バックプレッシャー制御**: `Settings.sqlite_max_concurrent_connections` に基づき、`SQLiteStorageAdapter` インスタンスレベルで単一の `asyncio.Semaphore` を保持し、`save_memory` や `vector_search` などのすべての DB 操作をこのセマフォでラップすること。その際、`asyncio.wait_for(semaphore.acquire(), timeout=Settings.sqlite_acquire_timeout)` を用い、タイムアウト時は `StorageError(code="STORAGE_BUSY", ...)` を送出すること。これによりメモリへのタスク滞留を防ぐ。

    - **コネクションプール設計**（再利用するコネクション管理）
    - TRUNCATEなどによるロック競合で `aiosqlite.OperationalError: database is locked` や `SQLITE_BUSY` 等が発生した場合、クラッシュさせるのではなく `StorageError(code="STORAGE_BUSY", recoverable=True)` を送出してMCPクライアントにエラーを通知する（再試行を促す）ハンドリングを追加すること。
- 接続確立後 (`pool/get_connection` ルーチン内など) 直ちに PRAGMA を強制実行し、`journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`, `synchronous=NORMAL` を適用する
- `sqlite-vec` 拡張のロードとベクトルインデックス作成
- `sqlite-vec` が期待するバイナリBLOBへの型シリアライズ要件として、Python の `list[float]` を保存時/検索時に公式パッケージ (`sqlite-vec`) が提供する `serialize_float32()` を用いて正確にエンコードする処理を優先的に実装に組み込むこと（背景技術として `struct.pack('<' + 'f' * len(embedding), *embedding)` を理解しつつ公式APIを第一選択とする）。また、エンコード処理（例: encode_embedding / save_embedding）およびデコード処理（例: decode_embedding / load_embedding）において、入力を必ず float32 にキャストし、保存時・検索時に次元数が期待値と一致するか `validate_embedding` 関数等で検証（不一致時はエラー）すること。さらに、`math.isnan` や `math.isinf` を用いて不正な値（NaN/Inf）を検出し、保存・検索を事前に拒否する実装を含めること。
- `FTS5` テーブルの作成（`content` カラムの全文検索用）
- メタデータテーブル `vectors_metadata` を作成し、次元数を保存
- `get_vector_dimension`: `SELECT dimension FROM vectors_metadata WHERE table_name = 'memories'`
- StorageAdapter Protocol に完全準拠
- テーブル自動マイグレーション（初回接続時にスキーマ作成）

**Step 3: テスト確認 & Commit**

```bash
git commit -m "feat: SQLite Storage Adapter (ライトウェイト版) を実装"
```

---

### Task 2.5b: SQLite Graph Adapter

**Files:**
- Create: `src/context_store/storage/sqlite_graph.py`
- Create: `tests/unit/test_sqlite_graph.py`

**Step 1: テストを書く**

- `create_edge`: エッジの追加（重複時は無視または更新）
- `create_edges_batch`: 複数エッジの情報を executemany 等で一括インサート（N+1問題対策）
- `traverse`: 再帰的 CTE によるグラフトラバーサル（depth=1,2,3 で検証）
- `traverse` の depth ハードリミット（`Settings.graph_max_logical_depth` で検証。これを超える値は強制制限）
- `delete_node`: ノードと関連エッジの削除
- `create_node`: ノードの作成（メタデータ付き）
- GraphAdapter Protocol に完全準拠

**Step 2: 実装**

- SPEC.md §8.4 の `memory_edges` スキーマと再帰的 CTE クエリをそのまま実装
- `SQLiteStorageAdapter` と同一の DB ファイルを共有（接続の受け渡し）
- PRAGMA は `SQLiteStorageAdapter` 側で既に適用済みを前提
- **トラバーサル上限設定**: `SUPERSEDES` チェーンループ回避用の物理ホップ上限値（CTE 内の `physical_depth >= graph_max_physical_hops` 制約）はハードコードを避け、`config.py` の `Settings.graph_max_physical_hops` を参照するかコンストラクタで受け取る設計とし、テストやランタイムでのチューニングを容易にすること。

**Step 3: テスト確認 & Commit**

```bash
git commit -m "feat: SQLite Graph Adapter (再帰的 CTE) を実装"
```

---

### Task 2.6: InMemory Cache Adapter + Storage Factory

**Files:**
- Create: `src/context_store/storage/inmemory.py`
- Create: `src/context_store/storage/factory.py`
- Create: `tests/unit/test_inmemory_cache.py`
- Create: `tests/unit/test_storage_factory.py`

**Step 1: テストを書く**

- InMemoryCacheAdapter: get/set/invalidate + TTL 期限切れテスト
- StorageFactory: `STORAGE_BACKEND=sqlite` → SQLiteStorageAdapter 生成
- StorageFactory: `STORAGE_BACKEND=postgres` → PostgresStorageAdapter 生成
- StorageFactory: `GRAPH_ENABLED=false` → GraphAdapter が None
- StorageFactory: `CACHE_BACKEND=inmemory` → InMemoryCacheAdapter 生成

**Step 2: 実装**

- InMemoryCacheAdapter: `dict` + `asyncio.Lock` + TTL 管理。`invalidate_prefix` メソッドでのループ内におけるO(N)ブロッキングとロック競合を防ぐため、以下のいずれかのアプローチを必須として実装すること: (a) スリープ前のロック一時解放・再取得（`batch_size` 毎にロックを解放し、`await asyncio.sleep(0.001)` を実行してから再取得する）、または (b) 全キーのリストを短いロック期間でスナップショットとして抽出し、ロック解放後にバッチ削除を実行する。
- StorageFactory: Settings に基づいて適切なアダプターを返すファクトリ関数
  `create_storage(settings) -> tuple[StorageAdapter, GraphAdapter, CacheAdapter]`
  ※ `sqlite` モードでは GraphAdapter = SQLiteGraphAdapter（None ではない）

**Step 3: テスト確認 & Commit**

```bash
git commit -m "feat: InMemory Cache Adapter + Storage Factory を実装"
```

---

## Phase 3: Embedding Provider

### Task 3.1: Protocol 定義 (Embedding / TokenCounter) + OpenAI Provider

**Files:**
- Create: `src/context_store/embedding/__init__.py`
- Create: `src/context_store/embedding/protocols.py`
- Create: `src/context_store/embedding/openai.py`
- Create: `tests/unit/test_embedding.py`

**Step 1: Protocol 定義 + テスト**

- SPEC.md §9 の EmbeddingProvider Protocol を `src/context_store/embedding/protocols.py` に定義。
- **TokenCounter Protocol の定義**: 同様に `protocols.py` にて `class TokenCounter(Protocol): def count_tokens(self, text: str) -> int: ...` などの型定義・インターフェースを定義。将来的に Post Processor のフォールバック等から利用可能にする。
- OpenAIEmbeddingProvider のテスト（httpx モック）。

**Step 2: 実装**

- embed: 単一テキスト → ベクトル
- embed_batch: バッチ処理。外部 API のトークン上限やペイロード上限を回避するため、内部でリストを固定サイズ（例: 100件ごと）のチャンクへ分割（ページネーション）して送信すること。この際、入力時のインデックスを追跡し、分割リトライ処理等が行われても **最終的な返り値の順序が入力 `texts` と完全に一致することを保証** すること。さらに、外部 API レートリミット (TPM/RPM) 抵触を防ぐため、特定の例外（HTTP 429, タイムアウト, 5xx等）に絞って `tenacity` 等を用いた Exponential Backoff によるリトライ機構を組み合わせて実装すること。
- dimension プロパティ

**Step 3: Commit**

```bash
git commit -m "feat: Embedding Provider Protocol + OpenAI 実装"
```

---

### Task 3.2: Local Model Provider

**Files:**
- Create: `src/context_store/embedding/local_model.py`
- Create: `tests/unit/test_embedding_local.py`

**Step 1: テスト + 実装**

- sentence-transformers の遅延ロード
- `from __future__ import annotations` で型アノテーションの遅延評価
- embed/embed_batch の実装

**Step 2: Commit**

```bash
git commit -m "feat: ローカルモデル Embedding Provider を実装"
```

---

### Task 3.3: LiteLLM + Custom API Provider

**Files:**
- Create: `src/context_store/embedding/litellm.py`
- Create: `src/context_store/embedding/custom_api.py`
- Create: `tests/unit/test_embedding_litellm.py`

**Step 1: テスト + 実装**

LiteLLM: litellm.aembedding() のラッパー。`embed_batch` には固定サイズのページネーション分割と、インデックスを追跡して元配列の順序を完全に保持する再構築ロジック、および `tenacity` 等を用いた特定例外の Exponential Backoff (リトライ機構) を実装し、レートリミットとAPIペイロード上限に対処すること。
Custom API: httpx で POST リクエスト。LiteLLMと同様に、`embed_batch` での固定サイズページネーションとインデックス追跡による順序保証、特定例外に対する `tenacity` 等を用いた Exponential Backoff (リトライ機構) を実装し、レートリミットおよびペイロード制限対策を行うこと。

**Step 2: Commit**

```bash
git commit -m "feat: LiteLLM + Custom API Embedding Provider を実装"
```

---

### Task 3.4: Embedding Provider ファクトリ

**Files:**
- Modify: `src/context_store/embedding/__init__.py`
- Create: `tests/unit/test_embedding_factory.py`

**Step 1: テスト + 実装**

Settings.embedding_provider の値に基づいて適切なプロバイダーインスタンスを返す
ファクトリ関数 `create_embedding_provider(settings)` を実装。

**Step 2: Commit**

```bash
git commit -m "feat: Embedding Provider ファクトリを実装"
```

---

## Phase 4: Ingestion Pipeline

### Task 4.1: Source Adapter (Conversation / Manual / URL)

**Files:**
- Create: `src/context_store/ingestion/__init__.py`
- Create: `src/context_store/ingestion/adapters.py`
- Create: `tests/unit/test_adapters.py`

**Step 1: テストを書く**

各アダプターに対するテスト:
- ConversationAdapter: トランスクリプトテキスト → RawContent リスト
- ManualAdapter: テキスト + メタデータ → RawContent
- URLAdapter: URL → HTML取得（httpx モック）→ Markdown変換 → RawContent

**Step 2: 実装**

- SourceAdapter Protocol の定義
- RawContent データクラスの定義
- HTMLからMarkdownへの変換（httpxでフェッチ、簡易パーサー）

**URLAdapter の DNS リバインディング対策（必須）:**

SSRF の DNS リバインディング攻撃を防ぐため、以下のフローで HTTP リクエストを発行:

1. URL のホスト名を DNS 解決し、解決された IP アドレスを取得
2. 取得した IP に対し、`ipaddress` モジュールを用いて厳密な検証（`is_private`, `is_loopback`, `is_link_local`, `is_multicast`, `is_unspecified`, および `0.0.0.0/8` 等）を行い、該当する場合は拒否する。
3. 検証済みの IP アドレスに対して直接接続する際、TLS ハンドシェイクにおいて `server_hostname` (SNI) に元のホスト名を設定し、かつ完全な証明書検証（ホスト名一致確認を含む）を強制する。証明書の不一致や検証失敗が発生した場合は接続を拒否する。
4. 検証済みの IP と TLS 設定を使用して HTTP リクエストを発行（`Host` ヘッダーは元のホスト名を設定）
5. レスポンスヘッダーの `Content-Type` が許可リスト（`text/*`, `application/json`, `application/pdf`）に含まれることを検証し、不一致の場合は接続を中断する（ボディのストリーミング開始前・ヘッダー受信直後に行うこと）
6. コネクション確立後、レスポンスボディを `httpx` のストリーミングAPI (`stream`) を用いて少しずつ読み込み、データ量が 10MB を超過した時点で直ちに通信を中断する。
7. リダイレクト発生時は遷移先 URL に対して手順 1-6 を再実行

`httpx` のカスタム Transport で DNS 解決と IP 検証を接続前に強制実行する。

**URLAdapter の拒否系ユニットテスト（必須）:**

以下のセキュリティテストを `tests/unit/test_adapters.py` に含める:

- private IP / loopback URL（`127.0.0.1`, `10.x.x.x`, `169.254.169.254`）を拒否すること
- IPv6 private / loopback / link-local / multicast（`::1`, `fc00::/7`, `fe80::/10`, `ff00::/8`）を拒否すること
- `0.0.0.0` などの特殊アドレスを拒否すること
- ホスト名ではなく IP リテラル（例: `http://127.0.0.1/`）も拒否すること
- DNS 応答が複数 IP を返す場合、1件でも private/restricted IP を含めば拒否すること
- リダイレクト 4 回目で失敗すること（`url_max_redirects=3`）
- 10MB 超のレスポンスを受信途中で即時中断し拒否すること（ストリーミング中の `url_max_response_bytes` チェック）
- 許可されていない Content-Type を拒否すること（`url_allowed_content_types`）
- DNS リバインディング: 解決済み IP へ直接接続すること
- 無効な HTTPS 証明書を拒否すること
- `allow_private_urls=True` でプライベート URL が許可されること
- URLAdapter が `Settings` の URL 関連設定を参照すること（Task 1.3 で追加済み）

**Step 3: Commit**

```bash
git commit -m "feat: Source Adapter (Conversation/Manual/URL) を実装"
```

**Verification:**

```bash
Run: pytest tests/unit/test_adapters.py -v
Expected: PASS
```

---

### Task 4.2: Chunker

**Files:**
- Create: `src/context_store/ingestion/chunker.py`
- Create: `tests/unit/test_chunker.py`

**Step 1: テストを書く**

- 会話ログ: Q&Aペアに正しく分割されること
- 手動入力: 短い入力はそのまま、長い入力はセクション分割
- URL文書: Markdown見出しベースのセクション分割 + オーバーラップ
- チャンク化された要素の順序関係を維持するため、Task 4.5 (CHUNK_NEXT/CHUNK_PREV) で利用可能な安定したキー名として、メタデータに `document_id` (文字列), `chunk_index` (整数、0オリジン), `chunk_count` (整数) を明示的に必須項目として定義し、意味論を含めて実装すること

**Step 2: 実装**

SourceType に応じた分割戦略の選択と実行。メモリ効率化のため、分割結果全体をメモリ上の巨大なリストとして保持するのではなく、ジェネレータ（`yield`）を利用してチャンクを1件ずつ出力する遅延評価パイプラインとして実装すること。

**Step 3: Commit**

```bash
git commit -m "feat: Chunker (Q&A分割/セクション分割) を実装"
```

---

### Task 4.3: Classifier（記憶種別の自動分類）

**Files:**
- Create: `src/context_store/ingestion/classifier.py`
- Create: `tests/unit/test_classifier.py`

**Step 1: テストを書く**

- 「DBのマイグレーションを実行した」→ EPISODIC
- 「JWTとはJSON Web Tokenの略で...」→ SEMANTIC
- 「デプロイ手順: 1. docker compose up 2. ...」→ PROCEDURAL
- 未分類入力（例: 「なるほど」「そうなんだ」等の分類ルールに合致しない曖昧な発話）→ EPISODIC に正しくフォールバックされること

**Step 2: 実装**

- ルールベース分類: キーワードマッチ + 構文パターン（LLM は使用しない）。
- 上記のいずれのパターンにも合致しない曖昧な入力に対するフォールバック（デフォルト）の MemoryType を `EPISODIC` とするロジックを実装。また、このフォールバック時には、ノイズによる検索結果汚染を防ぐため、デフォルトの `importance_score` に対してペナルティ（例: 0.5倍の係数を掛ける）を適用すること。
- QA / テレメトリ要件 (SPEC超過の拡張機能—オプション実装): SPEC.md §3.4 または 160行目の「EPISODIC へのフォールバック」仕様に対する監視として、未分類入力があった場合ルールの改善に繋げるための警告・専用ログを出力するテレメトリフックをオプションで実装する。

**Step 3: Commit**

```bash
git commit -m "feat: 記憶種別の自動分類 (Classifier) を実装"
```

---

### Task 4.4: Deduplicator（重複排除）

**Files:**
- Create: `src/context_store/ingestion/deduplicator.py`
- Create: `tests/unit/test_deduplicator.py`

**Step 1: テストを書く**

- 類似度 ≥ 0.90: **Append-only 置換**が選択されること
- 0.85 ≤ 類似度 < 0.90: 統合候補としてマークされること
- 類似度 < 0.85: 新規挿入が選択されること

**Append-only 置換の具体的手順（類似度 ≥ 0.90 の場合）:**

1. 既存記憶を `Archived` に遷移（`archived_at` を設定）
2. 新規ノードを INSERT
3. 新ノードから旧ノードへ `SUPERSEDES` エッジを作成

> **設計根拠**: `ON CONFLICT DO UPDATE` ではなく Append-only とすることで、
> 記憶の変遷履歴がグラフで追跡可能になる。

**Step 2: 実装**

StorageAdapter.vector_search を使って既存 Top5 を取得し、判定ロジックを実行。

**Step 3: Commit**

```bash
git commit -m "feat: Deduplicator (重複排除・統合候補マーク) を実装"
```

**Verification:**

```bash
Run: pytest tests/unit/test_deduplicator.py -v
Expected: PASS
```

---

### Task 4.5: Graph Linker

**Files:**
- Create: `src/context_store/ingestion/graph_linker.py`
- Create: `tests/unit/test_graph_linker.py`

**Step 1: テストを書く**

- SEMANTICALLY_RELATED: 類似度 ≥ 0.70 で作成されること
- TEMPORAL_NEXT/PREV: 同一セッションの記憶に対して作成されること
- SUPERSEDES: Append-only 置換（新規 INSERT と旧ノードへ SUPERSEDES を付与）時に作成されること
- REFERENCES: URL/ファイルパスの抽出
- CHUNK_NEXT/PREV: URLや手動入力における同一ドキュメント内の連続するチャンク群に対し、ドキュメント内の位置順序（構造的順序）を繋ぐエッジを作成すること

**Step 2: 実装**

推定ロジックを順次実行し、関連性や時系列によるエッジ候補のリストを作成する。推定された複数のエッジはループで `GraphAdapter.create_edge` を呼び出すのではなく、必ず `GraphAdapter.create_edges_batch` を用いて一括登録（バルクインサート）し、N+1問題によるパフォーマンス劣化を防ぐこと。

**Step 3: Commit**

```bash
git commit -m "feat: Graph Linker (リレーションシップ自動推定) を実装"
```

---

### Task 4.6: Ingestion Pipeline 統合

**Files:**
- Create: `src/context_store/ingestion/pipeline.py`
- Create: `tests/unit/test_ingestion_pipeline.py`

**Step 1: テストを書く**

- Pipeline 全体のフロー: 入力 → Adapter → Chunker → Classifier → Embedding → Deduplicator → Graph Linker → 永続化
- **トランザクション境界検証**: `EmbeddingProvider` のモックに意図的な遅延（ネットワークI/O待機のシミュレート）を仕込み、`embed` が完了する前に `StorageAdapter.begin` や `save_memory` が決して呼び出されないこと（実行順序の厳密なアサート）をテストし、`SQLITE_BUSY` の発生要因となるトランザクション内待機がないことを保証する。

**Step 2: 実装**

各コンポーネントを順番に呼び出す IngestionPipeline クラス。
**注意 (トランザクション境界):** `EmbeddingProvider` によるベクトル化処理（重いネットワーク待機）は、必ず `StorageAdapter` の書き込みトランザクション (`save_memory` 等) を開始する**前**に完了させてください。トランザクション内で待機すると SQLite の `SQLITE_BUSY` (busy_timeout) を引き起こす原因となります。

**Step 3: Commit**

```bash
git commit -m "feat: Ingestion Pipeline を統合"
```

---

## Phase 5: Retrieval Pipeline

### Task 5.1: Query Analyzer

**Files:**
- Create: `src/context_store/retrieval/__init__.py`
- Create: `src/context_store/retrieval/query_analyzer.py`
- Create: `tests/unit/test_query_analyzer.py`

**Step 1: テストを書く**

- 固有名詞/コード片 → keyword_weight が高い
- 「なぜ」「原因」 → graph_weight が高い
- 一般的なクエリ → vector_weight が高い
- 時間表現 → time_decay_enabled = True

**Step 2: 実装**

ルールベースのパターンマッチで SearchStrategy を決定。

**Step 3: Commit**

```bash
git commit -m "feat: Query Analyzer (意図解析・戦略決定) を実装"
```

---

### Task 5.2: Vector Search

**Files:**
- Create: `src/context_store/retrieval/vector_search.py`
- Create: `tests/unit/test_vector_search.py`

**Step 1: テスト + 実装**

EmbeddingProvider でクエリをベクトル化し、StorageAdapter.vector_search を呼び出す。

**Step 2: Commit**

```bash
git commit -m "feat: Vector Search を実装"
```

---

### Task 5.3: Keyword Search

**Files:**
- Create: `src/context_store/retrieval/keyword_search.py`
- Create: `tests/unit/test_keyword_search.py`

**Step 1: テスト + 実装**

StorageAdapter.keyword_search のラッパー。クエリの前処理（正規化等）を担当。

**Step 2: Commit**

```bash
git commit -m "feat: Keyword Search を実装"
```

---

### Task 5.4: Graph Traversal

**Files:**
- Create: `src/context_store/retrieval/graph_traversal.py`
- Create: `tests/unit/test_graph_traversal.py`

**Step 1: テスト + 実装**

- Vector Search で取得した上位ノードを起点として Graph Adapter で traverse
- SearchStrategy に基づくエッジタイプフィルタ
- **スーパーノード対策**: 各ノードからのエッジ展開（fan-out）時に取得上限（`Settings.graph_fanout_limit` から取得し適用）を設け、グラフ検索時のクエリ爆発を防ぐ
- **SUPERSEDES チェーン透過的解決**: `SUPERSEDES` エッジを辿るトラバーサルは論理深さカウントを消費しない実装とし、長大チェーンでも最新の Active ノードに到達可能にする。具体的には再帰的CTEにおいて論理深さ（`logical_depth`）と物理深さ（`physical_depth`）を分離し、`physical_depth` は常に +1、`logical_depth` は `CASE WHEN edge_type = 'SUPERSEDES' THEN logical_depth ELSE logical_depth + 1 END` で分岐更新する。探索停止条件に `visited_supersedes_ids` でのサイクル検出に加え、「物理的な最大ホップ数（`config.py` の `Settings.graph_max_physical_hops` [デフォ: 50] または環境変数経由のオーバーライド値）」を超過時というハードリミットを組み込む。**可視化要件**: ハードリミット到達時はエラーを投げずその到達時点の最新ノードを返すフェイルセーフ挙動とするが、将来的な概念ドリフトや異常のデバッグを可能にするため、Pythonの `logging` モジュールを使用して明確な警告ログ（例: `WARNING: Physical hops limit (50) reached for node {id}. Returning stale node.`）を必ず出力すること。この定数をGraph Adapterに注入（plumbing）することでテストやランタイムチューニングを容易にする。
- Neo4j 接続失敗時は空結果を返す（Graceful Degradation）

**Step 2: Commit**

```bash
git commit -m "feat: Graph Traversal を実装"
```

---

### Task 5.5: Result Fusion（RRF + 複合スコアリング）

**Files:**
- Create: `src/context_store/retrieval/result_fusion.py`
- Create: `tests/unit/test_result_fusion.py`

**Step 1: テストを書く**

- RRF スコアの正しい計算
- 時間減衰の適用（半減期 30 日）
- 重要度スコアの反映
- 複合スコアによるソート

**Step 2: 実装**

SPEC.md §5.4 の数式をそのまま実装。RRF スコアは理論上の最大スコア（weights_sumとkから算出）を用いて正規化する。

```python
import math

def normalize_rrf(scores: list[float], weights_sum: float = 1.0, k: int = 60) -> list[float]:
    if not scores:
        return []
        
    max_possible_score = weights_sum * (1.0 / (k + 2))
    if max_possible_score <= 0.0:
        return [0.0] * len(scores)
    
    normalized = []
    for s in scores:
        val = s / max_possible_score
        # [0.0, 1.0] にクランプ
        normalized.append(max(0.0, min(1.0, val)))
    return normalized

rrf_scores_raw = [sum(weight * 1/(K + rank + 1) for ...) for memory in results]
normalized_rrfs = normalize_rrf(rrf_scores_raw, weights_sum=1.0, k=K)

final_scores = []
for i in range(len(results)):
    time_decay = 0.5 ** (days_since_access_list[i] / half_life)
    score_i = 0.5 * normalized_rrfs[i] + 0.3 * time_decay + 0.2 * importance_score_list[i]
    final_scores.append(score_i)
```

**Step 3: Commit**

```bash
git commit -m "feat: Result Fusion (RRF + 時間減衰 + 複合スコアリング) を実装"
```

**Verification:**

```bash
Run: pytest tests/unit/test_result_fusion.py -v
Expected: PASS
```

**追加検証観点（RRF エッジケース）:**

- 入力が空配列の場合は空配列 `[]` を返す、または入力が非空で `theoretical_max`（または最大期待値）が 0 以下の場合は元の入力長と同じ長さの浮動小数点ゼロ配列（例: `[0.0, 0.0, ...]`）を返すこと
- 全ての結果が `[0.0, 1.0]` の範囲にクランプされていること
- 1 件のみ返る場合や同点のみの結果でも破綻しないこと
- `final_score` の並び順が期待通りになること

---

### Task 5.6: Post Processor

**Files:**
- Create: `src/context_store/retrieval/post_processor.py`
- Create: `tests/unit/test_post_processor.py`

**Step 1: テスト + 実装**

- プロジェクトフィルタ
- 最大トークン制限（`tiktoken` 等を用いた正確なトークン計算を実装）
  - **エンコーディング選択**: まず `tiktoken` の `encoding_for_model(model)` を第一候補としてトークンエンコーダの取得を試みる。
  - **プロバイダー依存フォールバック**: `encoding_for_model` が例外エラーや未対応を返す場合（ローカルモデルや一部の LiteLLM モデル等を利用している時）、`src/context_store/embedding/protocols.py` で定義した（Task 3.1） `TokenCounter` Protocol を経由してフォールバックする。
  - **近似による過大推定でのガード**: デフォルトエンコーディング（未指定時の `cl100k_base` 等）でのカウントも利用不可能な場合の最終手段として文字数近似を使用する。この際は、**必ず安全側（過大推定）**となる式（例: `ceil(len(text) * safety_margin)` 、safety_margin は 0.5~0.6 等）を採用し、`max_tokens` 超過を防ぐためのガードとする。
  - **エラーハンドリングとロギング**: フォールバックが発生した場合は、その決定と使用するフォールバックポリシー（利用したデフォルトエンコーディング名や文字数近似でのマージン値など）をシステムログに明示的に記録する。
- access_count / last_accessed_at の更新

**Step 2: Commit**

```bash
git commit -m "feat: Post Processor (フィルタ・トークン制限・アクセス記録) を実装"
```

---

### Task 5.7: Retrieval Pipeline 統合

**Files:**
- Create: `src/context_store/retrieval/pipeline.py`
- Create: `tests/unit/test_retrieval_pipeline.py`

**Step 1: テスト + 実装**

Query Analyzer → 並列検索 → Result Fusion → Post Processor の全フロー統合。

**Step 2: Commit**

```bash
git commit -m "feat: Retrieval Pipeline を統合"
```

---

## Phase 5.5: 中間統合テスト（Ingestion → Retrieval 貫通検証）

### Task 5.5.1: SQLite 統合テスト

**Files:**
- Create: `tests/integration/test_ingestion_retrieval.py`

**Step 1: テストを書く**

- 実 SQLite DB（一時ファイル）+ MockEmbeddingProvider（固定ベクトル）
- Ingestion Pipeline 経由で 5〜10件の記憶を保存
- Retrieval Pipeline で検索し、RRF スコアが正規化済みであることを検証
- 保存 → 検索 → 結果検証の往復テスト
- Deduplicator の Append-only 動作検証（类似データの重複保存）

**Step 2: Commit**

```bash
git commit -m "test: 中間統合テスト (Ingestion → Retrieval 貫通検証) を追加"
```

---

## Phase 6: Lifecycle Manager

### Task 6.1: Decay Scorer

**Files:**
- Create: `src/context_store/lifecycle/__init__.py`
- Create: `src/context_store/lifecycle/decay_scorer.py`
- Create: `tests/unit/test_decay_scorer.py`

**Step 1: テストを書く**

- 作成直後の記憶: 高スコア
- 30日経過: スコアが約半分
- 90日経過: 閾値以下

**Step 2: 実装**

SPEC.md §6.3 の複合スコア計算式を実装。

**Step 3: Commit**

```bash
git commit -m "feat: Decay Scorer (減衰スコア計算) を実装"
```

---

### Task 6.2: Archiver + Purger

**Files:**
- Create: `src/context_store/lifecycle/archiver.py`
- Create: `src/context_store/lifecycle/purger.py`
- Create: `tests/unit/test_archiver.py`
- Create: `tests/unit/test_purger.py`

**Step 1: テスト + 実装**

- Archiver: スコアが閾値以下の記憶を Archived に遷移
- Purger: Archived 後 N 日経過した記憶を物理削除（Storage + Graph 連動）

**Step 2: Commit**

```bash
git commit -m "feat: Archiver + Purger を実装"
```

---

### Task 6.3: Consolidator

**Files:**
- Create: `src/context_store/lifecycle/consolidator.py`
- Create: `tests/unit/test_consolidator.py`

**Step 1: テスト + 実装**

- 統合候補（Deduplicator がマーク済み）の記憶群を取得
- 最新の記憶をベースに、古い記憶の情報をマージ
- Neo4j で SUPERSEDES リレーションを作成
- 埋め込みベクトルの再計算

**Step 2: Commit**

```bash
git commit -m "feat: Consolidator (統合処理) を実装"
```

---

### Task 6.4: Lifecycle Manager 統合（イベント駆動型）

**Files:**
- Create: `src/context_store/lifecycle/manager.py`
- Create: `tests/unit/test_lifecycle_manager.py`

**Step 1: テスト + 実装**

APScheduler の代わりにイベント駆動型のレイジークリーンアップを実装:

- `on_memory_saved()`: 保存カウンターをインクリメント、「保存回数閾値（50回）」のみを判定し `run_cleanup` を非同期トリガー
- `_check_time_based_cleanup()`: MCPサーバーの初期化時（初回のみ）に非同期タスクとして実行。「前回から1日以上経過」を判定し `run_cleanup` をトリガーする。毎回のツール呼び出しで時間判定を行わずオーバーヘッドを削減
- `run_cleanup()`: Decay Scorer / Archiver / Consolidator / Purger / Stats Collector を順次実行
- `last_cleanup_at` と `save_count` を **DB に永続化**（プロセス寿命が短いため）
- SQLite バックエンドの場合、クリーンアップ処理の最後に WAL 縮小を試行するロジックを実装する：
    - `PRAGMA wal_checkpoint(PASSIVE)` の実行
    - 実行結果とWALサイズの**監視・可視化**
    - **自動フェイルセーフ機構**：「`PASSIVE` が継続的に失敗」かつ「WALファイルサイズが閾値（100MB）を超過」の両条件を検出した場合 → 警告ログ出力 + 自動的に `PRAGMA wal_checkpoint(TRUNCATE)` を試行（または次回起動時まで待機）するシステムによる自律的リカバリを実装すること。
- クリーンアップは `asyncio.create_task()` で非同期実行し、ツール応答をブロックしない。
- **WAL設定の外部化と設定値の利用（config.py / .env）:**
    - ハードコードされた閾値や時間枠を排除し、`config.py` 等で明示的な設定として定義すること。
    - 環境変数から読み込む `Settings` オブジェクトに以下を追加し `.env.example` にも記載する：
        - `WAL_TRUNCATE_SIZE_BYTES` (例: 104857600)
        - `WAL_PASSIVE_FAIL_CONSECUTIVE_THRESHOLD` (例: 3)
        - `WAL_PASSIVE_FAIL_WINDOW_SECONDS` (例: 600)
        - `WAL_PASSIVE_FAIL_WINDOW_COUNT_THRESHOLD` (例: 5)
        - `WAL_CHECKPOINT_MODE_PASSIVE` (デフォルト: "PASSIVE")
        - `WAL_CHECKPOINT_MODE_TRUNCATE` (デフォルト: "TRUNCATE")
    - 非同期のチェックポイント・TRUNCATE処理のコードパス、および `lifecycle_wal_state` への書き込みロジックはリテラルではなくこれらの `Settings` / `config` の閾値を読み取って動作すること。
    - テスト／ドキュメント要件：単体テスト・結合テストでは、ソースコードを変更せずにテスト用の `Settings` フィクスチャや環境変数の上書き（依存性の注入）によってこれらの閾値を操作・シミュレートできるオーバーライドパターンを実装すること。
- **WALステータスの永続化スキーマと更新ルール:**
    - 判定用のカウンタやステータスは `lifecycle_state` テーブル等に漠然と保持するのではなく、`lifecycle_state` テーブル（または新規の `lifecycle_wal_state` テーブル）に以下の明確な名前と型のカラムを追加し永続化する：
        - `wal_failure_count` (INTEGER): チェックポイントの総失敗回数
        - `wal_last_failure_ts` (TIMESTAMP UTC): 最後のチェックポイント失敗日時
        - `wal_last_checkpoint_result` (TEXT): 最新の実行結果（例: `"PASSIVE_OK"`, `"PASSIVE_FAIL"`, `"TRUNCATE_OK"`, `"TRUNCATE_FAIL"`）
        - `wal_last_observed_size_bytes` (INTEGER): 最後に観測されたWALファイルサイズ
        - `wal_consecutive_passive_failures` (INTEGER): 連続して失敗した `PASSIVE` チェックポイントの回数
        - `wal_failure_window` (JSON): 過去設定時間（例: `WAL_PASSIVE_FAIL_WINDOW_SECONDS`）の失敗タイムスタンプの配列（リングバッファ）を保持するスライディングウィンドウ
    - **非同期チェックポイントタスクによる更新ルール:**
        - `PASSIVE` の試行が失敗した場合：`wal_failure_count` と `wal_consecutive_passive_failures` をインクリメントし、`wal_last_failure_ts` に現在時刻、`wal_last_checkpoint_result` を設定。さらに `wal_failure_window` に今回の失敗タイムスタンプを追加する。
        - 試行が成功した場合：`wal_consecutive_passive_failures` を `0` にリセットし、`wal_last_checkpoint_result` に成功結果を設定、`wal_last_failure_ts` は `null` にクリア。
        - スライディングウィンドウの更新：状態更新のたびに `wal_failure_window` から現在時刻より設定秒数（例: `WAL_PASSIVE_FAIL_WINDOW_SECONDS`）以上古いエントリをパージする。このフィールドをSource of Truthとして設定時間内の失敗回数を計算し、これを用いて「設定時間に設定回数（例: 5回）以上の失敗」などの閾値判定を行うこと。
        - 観測が行われるたび：常に `wal_last_observed_size_bytes` を更新する。
    - **トランザクションと起動時の復元:**
        - これらの状態更新は、チェックポイントロジックで使用されるDBトランザクション内でアトミックに行うこと（`PRAGMA wal_checkpoint` を実行する非同期タスクと、自動 `TRUNCATE` フォールバックコードの両方がこれらのカラムを書き込むこと）。
        - アプリケーションは起動時にこれらのフィールドを読み込み、プロセス再起動後も失敗カウンタや状態を復元してから、上記 `Settings` 値を元に `TRUNCATE` をトリガーするべきかどうかの判定を行うこと。
- `graceful_shutdown()`: FastMCP の lifecycle / lifespan hook から呼び出せるようにし、ASGI/Uvicorn 側がシグナルを所有する場合はそちらを優先する
- アプリケーション側で `SIGINT`/`SIGTERM` ハンドラを登録するのは stdio 等で必要な場合に限定し、既存ハンドラを無条件に上書きしない
- 進行中タスクはタイムアウト付き（5秒）で完了待機し、`adapter.dispose()` も `asyncio.wait_for(..., timeout=5)` で保護する
- `asyncio.CancelledError` / `asyncio.TimeoutError` 時はロールバック / 後始末を試行し、`cleanup_running` と `last_cleanup_at` の整合性を崩さない
- 各ジョブは**冪等**に実装（中断後の再実行で同じ結果に収束、チャンク単位コミット）

**永続化詳細:**

| モード | 永続化先 | 接続元 |
| --- | --- | --- |
| SQLite | `lifecycle_state` テーブル（同一 DB ファイル） | SQLiteStorageAdapter |
| PostgreSQL | `lifecycle_state` テーブル（Task 2.1a で定義） | PostgresStorageAdapter |

**`cleanup_running` ロック（冪等性保証）:**

- SQLite: クリーンアップ開始時に `cleanup_running=true` + `updated_at` を設定
- PostgreSQL: `pg_try_advisory_lock(...)` でセッションロックを取得できた場合のみ実行する
- SQLite: クリーンアップ完了時に `cleanup_running=false` に戻す
- PostgreSQL: 完了時に `pg_advisory_unlock(...)` を実行する
- **スタルロック解放**: `cleanup_running=true` かつ `updated_at` が 10分以上前の場合、
  プロセスクラッシュとみなしロックを強制解放

**テスト要件:**

- `on_memory_saved()` がカウンターをインクリメントすること
- 閾値到達時に `run_cleanup` がトリガーされること
- 冪等性: 2回連続実行で同じ結果に収束すること
- スタルロック: 古い `cleanup_running` が解放されること
- `last_cleanup_at` が DB に永続化されること
- PostgreSQL モードでは advisory lock が二重実行を防ぐこと
- シャットダウン経路で cleanup task と adapter dispose が 5 秒以内に収束すること

**Step 2: Commit**

```bash
git commit -m "feat: Lifecycle Manager (イベント駆動型スケジューリング) を実装"
```

**Verification:**

```bash
Run: pytest tests/unit/test_lifecycle_manager.py -v
Expected: PASS
```

---

## Phase 7: RL 拡張ポイント

### Task 7.1: Extension Protocols + NoOp 実装

**Files:**
- Create: `src/context_store/extensions/__init__.py`
- Create: `src/context_store/extensions/protocols.py`
- Create: `src/context_store/extensions/noop.py`
- Create: `tests/unit/test_extensions.py`

**Step 1: テスト + 実装**

SPEC.md §10 の ActionLogger / RewardSignal / PolicyHook Protocol を定義。
NoOp 実装（何もしない）をデフォルトとして作成。

**Step 2: Commit**

```bash
git commit -m "feat: RL 拡張ポイント (Protocol + NoOp) を実装"
```

---

## Phase 8: Orchestrator + MCP Server

### Task 8.1: Orchestrator

**Files:**
- Create: `src/context_store/orchestrator.py`
- Create: `tests/unit/test_orchestrator.py`

**Step 1: テスト + 実装**

- Ingestion / Retrieval / Lifecycle の3パイプラインを保持
- RL 拡張フック（ActionLogger / RewardSignal / PolicyHook）を注入
- save / search / search_graph / delete / prune / stats の各操作を
  適切なパイプラインに委譲
- **ベクトル次元数フェイルファストチェック（SPEC.md §9.1）:**
  - 初期化時に `storage.get_vector_dimension()` と `embedding_provider.dimension` を比較
  - `stored_dim is not None and stored_dim != current_dim` の場合 `ConfigurationError` を発生
  - 例外メッセージにて、具体的なリカバリ手順（`SQLITE_DB_PATH` の変更 または DB ファイルの手動削除）を明示し、運用デッドロックを防ぐ
  - `stored_dim is None` の場合は警告ログを出力し続行（初回起動時は次元不明）

**Step 2: Commit**

```bash
git commit -m "feat: Orchestrator を実装"
```

---

### Task 8.2: MCP Server (FastMCP)

**Files:**
- Create: `src/context_store/server.py`
- Create: `tests/unit/test_server.py`

**Step 1: テスト + 実装**

SPEC.md §7 の全7ツール + 2リソースを FastMCP で定義:
- `memory_save` (引数 `source` のデフォルト値はエージェントの自律利用に合わせ `"conversation"` とし、明示的でない場合にも対応するよう実装すること。`tests/unit/test_server.py` にて、引数なしで呼び出した際に `"conversation"` となること、明示的に `"manual"` を指定した際に `"manual"` が保持されることを検証する回帰テストを追加すること)
- `memory_save_url`
- `memory_search`
- `memory_search_graph`
- `memory_delete`
- `memory_prune`
- `memory_stats`
- Resource: `memory://stats`, `memory://projects`

遅延ロード: 初回ツール呼び出し時に Orchestrator を初期化。

**排他制御要件（必須）:**

複数ツールの同時非同期呼び出し時にデッドロック・重複初期化を防ぐため、
`asyncio.Lock` による排他制御を実装する:

```python
class Server:
    def __init__(self):
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False
        self._url_semaphore: asyncio.Semaphore | None = None

    async def _ensure_initialized(self):
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if not self._initialized:
                await self._do_initialize()
                if self._url_semaphore is None:
                    settings = Settings()
                    self._url_semaphore = asyncio.Semaphore(settings.url_fetch_concurrency)
                self._initialized = True
```

各ツールハンドラの冒頭で `await self._ensure_initialized()` を呼び出す。

**URL 取得の並行制限要件とプロセススコープ（必須）:**

> **開発者向け Docstring 要件**: URLフェッチ用の `asyncio.Semaphore` はインスタンスレベルの排他制御です。MCPサーバーが複数プロセスで起動された場合、この Semaphore はプロセス単位での制限となる旨を `server.py` のコードコメントに明記してください。

`memory_save_url` は最大 30 秒の HTTP タイムアウトを持つため、
同時多数の呼び出しで非同期ワーカーが枯渇するリスクがある。
`asyncio.Semaphore` で同時実行数を制限する:

```python
async def memory_save_url(self, url: str, ...):
    await self._ensure_initialized()
    settings = Settings()
    async with self._url_semaphore:
        content = await fetch_url(
            url,
            timeout=settings.url_timeout_seconds,
            max_redirects=settings.url_max_redirects,
        )
        ...
```

**Step 2: Commit**

```bash
git commit -m "feat: MCP Server (FastMCP) を実装"
```

**URL 関連設定への依存（Task 1.3 で追加済み）:**

- `settings.url_fetch_concurrency` → `asyncio.Semaphore` の上限値
- `settings.url_timeout_seconds` → `httpx` の HTTP timeout
- `settings.url_max_redirects` → リダイレクト上限
- URLAdapter が `Settings` インスタンスを受け取る初期化経路（コンストラクタ/工場関数等）を明確にする
- SSRF 対策設定 (`settings.allow_private_urls`, `settings.url_max_response_bytes`, `settings.url_allowed_content_types`) を必ず `URLAdapter` に伝播させる
- 全ツールハンドラの冒頭で `await self._ensure_initialized()` を呼び出し、安全に初期化された `URLAdapter` を利用する

**Verification:**

```bash
Run: pytest tests/unit/test_server.py -v
Expected: PASS
```

---

### Task 8.3: エントリーポイント + 起動確認

**Files:**
- Modify: `pyproject.toml` (scripts セクション追加)
- Create: `src/context_store/__main__.py`

**Step 1: 実装**

```python
# src/context_store/__main__.py
from context_store.server import server

def main():
    server.run()

if __name__ == "__main__":
    main()
```

pyproject.toml に `[project.scripts]` を追加:

```toml
[project.scripts]
context-store = "context_store.__main__:main"
```

**Step 2: 起動確認**

Run: `python -m context_store`
Expected: MCP サーバーが stdio モードで起動

**Step 3: Commit**

```bash
git commit -m "feat: エントリーポイントを追加"
```

---

## Phase 9: 統合テスト + ドキュメント

### Task 9.1: エンドツーエンド統合テスト

**Files:**
- Create: `tests/integration/test_e2e.py`
- Create: `tests/conftest.py`

**Step 1: テストを書く**

2つの構成で E2E テストを実行:

**A) ライトウェイトモード（SQLite）:**

外部サービス不要。一時ファイルを使用して全フローを検証。

**B) フルモード（PostgreSQL + Neo4j + Redis）:**

Docker 上の全バックエンドに接続して以下のフローを検証:
1. `memory_save` で記憶を保存
2. `memory_search` でハイブリッド検索
3. `memory_search_graph` でグラフトラバーサル
4. `memory_save_url` で URL 取り込み
5. `memory_stats` で統計確認
6. `memory_prune` でクリーンアップ
7. `memory_delete` で削除

**テストデータ隔離戦略:**
- PostgreSQL: テスト毎のトランザクション・ロールバック
- Neo4j: テスト毎に `MATCH (n) DETACH DELETE n` でクリア
- Redis: テスト毎に `FLUSHDB` でクリア
- SQLite: テスト毎に一時ファイルを新規作成

**C) 並行書き込みストレステスト（SQLite）:**

WAL モード + `busy_timeout=5000` の設定が実運用で十分かを検証:

- 3〜5 プロセスから同時に `memory_save` を実行
- `busy_timeout` 内でリトライが成功することを検証
- `memory_search` が書き込み中にもブロックされないことを検証
- `SQLITE_BUSY` エラーが 0 件であることを確認
- Lifecycle Manager のクリーンアップ（大量 UPDATE/DELETE）をバックグラウンドで同時実行
- 再帰的 CTE（グラフ検索）実行中の DELETE 競合がデッドロックしないことを検証
- `test_sqlite_stress_process_crash`: `memory_save` 中の worker process crash を模擬し、stale lock 解放と `cleanup_running` 回復を確認
- `test_sqlite_wal_size_monitor`: heavy write 後も WAL サイズ増大が有界で、checkpoint が発火することを確認
- テスト末尾で `PRAGMA integrity_check` による DB 整合性検証を実行

**Step 2: Commit**

```bash
git commit -m "test: エンドツーエンド統合テストを追加"
```

---

### Task 9.2: README.md 更新

**Files:**
- Modify: `README.md`

**Step 1: 実装**

v2.0 の内容に全面更新:
- 概要・特徴
- クイックスタート（Docker Compose + pip install + MCP 設定）
- 設定リファレンス
- MCPツール一覧

**Step 2: Commit**

```bash
git commit -m "docs: README.md を v2.0 に更新"
```

**Verification:**

```bash
Run: python -m context_store --help
Expected: エントリーポイントが解決される（ヘルプまたは起動）
```

---

### Task 9.3: MCP クライアント設定生成

**Files:**
- Create: `scripts/generate_config.py`

**Step 1: 実装**

Claude Desktop / Cursor / その他クライアント用の MCP 設定 JSON を生成するスクリプト。

```json
{
  "mcpServers": {
    "context-store": {
      "command": "python",
      "args": ["-m", "context_store"],
      "env": {
        "POSTGRES_PASSWORD": "...",
        "NEO4J_PASSWORD": "..."
      }
    }
  }
}
```

**Step 2: Commit**

```bash
git commit -m "feat: MCP クライアント設定生成スクリプトを追加"
```

**Verification:**

```bash
Run: python scripts/generate_config.py > /tmp/context-store-config.json
Run: python -m json.tool /tmp/context-store-config.json > /dev/null
Expected: PASS（有効な JSON が出力される）
```

---

### Task 9.4: パフォーマンスベンチマークスイート

**Files:**
- Modify: `pyproject.toml` (`pytest-benchmark` を dev 依存へ追加)
- Create: `tests/benchmark/test_performance.py`

**Step 1: 実装**

- `pytest-benchmark` を dev 依存に追加
- DBに 10,000 件ダミーデータを投入した状態での `memory_search` の P50/P95/P99 レイテンシ測定
- `memory_save` のレイテンシ測定
- 初期化（ハンドシェイク）レイテンシ測定
- SQLite / PostgreSQL の比較ベンチマークを追加
- `memory_search_graph` の depth=1,2,3,5 比較を追加
- Deduplicator 経路を通る top-5 ベクトル検索コストを追加
- RRF 正規化オーバーヘッドを result_count=10,100,1000 で測定
- `db_backend`, `graph_depth`, `top_k`, `result_count` を parametrization し、同一 10,000 件 fixture を使って決定論的に実行する
- ベンチ結果は Task 9.4 の成果物として保存し、SPEC.md §13 の目標値との比較を記録する

**Step 2: Commit**

```bash
Run: pytest tests/benchmark/test_performance.py --benchmark-only -v
Expected: ベンチマークが収集され、結果アーティファクトが出力される

git add tests/benchmark/
git add pyproject.toml
git commit -m "test: パフォーマンスベンチマークスイートを追加"
```

---

## Phase Summary

| Phase | 内容 | Task数 |
|---|---|---|
| Phase 1 | プロジェクト基盤 | 5 |
| Phase 2 | Storage Layer | 8 |
| Phase 3 | Embedding Provider | 4 |
| Phase 4 | Ingestion Pipeline | 6 |
| Phase 5 | Retrieval Pipeline | 7 |
| Phase 5.5 | 中間統合テスト | 1 |
| Phase 6 | Lifecycle Manager | 4 |
| Phase 7 | RL 拡張ポイント | 1 |
| Phase 8 | Orchestrator + MCP Server | 3 |
| Phase 9 | 統合テスト + ドキュメント | 4 |
| **合計** | | **43 Tasks** |
