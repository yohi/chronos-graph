# Supabase Storage Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prisma Accelerate ストレージバックエンドを Supabase Data API (PostgREST) ベースのアダプタへ完全に置換し、HTTPS のみで動作するクラウドストレージを実現する。

**Architecture:** `src/context_store/storage/supabase.py` に `StorageAdapter` Protocol 準拠の `SupabaseStorageAdapter` を新設し、`supabase>=2.4.0` の `AsyncClient` で PostgREST を呼び出す。複雑なクエリ (ベクトル類似検索、サーバサイド DISTINCT、原子的 increment) は Postgres 関数 (RPC) に切り出して HTTP の Read-Modify-Write 競合を回避する。

**Tech Stack:** Python 3.12+, `supabase>=2.4.0` (`AsyncClient` + `postgrest`), `pydantic-settings`, `pytest` + `pytest-asyncio` + `unittest.mock.AsyncMock`, GitHub Actions, devcontainer (Python 3.12-slim + uv)

**Design Spec:** [`docs/superpowers/specs/2026-05-18-supabase-storage-adapter-design.md`](../specs/2026-05-18-supabase-storage-adapter-design.md)

---

## Git Branch Workflow (AI-Native Stacked PR)

このプロジェクトでは [AI-Native Stacked PR Workflow](https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb) に厳密に準拠して作業します。

### ブランチ命名規約
- フェーズ統合ブランチ (Phase Base): `feat/supabase-adapter/phase-N`
- タスクブランチ: `feat/supabase-adapter/phase-N-task-N.M-<slug>`
- 統合ターゲット: `master`

### 派生元判断ルール

| タスクの性質 | 派生元 | Draft PR の Target |
| --- | --- | --- |
| **単体で完結する** (他タスクの差分に依存せずに `master` へ取り込んでも壊れない) | `master` (Base) | `master` |
| **直前タスクに依存する** (前タスクの差分が前提) | 直前タスクのブランチ | 直前タスクのブランチ |

### 各タスクの締めくくり

すべてのタスクの実装手順の最後に**「Draft PR を作成する」アクション**を必ず実行します。Draft PR は上記の派生元判断ルールに従ったターゲットに対して作成し、PR 本文には親タスクへの参照と完了条件チェックリストを含めます。

### Devcontainer 強制

**すべてのテスト・型チェック・lint・スクリプト実行は devcontainer 内で行います。** ホスト側で直接 `pytest` 等を起動しないでください。各タスクの確認手順には `devcontainer exec ...` 形式または devcontainer 内のシェルから実行する前提でコマンドを記載しています。

---

## File Structure

新規作成 / 修正対象ファイルとその責務:

| 区分 | パス | 責務 |
| --- | --- | --- |
| 新規 | `supabase/migrations/20260518000001_initial_schema.sql` | `memories` テーブル + B-tree/GIN/HNSW インデックス + 拡張 (vector, pg_trgm) |
| 新規 | `supabase/migrations/20260518000002_rpc_functions.sql` | `vector_search` / `list_projects` / `increment_memory_access_count` RPC + 権限付与 |
| 新規 | `src/context_store/storage/supabase.py` | `SupabaseStorageAdapter` (Protocol 実装本体) |
| 新規 | `tests/unit/storage/test_supabase_adapter.py` | アダプタ単体テスト (AsyncMock ベース、`make_mock_*` ヘルパを同ファイル内で定義) |
| 変更 | `pyproject.toml` | `storage-supabase` extra 追加 → 後フェーズで `storage-prisma` extra と `prisma.*` mypy override を削除 |
| 変更 | `src/context_store/config.py` | `supabase_url` / `supabase_key` フィールド追加、`embedding_dimension` デフォルト 1024 → 768、`SUPABASE_VECTOR_DIMENSION` 定数、validator 追加 → 後フェーズで `prisma_database_url` と `"prisma"` リテラルを削除 |
| 変更 | `src/context_store/storage/factory.py` | `_create_storage_adapter` / `_create_graph_adapter` に supabase 分岐追加 → 後フェーズで prisma 分岐削除 |
| 変更 | `.github/workflows/ci.yml` | ランナーを `ubuntu-slim` に変更、`master` トリガー明示、後フェーズで Prisma generate ステップを削除 |
| 変更 | `.devcontainer/devcontainer.json` | 後フェーズで `Prisma Generate` タスク削除 |
| 変更 | `.env.example` | 後フェーズで `SUPABASE_URL` / `SUPABASE_KEY` 追記 |
| 変更 | `README.md` | 移行手順を追記 |
| 削除 | `src/context_store/storage/prisma.py` | Prisma アダプタ本体 (Phase 5) |
| 削除 | `prisma/schema.prisma` および `prisma/` ディレクトリ | Prisma スキーマ (Phase 5) |
| 削除 | `tests/unit/storage/test_prisma_*.py` / `tests/integration/test_orchestrator_prisma.py` | Prisma 専用テスト (Phase 5) |
| 削除 | `.env.prisma.example` / `.env.prisma.template` | Prisma 用 env テンプレ (Phase 5) |

---

## Phase 0: Infrastructure Baseline

**Phase Base ブランチ:** `feat/supabase-adapter/phase-0` ← `master`

既存の CI ワークフローと devcontainer は本リポジトリにすでに存在しているため、Phase 0 はゼロからの構築ではなく、本作業の前提条件 (master ターゲット、`ubuntu-slim` ランナー、`supabase/migrations/` ディレクトリの存在) を整える "ベースライン整合" を目的とします。

### Task 0.1: CI ワークフローと migrations ディレクトリの初期整備

**派生元:** `master` (Base) — 単体で完結 (既存テストを壊さず、Prisma 依存も維持されたまま)

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `supabase/migrations/.gitkeep`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/supabase-adapter/phase-0-task-0.1-ci-baseline
```

- [ ] **Step 2: CI ワークフローを修正してランナーと master トリガーを明示**

`.github/workflows/ci.yml` を編集します。`runs-on` を `ubuntu-slim` (自己ホストランナーラベル) に変更し、`push.branches` を明示的に `master` を含む形に整えます。

```yaml
name: CI

on:
  push:
    branches: ["master", "**"]
  pull_request:
    branches: ["master", "main"]

jobs:
  test:
    runs-on: ubuntu-slim

    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install uv
        uses: astral-sh/setup-uv@1edb52594c857e2b5b13128931090f0640537287 # v5.3.0
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Setup Node.js (for Prisma CLI)
        uses: actions/setup-node@1d0ff469b7ec7b3cb9d8673fde0c81c44821de2a # v4.2.0
        with:
          node-version: '20'

      - name: Generate Prisma Client
        run: uv run prisma generate --schema=./prisma/schema.prisma

      - name: Run ruff check
        run: uv run ruff check src/ tests/

      - name: Run ruff format check
        run: uv run ruff format --check src/ tests/

      - name: Run mypy
        run: uv run mypy src/

      - name: Run unit tests
        run: uv run pytest tests/unit -v --cov=src/context_store --cov-report=term-missing
        env:
          OPENAI_API_KEY: sk-dummy-key-for-ci-validation
```

- [ ] **Step 3: `supabase/migrations/` ディレクトリを作成して `.gitkeep` を置く**

```bash
mkdir -p supabase/migrations
touch supabase/migrations/.gitkeep
```

- [ ] **Step 4: devcontainer 内で CI 相当のチェックがグリーンであることを確認**

devcontainer のシェルで実行:

```bash
uv sync --all-extras --dev
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

Expected: すべて PASS (既存の Prisma 関連テストを含めて変化なし)

- [ ] **Step 5: コミット**

```bash
git add .github/workflows/ci.yml supabase/migrations/.gitkeep
git commit -m "ci: Supabase 対応に向けて CI ランナーを ubuntu-slim へ変更 & migrations ディレクトリ作成"
```

- [ ] **Step 6: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master --title "ci: align CI runner & scaffold supabase/migrations" \
  --body "Phase 0 Task 0.1. CI runner → ubuntu-slim, master トリガーを明示、supabase/migrations ディレクトリ追加。"
```

---

## Phase 1: SQL Migrations

**Phase Base ブランチ:** `feat/supabase-adapter/phase-1` ← `master` (Phase 0 のマージ完了後)

設計書 Section 4 で定義された `supabase/migrations/*.sql` をリポジトリに追加します。Python 側からは未参照のため、コード変更なしで完結します。

### Task 1.1: 初期スキーマ SQL を追加

**派生元:** `master` (Base) — 単体で完結 (新規 SQL ファイルのみ。既存コードへの影響なし)

**Files:**
- Create: `supabase/migrations/20260518000001_initial_schema.sql`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/supabase-adapter/phase-1-task-1.1-initial-schema
```

- [ ] **Step 2: 初期スキーマ SQL を作成**

`supabase/migrations/20260518000001_initial_schema.sql` をプロジェクトルートに新規作成し、以下を全文書き込み:

```sql
-- pgvector + pg_trgm 拡張
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- memories テーブル
CREATE TABLE IF NOT EXISTS memories (
    id                 UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    content            TEXT         NOT NULL,
    memory_type        VARCHAR(20)  NOT NULL CHECK (
        memory_type IN ('episodic', 'semantic', 'procedural')
    ),
    source_type        VARCHAR(20)  NOT NULL CHECK (
        source_type IN ('conversation', 'manual', 'url')
    ),
    source_metadata    JSONB        DEFAULT '{}',
    embedding          vector(768),
    semantic_relevance FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (semantic_relevance >= 0 AND semantic_relevance <= 1),
    importance_score   FLOAT        NOT NULL DEFAULT 0.5
                       CHECK (importance_score >= 0 AND importance_score <= 1),
    access_count       INT          NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    last_accessed_at   TIMESTAMPTZ  DEFAULT NOW(),
    created_at         TIMESTAMPTZ  DEFAULT NOW(),
    updated_at         TIMESTAMPTZ  DEFAULT NOW(),
    archived_at        TIMESTAMPTZ,
    tags               TEXT[]       DEFAULT '{}',
    project            TEXT,
    content_hash       TEXT         NOT NULL UNIQUE
);

-- B-tree indexes
CREATE INDEX IF NOT EXISTS idx_memories_memory_type    ON memories (memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_source_type    ON memories (source_type);
CREATE INDEX IF NOT EXISTS idx_memories_archived_at    ON memories (archived_at);
CREATE INDEX IF NOT EXISTS idx_memories_project        ON memories (project);
CREATE INDEX IF NOT EXISTS idx_memories_created_at     ON memories (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created_at_id  ON memories (created_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_memories_tags_gin       ON memories USING gin (tags);

-- HNSW vector index
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Full-text search (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_memories_content_fts
    ON memories USING gin (content gin_trgm_ops);
```

- [ ] **Step 3: devcontainer 内で SQL の構文妥当性を簡易確認**

PostgreSQL クライアントを使った文法チェックを devcontainer 内で実行 (ローカル `docker compose` の `postgres` コンテナを利用)。本 migration は DDL のみで GRANT を含まないため、`ON_ERROR_STOP=on` で全エラーを fail させる:

```bash
docker compose up -d postgres
docker compose exec -T postgres psql -U context_store -d context_store \
    --set=ON_ERROR_STOP=on -f - < supabase/migrations/20260518000001_initial_schema.sql
```

Expected: 終了コード 0。失敗した場合は SQL の構文/拡張に問題があるため修正して再実行。

(本番 Supabase への適用は `Phase 1: 完了後の手順` で別途実施)

- [ ] **Step 4: コミット**

```bash
git add supabase/migrations/20260518000001_initial_schema.sql
git commit -m "feat(supabase): memories テーブルとインデックスの初期スキーマ migration を追加"
```

- [ ] **Step 5: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master --title "feat(supabase): add initial schema migration" \
  --body "Phase 1 Task 1.1. memories テーブル + 拡張 (vector, pg_trgm) + B-tree/GIN/HNSW インデックス。"
```

### Task 1.2: RPC 関数 SQL を追加

**派生元:** Task 1.1 のブランチ — RPC は Task 1.1 で定義された `memories` テーブルを前提とするためスタック

**Files:**
- Create: `supabase/migrations/20260518000002_rpc_functions.sql`

- [ ] **Step 1: ブランチ作成 (Task 1.1 上に積み上げ)**

```bash
git checkout feat/supabase-adapter/phase-1-task-1.1-initial-schema
git checkout -b feat/supabase-adapter/phase-1-task-1.2-rpc-functions
```

- [ ] **Step 2: RPC 関数 SQL を作成**

`supabase/migrations/20260518000002_rpc_functions.sql` を作成し、以下を全文書き込み:

```sql
-- ============================================================
-- vector_search: pgvector の <=> (cosine distance) を使って
-- 上位 K 件取得。score = 1 - distance でコサイン類似度を返す。
-- p_project が NULL なら全プロジェクト対象。
-- ============================================================
CREATE OR REPLACE FUNCTION vector_search(
    query_embedding vector(768),
    match_count     integer,
    p_project       text DEFAULT NULL
)
RETURNS TABLE (
    id                 uuid,
    content            text,
    memory_type        varchar,
    source_type        varchar,
    source_metadata    jsonb,
    embedding          vector(768),
    semantic_relevance float,
    importance_score   float,
    access_count       integer,
    last_accessed_at   timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    archived_at        timestamptz,
    tags               text[],
    project            text,
    content_hash       text,
    score              float
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT
        m.id, m.content, m.memory_type, m.source_type, m.source_metadata,
        m.embedding, m.semantic_relevance, m.importance_score, m.access_count,
        m.last_accessed_at, m.created_at, m.updated_at, m.archived_at,
        m.tags, m.project, m.content_hash,
        (1 - (m.embedding <=> query_embedding))::float AS score
    FROM memories m
    WHERE m.archived_at IS NULL
      AND m.embedding IS NOT NULL
      AND (p_project IS NULL OR m.project = p_project)
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ============================================================
-- list_projects: DISTINCT project をサーバサイドで取得。
-- ============================================================
CREATE OR REPLACE FUNCTION list_projects()
RETURNS TABLE (project text)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT DISTINCT m.project
    FROM memories m
    WHERE m.project IS NOT NULL AND m.project <> '';
$$;

-- ============================================================
-- increment_memory_access_count: アトミック increment + 時刻更新
-- ============================================================
CREATE OR REPLACE FUNCTION increment_memory_access_count(
    p_memory_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    affected integer;
BEGIN
    UPDATE memories
       SET access_count     = access_count + 1,
           last_accessed_at = NOW(),
           updated_at       = NOW()
     WHERE id = p_memory_id;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected > 0;
END;
$$;

-- 権限付与: RLS 未適用のため service_role のみ
GRANT EXECUTE ON FUNCTION vector_search(vector, integer, text)   TO service_role;
GRANT EXECUTE ON FUNCTION list_projects()                         TO service_role;
GRANT EXECUTE ON FUNCTION increment_memory_access_count(uuid)    TO service_role;
```

- [ ] **Step 3: devcontainer 内で SQL 構文確認**

`service_role` ロールは Supabase 専用のため、ローカル Postgres には存在しない。**SQL 側の存在チェック (PL/pgSQL `DO` ブロック + `pg_roles` 参照)** でロール既存を benign にハンドリングし、migration 本体と合成して **1 回の psql 呼出** に集約する。`ON_ERROR_STOP=on` + シェルの `\|\| true` 不使用で、接続/認証/SQL 構文エラーをすべて確実に検知する:

```bash
{
    cat <<'SQL'
-- service_role はローカル Postgres には存在しないため、SQL レベルで冪等に作成する。
-- 真のエラー (接続失敗・認証失敗・構文エラー等) は ON_ERROR_STOP=on で fail-fast 検知。
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role;
    END IF;
END
$do$;
SQL
    cat supabase/migrations/20260518000002_rpc_functions.sql
} | docker compose exec -T postgres psql -U context_store -d context_store \
        --set=ON_ERROR_STOP=on
```

Expected: 終了コード 0。`Connection refused` / 認証失敗 / 構文エラー / GRANT エラー等が出た場合は原因を特定して修正し再実行する (`\|\| true` で握りつぶさない設計のため、エラーは必ず stderr に表示される)。

- [ ] **Step 4: コミット**

```bash
git add supabase/migrations/20260518000002_rpc_functions.sql
git commit -m "feat(supabase): vector_search / list_projects / increment_memory_access_count RPC を追加"
```

- [ ] **Step 5: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-1-task-1.1-initial-schema \
  --title "feat(supabase): add RPC functions migration" \
  --body "Phase 1 Task 1.2. vector_search / list_projects / increment_memory_access_count RPC + service_role GRANT。Task 1.1 にスタック。"
```

---

## Phase 2: Configuration Layer

**Phase Base ブランチ:** `feat/supabase-adapter/phase-2` ← `master`

`pyproject.toml` への optional dependency 追加と `Settings` への Supabase フィールド追加を行います。**この時点では Prisma 関連設定は残したまま** とし、新旧バックエンド両方を選択可能な状態を保ちます (Phase 5 で Prisma を削除)。

### Task 2.1: pyproject.toml に storage-supabase extra を追加

**派生元:** `master` (Base) — 単体で完結 (新規 optional dependency 追加のみ、既存コードへの影響なし)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/supabase-adapter/phase-2-task-2.1-pyproject
```

- [ ] **Step 2: `[project.optional-dependencies]` に `storage-supabase` を追加し、`all` extras に含める**

`pyproject.toml` の `[project.optional-dependencies]` セクションを以下のように修正します。

Before:

```toml
storage-prisma = [
    "prisma>=0.15.0",
    "sqlparse>=0.5.0",
]
```

After (Prisma extra は残しつつ Supabase を追加):

```toml
storage-prisma = [
    "prisma>=0.15.0",
    "sqlparse>=0.5.0",
]
storage-supabase = [
    "supabase>=2.4.0",
]
```

`all` extras を以下のように更新:

Before:

```toml
all = [
    "context-store-mcp[storage-postgres,storage-prisma,embedding-local,embedding-openai,embedding-litellm,dashboard,evaluator]",
]
```

After:

```toml
all = [
    "context-store-mcp[storage-postgres,storage-prisma,storage-supabase,embedding-local,embedding-openai,embedding-litellm,dashboard,evaluator]",
]
```

- [ ] **Step 3: 依存解決と uv.lock 更新**

devcontainer 内で実行:

```bash
uv sync --extra storage-supabase --extra dashboard --extra embedding-local --dev
```

`uv.lock` が更新されることを確認。

- [ ] **Step 4: 既存テストが回帰していないことを確認**

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

Expected: すべて PASS

- [ ] **Step 5: コミット**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add storage-supabase optional dependency (supabase>=2.4.0)"
```

- [ ] **Step 6: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "build: add storage-supabase optional dependency" \
  --body "Phase 2 Task 2.1. supabase>=2.4.0 を optional extra として追加。Prisma extras は維持。"
```

### Task 2.2: Settings に Supabase フィールドと validator を追加

**派生元:** `master` (Base) — 単体で完結 (新規フィールド追加と既存デフォルト値の調整のみ。後続フェーズで利用されるが、本変更自体は他タスク差分に依存しない)

**Files:**
- Modify: `src/context_store/config.py`
- Modify: `tests/unit/test_config.py` (新規テスト追記)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/supabase-adapter/phase-2-task-2.2-settings
```

- [ ] **Step 2: 失敗テストを先に書く (TDD: Red)**

`tests/unit/test_config.py` の末尾に追記:

```python
import pytest
from pydantic import ValidationError

from context_store.config import SUPABASE_VECTOR_DIMENSION, Settings


def _make_supabase_settings(**overrides):
    base = {
        "storage_backend": "supabase",
        "supabase_url": "https://example.supabase.co",
        "supabase_key": "test-service-role-key",
        "graph_enabled": False,
        "embedding_dimension": SUPABASE_VECTOR_DIMENSION,
    }
    base.update(overrides)
    return Settings(**base)


def test_supabase_constant_is_768():
    assert SUPABASE_VECTOR_DIMENSION == 768


def test_supabase_settings_valid_minimum():
    s = _make_supabase_settings()
    assert s.storage_backend == "supabase"
    assert s.supabase_url == "https://example.supabase.co"
    assert s.supabase_key.get_secret_value() == "test-service-role-key"


def test_supabase_requires_url():
    with pytest.raises(ValidationError, match="SUPABASE_URL"):
        _make_supabase_settings(supabase_url="")


def test_supabase_requires_key():
    with pytest.raises(ValidationError, match="SUPABASE_KEY"):
        _make_supabase_settings(supabase_key="")


def test_supabase_url_must_be_https():
    with pytest.raises(ValidationError, match="https://"):
        _make_supabase_settings(supabase_url="http://example.supabase.co")


def test_supabase_rejects_graph_enabled():
    with pytest.raises(ValidationError, match="graph_enabled=true"):
        _make_supabase_settings(graph_enabled=True)


def test_supabase_rejects_dimension_mismatch():
    with pytest.raises(ValidationError, match="vector\\(768\\)"):
        _make_supabase_settings(embedding_dimension=1024)


def test_default_embedding_dimension_is_768():
    s = Settings(storage_backend="sqlite")
    assert s.embedding_dimension == 768


def test_graph_backend_for_supabase_is_disabled():
    s = _make_supabase_settings()
    assert s.graph_backend == "disabled"
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/test_config.py -k "supabase or default_embedding_dimension or graph_backend_for_supabase" -v
```

Expected: FAIL (`SUPABASE_VECTOR_DIMENSION` が import できない、`storage_backend="supabase"` が Literal 不一致など)

- [ ] **Step 4: `src/context_store/config.py` に Supabase 設定を追加**

`Literal` の更新、定数追加、フィールド追加、validator 追加を一括で行います。Prisma 関連は残置します。

```python
# (ファイル冒頭の import 群の直後あたり)
from typing import Final

SUPABASE_VECTOR_DIMENSION: Final[int] = 768
```

`storage_backend` を更新:

```python
storage_backend: Literal["sqlite", "postgres", "prisma", "supabase"] = "sqlite"
```

`embedding_dimension` のデフォルトを 768 へ:

```python
embedding_dimension: int = Field(default=768, ge=1)
```

Prisma フィールドの直下に Supabase フィールドを追加:

```python
# --- Supabase (storage_backend=supabase の場合) ---
supabase_url: str = Field(
    default="",
    description="Supabase Project URL (例: https://xxxxx.supabase.co)",
)
supabase_key: SecretStr = Field(
    default=SecretStr(""),
    description="Service Role Key または Anon Key",
)
```

`_validate_storage_config` validator に supabase 分岐を追加:

```python
@model_validator(mode="after")
def _validate_storage_config(self) -> "Settings":
    if self.storage_backend == "postgres":
        if not self.postgres_password.get_secret_value().strip():
            raise ValueError("POSTGRES_PASSWORD は storage_backend=postgres の場合に必須です。")
        if self.graph_enabled and not self.neo4j_password.get_secret_value().strip():
            raise ValueError(
                "NEO4J_PASSWORD は storage_backend=postgres かつ "
                "graph_enabled=true の場合に必須です。"
            )
    if self.storage_backend == "prisma":
        url = self.prisma_database_url.get_secret_value().strip()
        if not url:
            raise ValueError("PRISMA_DATABASE_URL は storage_backend=prisma の場合に必須です。")
        self.prisma_database_url = SecretStr(url)
        if not (url.startswith("prisma://") or url.startswith("prismas://")):
            raise ValueError(
                "PRISMA_DATABASE_URL は prisma:// または prismas:// で始まる "
                "Accelerate スキームでなければなりません。"
            )
        if self.graph_enabled:
            raise ValueError(
                "storage_backend=prisma は graph_enabled=true をサポートしません "
                "(Neo4j Bolt は HTTPS にカプセル化できないため)。"
            )
    if self.storage_backend == "supabase":
        if not self.supabase_url.strip():
            raise ValueError("SUPABASE_URL は storage_backend=supabase の場合に必須です。")
        if not self.supabase_key.get_secret_value().strip():
            raise ValueError("SUPABASE_KEY は storage_backend=supabase の場合に必須です。")
        if not self.supabase_url.startswith("https://"):
            raise ValueError("SUPABASE_URL は https:// で始まる必要があります。")
        if self.graph_enabled:
            raise ValueError(
                "storage_backend=supabase は graph_enabled=true をサポートしません "
                "(Neo4j Bolt は HTTPS にカプセル化できないため)。"
            )
        if self.embedding_dimension != SUPABASE_VECTOR_DIMENSION:
            raise ValueError(
                f"EMBEDDING_DIMENSION={self.embedding_dimension} は "
                f"storage_backend=supabase のスキーマ vector({SUPABASE_VECTOR_DIMENSION}) "
                "と一致しません。次元数を変更する場合は "
                "supabase/migrations/ の SQL とこの定数を同時に更新してください。"
            )
    return self
```

`graph_backend` computed_field を更新:

```python
@computed_field  # type: ignore[prop-decorator]
@property
def graph_backend(self) -> str:
    """Derived: 'sqlite' | 'neo4j' | 'disabled'."""
    if not self.graph_enabled:
        return "disabled"
    if self.storage_backend == "sqlite":
        return "sqlite"
    if self.storage_backend == "postgres":
        return "neo4j"
    return "disabled"  # prisma / supabase
```

- [ ] **Step 5: テストがパスすることを確認 (Green)**

```bash
uv run pytest tests/unit/test_config.py -v
uv run mypy src/context_store/config.py
```

Expected: 新規テスト + 既存テストすべて PASS。mypy エラーゼロ。

- [ ] **Step 6: 既存テスト全体の回帰確認**

```bash
uv run pytest tests/unit -v
```

Expected: 既存テストの回帰なし。`embedding_dimension` のデフォルトを 1024 → 768 に変更した影響で `test_embedding_factory.py` 内の明示的に dim を指定したテストはすべて引き続きパスする (既存テストは値を明示しているため)。

- [ ] **Step 7: コミット**

```bash
git add src/context_store/config.py tests/unit/test_config.py
git commit -m "feat(config): Supabase バックエンド用フィールドと validator を追加 (default dim 768)"
```

- [ ] **Step 8: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "feat(config): add Supabase fields, validator, dimension constant" \
  --body "Phase 2 Task 2.2. SUPABASE_VECTOR_DIMENSION 定数 + supabase_url/key フィールド + validator。embedding_dimension デフォルトを 1024→768 へ。Prisma 設定は維持。"
```

---

## Phase 3: Supabase Storage Adapter (TDD)

**Phase Base ブランチ:** `feat/supabase-adapter/phase-3` ← Phase 2 完了後の master

すべてのタスクで `unittest.mock.AsyncMock` を用いて `supabase.AsyncClient` 全体をモックし、HTTP 通信なしでロジック検証を行います。詳細なテスト仕様は設計書 Section 7.1.2 を参照。

### Task 3.1: テストスキャフォールド + アダプタ骨格 + エラーマッピング

**派生元:** Task 2.2 のブランチ — `Settings.supabase_url/key` と `SUPABASE_VECTOR_DIMENSION` 定数に依存するためスタック

**Files:**
- Create: `src/context_store/storage/supabase.py`
- Create: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成 (Task 2.2 上に積み上げ)**

```bash
git checkout feat/supabase-adapter/phase-2-task-2.2-settings
git checkout -b feat/supabase-adapter/phase-3-task-3.1-skeleton
```

- [ ] **Step 2: アダプタ骨格・dispose・エラーマッピングの失敗テストを書く (Red)**

`tests/unit/storage/test_supabase_adapter.py` を新規作成。**モックヘルパはモジュールレベル関数としてファイル先頭に定義**し、conftest 経由の import 解決問題と pytest fixture 注入の煩雑さを同時に回避する:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from context_store.storage.protocols import StorageError
from context_store.storage.supabase import SupabaseStorageAdapter


def make_mock_response(data, count=None):
    resp = MagicMock()
    resp.data = data
    resp.count = count
    return resp


def make_mock_client():
    client = MagicMock()
    client.table = MagicMock()
    client.rpc = MagicMock()
    client.postgrest = AsyncMock()
    return client


@pytest.fixture
def adapter():
    return SupabaseStorageAdapter(make_mock_client())


@pytest.mark.asyncio
async def test_dispose_closes_client(adapter):
    await adapter.dispose()
    adapter._client.postgrest.aclose.assert_awaited_once()


def test_error_mapping_duplicate_23505(adapter):
    exc = type("E", (Exception,), {"code": "23505", "message": "dup"})("dup")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "DUPLICATE_CONTENT"
    assert err.recoverable is False


def test_error_mapping_invalid_input_22P02(adapter):
    exc = type("E", (Exception,), {"code": "22P02", "message": "bad uuid"})("bad uuid")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "INVALID_INPUT"
    assert err.recoverable is False


def test_error_mapping_not_found_PGRST116(adapter):
    exc = type("E", (Exception,), {"code": "PGRST116", "message": "not found"})("not found")
    err = adapter._map_to_storage_error(exc)
    assert err.code == "NOT_FOUND"


def test_error_mapping_timeout_recoverable(adapter):
    err = adapter._map_to_storage_error(httpx.ReadTimeout("504 Gateway Timeout"))
    assert err.code == "STORAGE_TIMEOUT"
    assert err.recoverable is True


def test_error_mapping_payload_too_large_not_recoverable(adapter):
    err = adapter._map_to_storage_error(Exception("413 payload too large"))
    assert err.code == "STORAGE_PAYLOAD_TOO_LARGE"
    assert err.recoverable is False


def test_error_mapping_default_recoverable(adapter):
    err = adapter._map_to_storage_error(Exception("something else"))
    assert err.code == "STORAGE_ERROR"
    assert err.recoverable is True
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
```

Expected: `ImportError: cannot import name 'SupabaseStorageAdapter'` で FAIL

- [ ] **Step 4: `src/context_store/storage/supabase.py` を作成**

ファイル全体を以下の内容で作成 (`save_memory` などの本体メソッドは後続タスクで追加、本タスクでは骨格のみ):

```python
"""Supabase Data API (PostgREST)-backed Storage Adapter.

設計仕様: docs/superpowers/specs/2026-05-18-supabase-storage-adapter-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

try:
    from supabase import AsyncClient, create_async_client  # noqa: F401
    from postgrest.exceptions import APIError as PostgrestAPIError  # noqa: F401

    _supabase_available = True
except ImportError:
    AsyncClient = Any  # type: ignore[misc,assignment]
    PostgrestAPIError = Exception  # type: ignore[misc,assignment]
    _supabase_available = False

from context_store.storage.protocols import StorageError

if TYPE_CHECKING:
    from context_store.config import Settings

logger = logging.getLogger(__name__)

SUPABASE_BATCH_FETCH_CHUNK_SIZE: Final[int] = 200
SUPABASE_MAX_TOP_K: Final[int] = 200


class SupabaseStorageAdapter:
    """StorageAdapter implementation backed by Supabase Data API (HTTPS only)."""

    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: "Settings") -> "SupabaseStorageAdapter":
        # 詳細実装は Task 3.2 で追加
        raise NotImplementedError

    async def dispose(self) -> None:
        client = self._client
        postgrest = getattr(client, "postgrest", None)
        if postgrest is not None and hasattr(postgrest, "aclose"):
            await postgrest.aclose()

    def _map_to_storage_error(self, exc: Exception) -> StorageError:
        code = getattr(exc, "code", None) or ""
        message = getattr(exc, "message", "") or str(exc)

        if code == "23505":
            return StorageError(message, code="DUPLICATE_CONTENT", recoverable=False)
        if code in ("22P02", "22023"):
            return StorageError(message, code="INVALID_INPUT", recoverable=False)
        if code == "PGRST116":
            return StorageError(message, code="NOT_FOUND", recoverable=False)

        exc_str = str(exc).lower()
        if any(kw in exc_str for kw in ("timeout", "408", "504", "503", "connecterror")):
            return StorageError(message, code="STORAGE_TIMEOUT", recoverable=True)
        if "413" in exc_str or "payload too large" in exc_str:
            return StorageError(message, code="STORAGE_PAYLOAD_TOO_LARGE", recoverable=False)

        return StorageError(message, code="STORAGE_ERROR", recoverable=True)
```

- [ ] **Step 5: テストがパスすることを確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
uv run ruff check src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
uv run ruff format --check src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
```

Expected: 7 tests PASS、mypy/ruff エラーゼロ

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): SupabaseStorageAdapter の骨格・dispose・エラーマッピングを追加"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-2-task-2.2-settings \
  --title "feat(storage): scaffold SupabaseStorageAdapter (skeleton + error mapping)" \
  --body "Phase 3 Task 3.1. クラス骨格、dispose()、_map_to_storage_error の全カテゴリ実装。Task 2.2 にスタック。"
```

### Task 3.2: `create()` クラスメソッドと `get_vector_dimension` + dimension fail-fast 検証

**派生元:** Task 3.1 のブランチ — Task 3.1 の骨格に基づく

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.1-skeleton
git checkout -b feat/supabase-adapter/phase-3-task-3.2-create
```

- [ ] **Step 2: 失敗テストを書く (Red)**

`tests/unit/storage/test_supabase_adapter.py` に追記:

既存ファイルの import 群と並ぶ位置に `from unittest.mock import patch` を、ファイル末尾に追加テストを追記。`make_mock_client` / `make_mock_response` はファイル先頭で既に定義済み。

```python
from unittest.mock import AsyncMock, patch

from context_store.config import Settings


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_length():
    client = make_mock_client()
    vec_768 = "[" + ",".join(["0.1"] * 768) + "]"
    chain = (
        client.table.return_value.select.return_value.not_.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_768}]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() == 768


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_none_when_empty():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value.not_.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    assert await adapter.get_vector_dimension() is None


@pytest.mark.asyncio
async def test_create_succeeds_when_table_empty():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value.not_.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
    )
    with patch(
        "context_store.storage.supabase.create_async_client",
        new=AsyncMock(return_value=client),
    ):
        adapter = await SupabaseStorageAdapter.create(settings)
    assert isinstance(adapter, SupabaseStorageAdapter)


@pytest.mark.asyncio
async def test_create_fails_when_dimension_mismatch():
    client = make_mock_client()
    vec_1024 = "[" + ",".join(["0.1"] * 1024) + "]"
    chain = (
        client.table.return_value.select.return_value.not_.return_value
        .is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"embedding": vec_1024}]))

    settings = Settings(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
    )
    with patch(
        "context_store.storage.supabase.create_async_client",
        new=AsyncMock(return_value=client),
    ):
        with pytest.raises(StorageError) as exc_info:
            await SupabaseStorageAdapter.create(settings)
    assert exc_info.value.code == "INVALID_STATE"
    assert "768" in str(exc_info.value) and "1024" in str(exc_info.value)
    client.postgrest.aclose.assert_awaited()
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -k "vector_dimension or create" -v
```

Expected: `NotImplementedError` で FAIL

- [ ] **Step 4: `supabase.py` に `create()` と `get_vector_dimension` を実装**

`SupabaseStorageAdapter` クラスに以下を追加 (既存の `create` の `NotImplementedError` を置換):

```python
from context_store.storage.postgres_helpers import _parse_embedding

# ... 既存 import 群に追加 ...

# クラス内メソッド:

async def get_vector_dimension(self) -> int | None:
    chain = (
        self._client.table("memories")
        .select("embedding")
        .not_.is_("embedding", "null")
        .limit(1)
    )
    response = await chain.execute()
    rows = response.data or []
    if not rows:
        return None
    embedding = _parse_embedding(rows[0].get("embedding"))
    return len(embedding) if embedding else None

@classmethod
async def create(cls, settings: "Settings") -> "SupabaseStorageAdapter":
    if not _supabase_available:
        raise ImportError(
            "supabase is not installed. Install with: "
            "uv sync --extra storage-supabase"
        )
    client = await create_async_client(
        settings.supabase_url,
        settings.supabase_key.get_secret_value(),
    )
    adapter = cls(client)
    try:
        actual_dim = await adapter.get_vector_dimension()
    except Exception as exc:
        await adapter.dispose()
        raise adapter._map_to_storage_error(exc) from exc

    if actual_dim is not None and actual_dim != settings.embedding_dimension:
        await adapter.dispose()
        raise StorageError(
            f"Supabase memories.embedding dimension ({actual_dim}) does not match "
            f"settings.embedding_dimension ({settings.embedding_dimension}). "
            "Apply the matching supabase/migrations SQL or reconcile EMBEDDING_DIMENSION.",
            code="INVALID_STATE",
            recoverable=False,
        )
    return adapter
```

- [ ] **Step 5: テストがパスすることを確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
```

Expected: すべて PASS。mypy エラーゼロ。

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): SupabaseStorageAdapter.create() + dimension fail-fast probe"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.1-skeleton \
  --title "feat(storage): add create() + dimension probe" \
  --body "Phase 3 Task 3.2. AsyncClient 生成、起動時 dimension 検証、失敗時 fail-fast。Task 3.1 にスタック。"
```

### Task 3.3: CRUD writes (`save_memory`, `update_memory`)

**派生元:** Task 3.2 のブランチ

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.2-create
git checkout -b feat/supabase-adapter/phase-3-task-3.3-writes
```

- [ ] **Step 2: 失敗テストを書く (Red)**

設計書 Section 7.1.2 の `test_save_memory_inserts_with_content_hash`, `test_save_memory_raises_duplicate_on_23505`, `test_update_memory_recomputes_content_hash`, `test_update_memory_rejects_disallowed_columns` を `tests/unit/storage/test_supabase_adapter.py` に実装。代表として save と update をフルコードで記載:

```python
import hashlib

from context_store.models.memory import Memory, MemoryType, SourceType


def _sample_memory(content: str = "hello world", embedding=None) -> Memory:
    return Memory(
        content=content,
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        embedding=embedding or [0.1] * 768,
    )


@pytest.mark.asyncio
async def test_save_memory_inserts_with_content_hash():
    client = make_mock_client()
    inserted_id = "550e8400-e29b-41d4-a716-446655440000"
    client.table.return_value.insert.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[{"id": inserted_id}])
    )

    adapter = SupabaseStorageAdapter(client)
    mem = _sample_memory("hello world")
    result = await adapter.save_memory(mem)

    assert result == inserted_id
    insert_args = client.table.return_value.insert.call_args[0][0]
    assert insert_args["content_hash"] == hashlib.sha256(b"hello world").hexdigest()
    assert insert_args["content"] == "hello world"
    assert insert_args["embedding"] == "[" + ",".join(str(v) for v in [0.1] * 768) + "]"


@pytest.mark.asyncio
async def test_save_memory_raises_duplicate_on_23505():
    client = make_mock_client()
    err = type("E", (Exception,), {"code": "23505", "message": "duplicate key value"})("dup")
    client.table.return_value.insert.return_value.execute = AsyncMock(side_effect=err)

    adapter = SupabaseStorageAdapter(client)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(_sample_memory())
    assert exc_info.value.code == "DUPLICATE_CONTENT"
    assert exc_info.value.recoverable is False


@pytest.mark.asyncio
async def test_update_memory_recomputes_content_hash():
    client = make_mock_client()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"id": "x"}]))

    adapter = SupabaseStorageAdapter(client)
    ok = await adapter.update_memory(
        "550e8400-e29b-41d4-a716-446655440000",
        {"content": "new content"},
    )
    assert ok is True
    update_args = client.table.return_value.update.call_args[0][0]
    assert update_args["content"] == "new content"
    assert update_args["content_hash"] == hashlib.sha256(b"new content").hexdigest()


@pytest.mark.asyncio
async def test_update_memory_rejects_disallowed_columns():
    client = make_mock_client()
    chain = client.table.return_value.update.return_value.eq.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[{"id": "x"}]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.update_memory(
        "550e8400-e29b-41d4-a716-446655440000",
        {"id": "999", "secret_field": "x", "content": "ok"},
    )
    update_args = client.table.return_value.update.call_args[0][0]
    assert set(update_args.keys()) == {"content", "content_hash"}
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -k "save_memory or update_memory" -v
```

Expected: `AttributeError: ... has no attribute 'save_memory'` で FAIL

- [ ] **Step 4: `supabase.py` に `save_memory` と `update_memory` を実装**

クラス内にメソッドを追加:

```python
from typing import cast

from context_store.storage.postgres_helpers import _content_hash, _embedding_to_pg

ALLOWED_UPDATE_COLUMNS: Final[frozenset[str]] = frozenset({
    "content",
    "memory_type",
    "source_type",
    "source_metadata",
    "embedding",
    "semantic_relevance",
    "importance_score",
    "tags",
    "project",
    "archived_at",
})

async def save_memory(self, memory: "Memory") -> str:
    row = {
        "content": memory.content,
        "memory_type": memory.memory_type.value,
        "source_type": memory.source_type.value,
        "source_metadata": memory.source_metadata or {},
        "embedding": _embedding_to_pg(memory.embedding or []),
        "semantic_relevance": memory.semantic_relevance,
        "importance_score": memory.importance_score,
        "tags": list(memory.tags or []),
        "project": memory.project,
        "content_hash": _content_hash(memory.content),
    }
    try:
        response = await self._client.table("memories").insert(row).execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    rows = response.data or []
    if not rows:
        raise StorageError("Insert returned no rows", code="STORAGE_ERROR", recoverable=True)
    return cast(str, rows[0]["id"])


async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
    filtered = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_COLUMNS}
    if "content" in filtered:
        filtered["content_hash"] = _content_hash(filtered["content"])
    if "embedding" in filtered and not isinstance(filtered["embedding"], str):
        filtered["embedding"] = _embedding_to_pg(filtered["embedding"] or [])
    if not filtered:
        return False
    try:
        response = (
            await self._client.table("memories")
            .update(filtered)
            .eq("id", memory_id)
            .execute()
        )
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return bool(response.data)
```

- [ ] **Step 5: テストパス確認 + lint/型 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
uv run ruff check src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
```

Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): save_memory + update_memory (whitelist + hash recompute)"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.2-create \
  --title "feat(storage): save_memory + update_memory" \
  --body "Phase 3 Task 3.3. INSERT/UPDATE with content_hash recompute & column whitelist。"
```

### Task 3.4: CRUD reads/deletes (`get_memory`, `get_memories_batch`, `delete_memory`)

**派生元:** Task 3.3 のブランチ

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.3-writes
git checkout -b feat/supabase-adapter/phase-3-task-3.4-reads
```

- [ ] **Step 2: 失敗テストを書く (Red)**

`test_get_memory_returns_none_when_not_found`, `test_get_memory_invalid_uuid_returns_none`, `test_get_memories_batch_preserves_input_order`, `test_get_memories_batch_chunks_at_200`, `test_get_memories_batch_skips_invalid_uuid`, `test_delete_memory_returns_false_when_not_found` を設計書 Section 7.1.2 の仕様通りに追加。代表例として 2 つフルコード:

```python
import json
from datetime import datetime, timezone


def _mock_row(memory_id: str, content: str = "x") -> dict:
    return {
        "id": memory_id,
        "content": content,
        "memory_type": "semantic",
        "source_type": "manual",
        "source_metadata": {},
        "embedding": "[" + ",".join(["0.1"] * 768) + "]",
        "semantic_relevance": 0.5,
        "importance_score": 0.5,
        "access_count": 0,
        "last_accessed_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "archived_at": None,
        "tags": [],
        "project": None,
        "content_hash": "h",
    }


@pytest.mark.asyncio
async def test_get_memory_returns_none_when_not_found():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value.eq.return_value
        .maybe_single.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=None))

    adapter = SupabaseStorageAdapter(client)
    result = await adapter.get_memory("550e8400-e29b-41d4-a716-446655440000")
    assert result is None


@pytest.mark.asyncio
async def test_get_memory_invalid_uuid_returns_none():
    client = make_mock_client()
    adapter = SupabaseStorageAdapter(client)
    result = await adapter.get_memory("not-a-uuid")
    assert result is None
    client.table.assert_not_called()


@pytest.mark.asyncio
async def test_get_memories_batch_preserves_input_order():
    client = make_mock_client()
    id1 = "11111111-1111-1111-1111-111111111111"
    id2 = "22222222-2222-2222-2222-222222222222"
    id3 = "33333333-3333-3333-3333-333333333333"

    rows = [_mock_row(id1, "c1"), _mock_row(id2, "c2"), _mock_row(id3, "c3")]
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=rows))

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.get_memories_batch([id3, id1, id2])
    assert [str(m.id) for m in results] == [id3, id1, id2]


@pytest.mark.asyncio
async def test_get_memories_batch_chunks_at_200():
    client = make_mock_client()
    ids = [f"{i:08d}-0000-0000-0000-000000000000" for i in range(250)]
    chain = client.table.return_value.select.return_value.in_.return_value
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.get_memories_batch(ids)
    assert client.table.return_value.select.return_value.in_.call_count == 2


@pytest.mark.asyncio
async def test_delete_memory_returns_false_when_not_found():
    client = make_mock_client()
    chain = (
        client.table.return_value.delete.return_value.eq.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    result = await adapter.delete_memory("550e8400-e29b-41d4-a716-446655440000")
    assert result is False
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -k "get_memory or get_memories_batch or delete_memory" -v
```

Expected: AttributeError 系で FAIL

- [ ] **Step 4: `supabase.py` に `get_memory`, `get_memories_batch`, `delete_memory` を実装**

```python
from uuid import UUID
from context_store.storage.postgres_helpers import _record_to_memory

def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def get_memory(self, memory_id: str) -> "Memory | None":
    if not _is_valid_uuid(memory_id):
        return None
    try:
        response = (
            await self._client.table("memories")
            .select("*")
            .eq("id", memory_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    if not response.data:
        return None
    return _record_to_memory(response.data)


async def get_memories_batch(self, memory_ids: list[str]) -> list["Memory"]:
    valid_ids = [mid for mid in memory_ids if _is_valid_uuid(mid)]
    if not valid_ids:
        return []
    by_id: dict[str, "Memory"] = {}
    for i in range(0, len(valid_ids), SUPABASE_BATCH_FETCH_CHUNK_SIZE):
        chunk = valid_ids[i : i + SUPABASE_BATCH_FETCH_CHUNK_SIZE]
        try:
            response = (
                await self._client.table("memories")
                .select("*")
                .in_("id", chunk)
                .execute()
            )
        except Exception as exc:
            raise self._map_to_storage_error(exc) from exc
        for row in response.data or []:
            memory = _record_to_memory(row)
            by_id[str(memory.id)] = memory
    return [by_id[mid] for mid in valid_ids if mid in by_id]


async def delete_memory(self, memory_id: str) -> bool:
    if not _is_valid_uuid(memory_id):
        return False
    try:
        response = (
            await self._client.table("memories")
            .delete(returning="representation")
            .eq("id", memory_id)
            .execute()
        )
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return bool(response.data)
```

- [ ] **Step 5: テストパス確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
uv run ruff check src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
```

Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): get_memory / get_memories_batch (順序保持・200件チャンク) / delete_memory"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.3-writes \
  --title "feat(storage): get/batch/delete operations" \
  --body "Phase 3 Task 3.4. UUID 検証、200 件チャンク、入力順保持。"
```

### Task 3.5: Search (`vector_search`, `keyword_search`)

**派生元:** Task 3.4 のブランチ

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.4-reads
git checkout -b feat/supabase-adapter/phase-3-task-3.5-search
```

- [ ] **Step 2: 失敗テストを書く (Red)**

設計書 Section 7.1.2 の `test_vector_search_invokes_rpc`, `test_vector_search_clamps_top_k`, `test_keyword_search_uses_ilike`, `test_keyword_search_does_not_escape_like_wildcards` を追加。代表例:

```python
import logging
from context_store.models.memory import MemorySource


@pytest.mark.asyncio
async def test_vector_search_invokes_rpc():
    client = make_mock_client()
    row = _mock_row("550e8400-e29b-41d4-a716-446655440000", "hit")
    row["score"] = 0.95
    client.rpc.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[row])
    )

    adapter = SupabaseStorageAdapter(client)
    results = await adapter.vector_search([0.1] * 768, top_k=10, project=None)

    client.rpc.assert_called_once_with(
        "vector_search",
        {"query_embedding": [0.1] * 768, "match_count": 10, "p_project": None},
    )
    assert len(results) == 1
    assert results[0].score == 0.95
    assert results[0].source == MemorySource.VECTOR


@pytest.mark.asyncio
async def test_vector_search_clamps_top_k(caplog):
    client = make_mock_client()
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=[]))
    adapter = SupabaseStorageAdapter(client)
    with caplog.at_level(logging.WARNING, logger="context_store.storage.supabase"):
        await adapter.vector_search([0.1] * 768, top_k=300, project=None)
    call_args = client.rpc.call_args[0]
    assert call_args[1]["match_count"] == 200
    assert any("top_k" in rec.message.lower() or "clamp" in rec.message.lower() for rec in caplog.records)


@pytest.mark.asyncio
async def test_keyword_search_uses_ilike():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value
        .ilike.return_value.is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.keyword_search("hello", top_k=5, project=None)

    client.table.return_value.select.return_value.ilike.assert_called_once_with(
        "content", "%hello%"
    )
    chain_obj = client.table.return_value.select.return_value.ilike.return_value
    chain_obj.is_.assert_called_once_with("archived_at", "null")
    chain_obj.is_.return_value.limit.assert_called_once_with(5)


@pytest.mark.asyncio
async def test_keyword_search_does_not_escape_like_wildcards():
    client = make_mock_client()
    chain = (
        client.table.return_value.select.return_value
        .ilike.return_value.is_.return_value.limit.return_value
    )
    chain.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.keyword_search("%hack_", top_k=5, project=None)

    client.table.return_value.select.return_value.ilike.assert_called_once_with(
        "content", "%%hack_%"
    )
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -k "search" -v
```

Expected: AttributeError 系で FAIL

- [ ] **Step 4: `supabase.py` に検索を実装**

```python
from context_store.models.memory import MemorySource, ScoredMemory


async def vector_search(
    self,
    embedding: list[float],
    top_k: int,
    project: str | None = None,
) -> list["ScoredMemory"]:
    effective_top_k = top_k
    if top_k > SUPABASE_MAX_TOP_K:
        logger.warning(
            "top_k=%d exceeds SUPABASE_MAX_TOP_K=%d; clamping",
            top_k,
            SUPABASE_MAX_TOP_K,
        )
        effective_top_k = SUPABASE_MAX_TOP_K

    params = {
        "query_embedding": embedding,
        "match_count": effective_top_k,
        "p_project": project,
    }
    try:
        response = await self._client.rpc("vector_search", params).execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc

    results: list[ScoredMemory] = []
    for row in response.data or []:
        score = float(row.pop("score", 0.0))
        memory = _record_to_memory(row)
        results.append(ScoredMemory(memory=memory, score=score, source=MemorySource.VECTOR))
    return results


async def keyword_search(
    self,
    query: str,
    top_k: int,
    project: str | None = None,
) -> list["ScoredMemory"]:
    effective_top_k = min(top_k, SUPABASE_MAX_TOP_K)
    builder = (
        self._client.table("memories")
        .select("*")
        .ilike("content", f"%{query}%")
        .is_("archived_at", "null")
        .limit(effective_top_k)
    )
    if project is not None:
        builder = builder.eq("project", project)
    try:
        response = await builder.execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc

    results: list[ScoredMemory] = []
    for row in response.data or []:
        memory = _record_to_memory(row)
        results.append(ScoredMemory(memory=memory, score=1.0, source=MemorySource.KEYWORD))
    return results
```

- [ ] **Step 5: テストパス確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
uv run ruff check src/context_store/storage/supabase.py
```

Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): vector_search (RPC + top_k clamp) + keyword_search (ilike, no escape)"
```

- [ ] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.4-reads \
  --title "feat(storage): vector & keyword search" \
  --body "Phase 3 Task 3.5. RPC ベース vector_search + clamp、PostgREST ilike keyword_search。"
```

### Task 3.6: Filter/Count/List/Increment (`list_by_filter`, `count_by_filter`, `list_projects`, `increment_memory_access_count`)

**派生元:** Task 3.5 のブランチ

**Files:**
- Modify: `src/context_store/storage/supabase.py`
- Modify: `tests/unit/storage/test_supabase_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.5-search
git checkout -b feat/supabase-adapter/phase-3-task-3.6-filter-list
```

- [ ] **Step 2: 失敗テストを書く (Red)**

設計書 Section 7.1.2 の `test_list_by_filter_cursor_pagination`, `test_count_by_filter_uses_head_true`, `test_list_projects_invokes_rpc`, `test_increment_access_count_invokes_rpc`, `test_list_by_filter_archived_logic` を追加。さらに **本タスクで対応するレビュー指摘** に対する以下の回帰テストも追加する:

- `test_format_pg_datetime_preserves_microseconds_and_tz`: `_format_pg_datetime` の出力に μs と `+00:00` が含まれることを assert
- `test_list_by_filter_cursor_keeps_microseconds`: `or_()` に渡される文字列に μs が含まれることを assert
- `test_archived_after_auto_coerces_to_archived_true`: `archived=None` + `archived_after` 指定時に `not_.is_("archived_at","null")` が呼ばれることを assert
- `test_archived_false_returns_both`: `archived=False` の場合 `is_("archived_at",...)` が呼ばれないことを assert

代表例:

```python
from datetime import datetime, timezone

from context_store.storage.protocols import MemoryFilters


@pytest.mark.asyncio
async def test_count_by_filter_uses_head_true():
    client = make_mock_client()
    builder = client.table.return_value.select.return_value
    builder.execute = AsyncMock(return_value=make_mock_response(data=[], count=42))

    adapter = SupabaseStorageAdapter(client)
    count = await adapter.count_by_filter(MemoryFilters())

    client.table.return_value.select.assert_called_with("*", count="exact", head=True)
    assert count == 42


@pytest.mark.asyncio
async def test_list_projects_invokes_rpc():
    client = make_mock_client()
    client.rpc.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[{"project": "a"}, {"project": "b"}])
    )

    adapter = SupabaseStorageAdapter(client)
    projects = await adapter.list_projects()
    client.rpc.assert_called_once_with("list_projects", {})
    assert projects == ["a", "b"]


@pytest.mark.asyncio
async def test_increment_access_count_invokes_rpc():
    client = make_mock_client()
    client.rpc.return_value.execute = AsyncMock(return_value=make_mock_response(data=True))

    adapter = SupabaseStorageAdapter(client)
    memory_id = "550e8400-e29b-41d4-a716-446655440000"
    ok = await adapter.increment_memory_access_count(memory_id)
    client.rpc.assert_called_once_with(
        "increment_memory_access_count",
        {"p_memory_id": memory_id},
    )
    assert ok is True


@pytest.mark.asyncio
async def test_list_by_filter_cursor_pagination():
    client = make_mock_client()
    builder = client.table.return_value.select.return_value
    builder.or_.return_value.order.return_value.limit.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[])
    )

    adapter = SupabaseStorageAdapter(client)
    cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
    await adapter.list_by_filter(
        MemoryFilters(
            created_after=cutoff,
            id_after="550e8400-e29b-41d4-a716-446655440000",
            order_by="created_at DESC",
            limit=20,
        )
    )

    or_arg = builder.or_.call_args[0][0]
    assert "created_at.lt." in or_arg
    assert "and(created_at.eq." in or_arg
    assert "id.lt.550e8400-e29b-41d4-a716-446655440000" in or_arg


def test_format_pg_datetime_preserves_microseconds_and_tz():
    from context_store.storage.supabase import _format_pg_datetime

    dt = datetime(2026, 5, 18, 12, 34, 56, 123456, tzinfo=timezone.utc)
    result = _format_pg_datetime(dt)
    assert "123456" in result, f"μs が欠落: {result!r}"
    assert result.endswith("+00:00"), f"TZ 情報が欠落: {result!r}"


@pytest.mark.asyncio
async def test_list_by_filter_cursor_keeps_microseconds():
    client = make_mock_client()
    builder = client.table.return_value.select.return_value
    builder.or_.return_value.order.return_value.limit.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[])
    )

    adapter = SupabaseStorageAdapter(client)
    cutoff = datetime(2026, 5, 1, 0, 0, 0, 654321, tzinfo=timezone.utc)
    await adapter.list_by_filter(
        MemoryFilters(
            created_after=cutoff,
            id_after="550e8400-e29b-41d4-a716-446655440000",
            order_by="created_at DESC",
            limit=20,
        )
    )

    or_arg = builder.or_.call_args[0][0]
    assert "654321" in or_arg, f"μs が cursor から欠落: {or_arg!r}"


@pytest.mark.asyncio
async def test_archived_after_auto_coerces_to_archived_true():
    """archived_after 指定時は archived=None でも archived only にコアース"""
    client = make_mock_client()
    builder = client.table.return_value.select.return_value
    builder.not_.is_.return_value.gte.return_value.execute = AsyncMock(
        return_value=make_mock_response(data=[])
    )

    adapter = SupabaseStorageAdapter(client)
    await adapter.list_by_filter(
        MemoryFilters(archived_after=datetime(2026, 1, 1, tzinfo=timezone.utc))
    )

    # archived=None のままだと is_("archived_at", "null") が呼ばれてしまうので、
    # not_.is_(...) (= archived only) が呼ばれることを確認
    builder.not_.is_.assert_called_with("archived_at", "null")
    # archived_at IS NULL の追加呼出は発生していない
    builder.is_.assert_not_called()


@pytest.mark.asyncio
async def test_archived_false_returns_both():
    """archived=False は active/archived 両方返す (フィルタを足さない)"""
    client = make_mock_client()
    builder = client.table.return_value.select.return_value
    builder.execute = AsyncMock(return_value=make_mock_response(data=[]))

    adapter = SupabaseStorageAdapter(client)
    await adapter.list_by_filter(MemoryFilters(archived=False))

    builder.is_.assert_not_called()
    builder.not_.is_.assert_not_called()
```

- [ ] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -k "filter or count or list_projects or increment_access" -v
```

Expected: AttributeError 系で FAIL

- [ ] **Step 4: `supabase.py` にロジックを実装**

```python
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters


def _format_pg_datetime(dt: datetime) -> str:
    # isoformat(timespec="microseconds") で μs + TZ オフセット (+00:00) を残す。
    # 秒精度に丸めると cursor pagination の (created_at.eq.X) 比較が
    # PostgreSQL TIMESTAMPTZ (μs 精度) と一致せず、ページ間で行の重複/欠落を起こす。
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _apply_common_filters(builder, filters: MemoryFilters):
    if filters.project is not None:
        builder = builder.eq("project", filters.project)
    if filters.memory_type is not None:
        builder = builder.eq("memory_type", filters.memory_type)
    if filters.session_id is not None:
        builder = builder.eq("source_metadata->>session_id", filters.session_id)
    if filters.min_importance is not None:
        builder = builder.gte("importance_score", filters.min_importance)
    if filters.tags:
        builder = builder.contains("tags", filters.tags)

    # Protocol セマンティクス (protocols.py:28):
    #   archived = None  → active only   (archived_at IS NULL)
    #   archived = True  → archived only (archived_at IS NOT NULL)
    #   archived = False → 両方 (フィルタ無し)
    # archived_after が指定された場合、デフォルトの archived=None と矛盾するため
    # 自動で archived=True にコアースしてアーカイブ済みのみ返す挙動とする。
    effective_archived = filters.archived
    if filters.archived_after is not None and effective_archived is None:
        effective_archived = True

    if effective_archived is None:
        builder = builder.is_("archived_at", "null")
    elif effective_archived is True:
        builder = builder.not_.is_("archived_at", "null")
    # effective_archived is False の場合は何も追加しない (両方返す意図)

    if filters.archived_after is not None:
        builder = builder.gte("archived_at", _format_pg_datetime(filters.archived_after))
    return builder


async def list_by_filter(self, filters: "MemoryFilters") -> list["Memory"]:
    builder = self._client.table("memories").select("*")
    builder = _apply_common_filters(builder, filters)

    if filters.created_after is not None and filters.id_after is not None:
        ts = _format_pg_datetime(filters.created_after)
        builder = builder.or_(
            f"created_at.lt.{ts},and(created_at.eq.{ts},id.lt.{filters.id_after})"
        )
    elif filters.created_after is not None:
        builder = builder.lt("created_at", _format_pg_datetime(filters.created_after))

    if filters.order_by:
        column, _, direction = filters.order_by.partition(" ")
        if column in ALLOWED_SORT_COLUMNS:
            desc = direction.upper() == "DESC"
            builder = builder.order(column, desc=desc)
    if filters.limit is not None:
        builder = builder.limit(filters.limit)
    if filters.offset is not None:
        builder = builder.offset(filters.offset)

    try:
        response = await builder.execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return [_record_to_memory(row) for row in response.data or []]


async def count_by_filter(self, filters: "MemoryFilters") -> int:
    builder = self._client.table("memories").select("*", count="exact", head=True)
    builder = _apply_common_filters(builder, filters)
    try:
        response = await builder.execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return int(response.count or 0)


async def list_projects(self) -> list[str]:
    try:
        response = await self._client.rpc("list_projects", {}).execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return [row["project"] for row in response.data or [] if row.get("project")]


async def increment_memory_access_count(self, memory_id: str) -> bool:
    if not _is_valid_uuid(memory_id):
        return False
    try:
        response = await self._client.rpc(
            "increment_memory_access_count", {"p_memory_id": memory_id}
        ).execute()
    except Exception as exc:
        raise self._map_to_storage_error(exc) from exc
    return bool(response.data)
```

- [ ] **Step 5: テストパス確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_supabase_adapter.py -v
uv run mypy src/context_store/storage/supabase.py
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: 全テスト PASS、mypy エラーゼロ

- [ ] **Step 6: シークレット非露出テストを追加 (設計書 Section 7.1.2)**

```python
@pytest.mark.asyncio
async def test_no_secret_in_exception_message():
    client = make_mock_client()
    secret = "super-secret-jwt-token"
    client.table.return_value.insert.return_value.execute = AsyncMock(
        side_effect=Exception("auth failed but not leaking key")
    )

    adapter = SupabaseStorageAdapter(client)
    try:
        await adapter.save_memory(_sample_memory())
    except StorageError as exc:
        assert secret not in str(exc)
        assert secret not in repr(exc)
```

`uv run pytest tests/unit/storage/test_supabase_adapter.py -v` で全件通ることを再確認。

- [ ] **Step 7: コミット**

```bash
git add src/context_store/storage/supabase.py tests/unit/storage/test_supabase_adapter.py
git commit -m "feat(storage): list/count/projects + increment_access RPC, シークレット非露出を保証"
```

- [ ] **Step 8: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.5-search \
  --title "feat(storage): filter/count/list_projects/increment" \
  --body "Phase 3 Task 3.6. PostgREST フィルタチェーン、cursor pagination、count head=True、サーバサイド DISTINCT、原子的 increment。シークレット非露出テスト含む。"
```

---

## Phase 4: Factory Integration

**Phase Base ブランチ:** `feat/supabase-adapter/phase-4` ← Phase 3 完了後の master

### Task 4.1: Factory に supabase 分岐を追加

**派生元:** Task 3.6 のブランチ — 完成した `SupabaseStorageAdapter` への参照を追加するためスタック

**Files:**
- Modify: `src/context_store/storage/factory.py`
- Create: `tests/unit/storage/test_factory_supabase.py`

- [x] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-3-task-3.6-filter-list
git checkout -b feat/supabase-adapter/phase-4-task-4.1-factory
```

- [x] **Step 2: 失敗テストを書く (Red)**

`tests/unit/storage/test_factory_supabase.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_store.config import Settings
from context_store.storage.factory import _create_graph_adapter, _create_storage_adapter
from context_store.storage.supabase import SupabaseStorageAdapter


def _make_settings(**overrides) -> Settings:
    base = dict(
        storage_backend="supabase",
        supabase_url="https://x.supabase.co",
        supabase_key="k",
        embedding_dimension=768,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_factory_creates_supabase_adapter():
    settings = _make_settings()
    fake_adapter = SupabaseStorageAdapter(client=object())  # type: ignore[arg-type]
    with patch(
        "context_store.storage.supabase.SupabaseStorageAdapter.create",
        new=AsyncMock(return_value=fake_adapter),
    ):
        adapter = await _create_storage_adapter(settings, read_only=False)
    assert adapter is fake_adapter


@pytest.mark.asyncio
async def test_factory_supabase_read_only_raises():
    settings = _make_settings()
    with pytest.raises(NotImplementedError):
        await _create_storage_adapter(settings, read_only=True)


@pytest.mark.asyncio
async def test_factory_graph_disabled_for_supabase():
    settings = _make_settings(graph_enabled=False)
    graph = await _create_graph_adapter(settings, read_only=False)
    assert graph is None
```

- [x] **Step 3: 失敗を確認 (Red)**

```bash
uv run pytest tests/unit/storage/test_factory_supabase.py -v
```

Expected: `ValueError: Unsupported storage_backend: 'supabase'` で FAIL

- [x] **Step 4: `factory.py` に supabase 分岐を追加 (Prisma 分岐は維持)**

`_create_storage_adapter` に追加:

```python
if settings.storage_backend == "supabase":
    from context_store.storage.supabase import SupabaseStorageAdapter

    if read_only:
        raise NotImplementedError(
            "read_only mode for supabase backend is not yet supported"
        )
    return await SupabaseStorageAdapter.create(settings)
```

`_create_graph_adapter` の Prisma 分岐の直後に追加:

```python
if settings.storage_backend == "supabase":
    raise ValueError(
        "Graph adapter is not supported for storage_backend=supabase "
        "(Neo4j Bolt cannot be tunneled over HTTPS)"
    )
```

ただし `graph_enabled=False` の場合は冒頭で None が返るため到達しない。

ファイル冒頭の docstring `Routing logic` セクションも更新:

```python
"""...
- STORAGE_BACKEND=sqlite    → SQLiteStorageAdapter
- STORAGE_BACKEND=postgres  → PostgresStorageAdapter
- STORAGE_BACKEND=prisma    → PrismaStorageAdapter (Phase 5 で削除予定)
- STORAGE_BACKEND=supabase  → SupabaseStorageAdapter
..."""
```

- [x] **Step 5: テストパス確認 (Green)**

```bash
uv run pytest tests/unit/storage/test_factory_supabase.py -v
uv run pytest tests/unit -v
uv run mypy src/context_store/storage/factory.py
uv run ruff check src/ tests/
```

Expected: すべて PASS

- [x] **Step 6: コミット**

```bash
git add src/context_store/storage/factory.py tests/unit/storage/test_factory_supabase.py
git commit -m "feat(factory): Supabase backend 分岐を追加 (Prisma 分岐は維持)"
```

- [x] **Step 7: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-3-task-3.6-filter-list \
  --title "feat(factory): wire SupabaseStorageAdapter" \
  --body "Phase 4 Task 4.1. factory._create_storage_adapter に supabase 分岐追加、グラフ非対応化、read_only NotImplementedError。Prisma 分岐は Phase 5 まで残置。"
```

---

## Phase 5: Prisma Removal

**Phase Base ブランチ:** `feat/supabase-adapter/phase-5` ← Phase 4 完了後の master

Phase 4 までで Supabase バックエンドが完全動作することを確認したうえで、Prisma 関連コード・テスト・依存・CI ステップを clean break で削除します。

### Task 5.1: Prisma コード本体・テスト・config 設定の削除

**派生元:** Task 4.1 のブランチ — factory が Supabase 分岐を持つ状態でないと、Prisma 削除後にバックエンド選択肢が postgres/sqlite のみになり、本タスクで実装する移行先がなくなる

**Files:**
- Delete: `src/context_store/storage/prisma.py`
- Delete: `prisma/schema.prisma` および `prisma/` ディレクトリ
- Delete: `tests/unit/storage/test_prisma_adapter.py`
- Delete: `tests/unit/storage/test_prisma_pagination.py`
- Delete: `tests/integration/test_orchestrator_prisma.py`
- Modify: `src/context_store/config.py`
- Modify: `src/context_store/storage/factory.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-4-task-4.1-factory
git checkout -b feat/supabase-adapter/phase-5-task-5.1-remove-prisma-code
```

- [ ] **Step 2: Prisma 専用テストを先に削除**

```bash
git rm tests/unit/storage/test_prisma_adapter.py \
       tests/unit/storage/test_prisma_pagination.py \
       tests/integration/test_orchestrator_prisma.py
```

- [ ] **Step 3: アダプタ本体・Prisma スキーマを削除**

```bash
git rm src/context_store/storage/prisma.py
git rm -r prisma/
```

- [ ] **Step 4: `config.py` から Prisma 関連を削除**

`storage_backend` の Literal から `"prisma"` を除く:

```python
storage_backend: Literal["sqlite", "postgres", "supabase"] = "sqlite"
```

`prisma_database_url` フィールドを削除。`_validate_storage_config` validator から `if self.storage_backend == "prisma":` ブロック全体を削除。

- [ ] **Step 5: `factory.py` から Prisma 分岐を削除**

`_create_storage_adapter` の `if settings.storage_backend == "prisma":` ブロック全体を削除。`_create_graph_adapter` の `if settings.storage_backend == "prisma":` ブロックも削除 (Supabase 分岐が同等のメッセージで存在する)。

ファイル冒頭の docstring も更新:

```python
"""...
- STORAGE_BACKEND=sqlite   → SQLiteStorageAdapter
- STORAGE_BACKEND=postgres → PostgresStorageAdapter
- STORAGE_BACKEND=supabase → SupabaseStorageAdapter
..."""
```

- [ ] **Step 6: テストで回帰がないことを確認**

```bash
uv run pytest tests/unit -v
uv run mypy src/
uv run ruff check src/ tests/
```

Expected: すべて PASS。`tests/unit/test_config.py` 内の Prisma 関連テストも併せて削除済みの想定 (該当があれば本ステップ内で削除)。

`tests/unit/test_config.py` で Prisma に言及するテストを `grep -n "prisma" tests/unit/test_config.py` で確認し、存在すれば削除:

```bash
grep -n "prisma" tests/unit/test_config.py || true
```

該当行があれば該当テスト関数全体を削除してから再テスト。

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "refactor: Prisma バックエンドの全コード・テスト・スキーマを削除"
```

- [ ] **Step 8: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-4-task-4.1-factory \
  --title "refactor: remove Prisma adapter & related code" \
  --body "Phase 5 Task 5.1. prisma.py / prisma/ / 専用テスト削除、config と factory から Prisma 分岐削除。"
```

### Task 5.2: ツーリング・依存・CI/Devcontainer・env テンプレからの Prisma 痕跡削除

**派生元:** Task 5.1 のブランチ — Prisma コードが消えた状態でないと、CI から `prisma generate` を消すと Prisma コードのある古いリビジョンでテストが回らなくなる

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `.devcontainer/devcontainer.json`
- Modify: `.env.example`
- Delete: `.env.prisma.example`
- Delete: `.env.prisma.template`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feat/supabase-adapter/phase-5-task-5.1-remove-prisma-code
git checkout -b feat/supabase-adapter/phase-5-task-5.2-remove-tooling
```

- [ ] **Step 2: `pyproject.toml` から `storage-prisma` extra と mypy override を削除**

`[project.optional-dependencies]` から:

```toml
storage-prisma = [
    "prisma>=0.15.0",
    "sqlparse>=0.5.0",
]
```

を削除。`all` extras も以下に修正:

```toml
all = [
    "context-store-mcp[storage-postgres,storage-supabase,embedding-local,embedding-openai,embedding-litellm,dashboard,evaluator]",
]
```

`[[tool.mypy.overrides]]` の `module = "prisma.*"` ブロックを削除。

- [ ] **Step 3: `.github/workflows/ci.yml` から Prisma 関連ステップを削除**

以下のステップを削除:

```yaml
      - name: Setup Node.js (for Prisma CLI)
        uses: actions/setup-node@1d0ff469b7ec7b3cb9d8673fde0c81c44821de2a # v4.2.0
        with:
          node-version: '20'

      - name: Generate Prisma Client
        run: uv run prisma generate --schema=./prisma/schema.prisma
```

最終的な `.github/workflows/ci.yml` (Prisma 削除後):

```yaml
name: CI

on:
  push:
    branches: ["master", "**"]
  pull_request:
    branches: ["master", "main"]

jobs:
  test:
    runs-on: ubuntu-slim

    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2

      - name: Install uv
        uses: astral-sh/setup-uv@1edb52594c857e2b5b13128931090f0640537287 # v5.3.0
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Run ruff check
        run: uv run ruff check src/ tests/

      - name: Run ruff format check
        run: uv run ruff format --check src/ tests/

      - name: Run mypy
        run: uv run mypy src/

      - name: Run unit tests
        run: uv run pytest tests/unit -v --cov=src/context_store --cov-report=term-missing
        env:
          OPENAI_API_KEY: sk-dummy-key-for-ci-validation
```

- [ ] **Step 4: `.devcontainer/devcontainer.json` から Prisma タスクを削除**

`tasks` 配列内の以下のタスク定義を削除:

```jsonc
{
  "label": "Prisma Generate",
  "type": "shell",
  "command": "uv run prisma generate --schema=./prisma/schema.prisma",
  "problemMatcher": [],
  "presentation": { "reveal": "always", "panel": "shared" },
  "dependsOn": ["Install Dependencies"]
},
```

- [ ] **Step 5: env テンプレを整理**

`.env.example` を以下に更新 (Supabase エントリ追加):

```bash
# === Storage Backend ===
# SQLite (Local):  storage_backend=sqlite, graph_enabled=true (optional)
# PostgreSQL + Neo4j (Cloud/Production): storage_backend=postgres, graph_enabled=true
# Supabase (HTTPS-only managed PostgreSQL): storage_backend=supabase
STORAGE_BACKEND=supabase
GRAPH_ENABLED=false

# === Supabase (storage_backend=supabase の場合に必須) ===
# ⚠ SECURITY: SUPABASE_KEY (service_role) は RLS をバイパスする最高権限キー。
#   - クライアントサイドコード/ブラウザに**絶対に**埋め込まない (この .env はサーバ専用)
#   - サーバの環境変数 / Secrets Manager (AWS Secrets Manager, Doppler 等) で管理し、
#     git に commit しない (.gitignore で `.env` を除外)
#   - 漏洩時は Supabase Dashboard > Settings > API から直ちに再生成
#   - 定期ローテーションを運用に組み込む
#   - クライアント側からも参照する場合は anon key + RLS ポリシーを使う
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=replace-with-service-role-key

# === Redis (Cache) ===
CACHE_BACKEND=inmemory
REDIS_URL=redis://localhost:6379
REDIS_SSL=false

# === Embedding ===
EMBEDDING_PROVIDER=local-model
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m
EMBEDDING_DIMENSION=768

# === Search & Lifecycle ===
SIMILARITY_THRESHOLD=0.70
DEDUP_THRESHOLD=0.90
DEFAULT_TOP_K=10
DECAY_HALF_LIFE_DAYS=30
ARCHIVE_THRESHOLD=0.05
PURGE_RETENTION_DAYS=90

# === Dashboard ===
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8000

# === URL Fetch (SSRF 対策) ===
ALLOW_PRIVATE_URLS=false
URL_FETCH_CONCURRENCY=3
URL_MAX_REDIRECTS=3
URL_MAX_RESPONSE_BYTES=10485760
URL_TIMEOUT_SECONDS=30
```

Prisma 専用テンプレを削除:

```bash
git rm .env.prisma.example .env.prisma.template
```

- [ ] **Step 6: devcontainer 内で全体回帰を確認**

```bash
uv sync --all-extras --dev
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

Expected: すべて PASS

- [ ] **Step 7: コミット**

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml .devcontainer/devcontainer.json .env.example
git add -A  # .env.prisma.* の削除を反映
git commit -m "chore: Prisma 依存・CI/Devcontainer ステップ・env テンプレを削除"
```

- [ ] **Step 8: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base feat/supabase-adapter/phase-5-task-5.1-remove-prisma-code \
  --title "chore: remove Prisma tooling & env templates" \
  --body "Phase 5 Task 5.2. pyproject extras / mypy override / CI Prisma generate / devcontainer タスク / .env.prisma.* を削除。.env.example を Supabase デフォルトに更新。"
```

---

## Phase 6: Documentation

**Phase Base ブランチ:** `feat/supabase-adapter/phase-6` ← Phase 5 完了後の master

### Task 6.1: README に Supabase セットアップ手順と Prisma → Supabase 移行ガイドを追記

**派生元:** `master` (Base) — ドキュメント追記のみで単体完結。Phase 5 まで取り込まれた master を前提とするが、コード依存はない

**Files:**
- Modify: `README.md`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master && git pull --ff-only origin master
git checkout -b feat/supabase-adapter/phase-6-task-6.1-docs
```

- [ ] **Step 2: README に Supabase セクションを追加**

`README.md` の "Storage backends" 周辺セクションに以下を追記 (該当セクションがなければ最後に新規追加):

````markdown
### Supabase バックエンド (HTTPS-only PostgreSQL)

社内ネットワークで TCP/5432 が遮断されている場合に、HTTPS (443) のみで動作する Supabase Data API (PostgREST) を利用できます。

#### 1. Supabase プロジェクトの準備

1. [Supabase Dashboard](https://app.supabase.com) でプロジェクトを作成
2. Supabase CLI でリポジトリにリンクしてマイグレーションを適用
   ```bash
   supabase link --project-ref <YOUR_PROJECT_REF>
   supabase db push
   ```
   あるいは Studio の SQL Editor から `supabase/migrations/20260518000001_initial_schema.sql` → `20260518000002_rpc_functions.sql` の順に手動実行
3. **Settings → API** から `Project URL` と `service_role` キーを取得

#### 2. 環境変数

```bash
STORAGE_BACKEND=supabase
GRAPH_ENABLED=false
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=<service_role_key>
EMBEDDING_DIMENSION=768
EMBEDDING_PROVIDER=local-model
LOCAL_MODEL_NAME=cl-nagoya/ruri-v3-310m
```

> ⚠ **SUPABASE_KEY のセキュリティ**
> `service_role` キーは Row Level Security をバイパスする最高権限キーです。
> - **クライアントコード / ブラウザに絶対に埋め込まない** (サーバサイド専用)
> - サーバの環境変数 / Secrets Manager (AWS Secrets Manager, Doppler 等) で管理し、 git に commit しない
> - 漏洩時は Supabase Dashboard > Settings > API から直ちに再生成 (rotate)
> - クライアントからも参照する用途では **anon key + RLS ポリシー** を利用する

`EMBEDDING_DIMENSION` は `supabase/migrations/20260518000001_initial_schema.sql` の `vector(768)` と一致しなければ起動時に `INVALID_STATE` で fail-fast します。次元数を変更したい場合は SQL と環境変数を同時に更新してください。

#### 3. 依存インストール

devcontainer 内で:

```bash
uv sync --extra storage-supabase --extra dashboard --extra embedding-local
```

#### 4. (旧 Prisma ユーザー向け) 移行手順

1. `.env` で `STORAGE_BACKEND=prisma` → `supabase` に変更
2. `PRISMA_DATABASE_URL` を削除し、`SUPABASE_URL` / `SUPABASE_KEY` を設定
3. 必要に応じて `pg_dump` / `pg_restore` で既存データを Supabase プロジェクトへ移行 (本リポジトリは自動移行スクリプトを提供しない)
````

- [ ] **Step 3: lint チェック (markdownlint があれば)**

devcontainer 内で:

```bash
uv run python -c "import pathlib; print(pathlib.Path('README.md').read_text()[:200])"  # 簡易確認
```

- [ ] **Step 4: コミット**

```bash
git add README.md
git commit -m "docs: Supabase バックエンドのセットアップ手順と Prisma → Supabase 移行ガイドを追記"
```

- [ ] **Step 5: Phase Base 向け Draft PR を作成**

```bash
git push -u origin HEAD
gh pr create --draft --base master \
  --title "docs: Supabase backend setup & migration guide" \
  --body "Phase 6 Task 6.1. README に Supabase セクション追加、Prisma からの移行手順を記載。"
```

---

## Phase Completion: Final Integration

すべての Phase の Draft PR がレビュー完了 → Ready for review → マージされたら、以下を実施:

- [ ] **Final Step 1: Supabase 本番プロジェクトに migration を適用**

```bash
supabase link --project-ref <YOUR_PROJECT_REF>
supabase db push
```

- [ ] **Final Step 2: 本番 `.env` の更新確認 (リポジトリ外)**

`SUPABASE_URL` / `SUPABASE_KEY` / `EMBEDDING_DIMENSION=768` がセットされていることを確認。

- [ ] **Final Step 3: スモークテスト (devcontainer + ライブ Supabase)**

```bash
SUPABASE_LIVE_TEST=1 uv run pytest tests/storage/integration/test_supabase_live.py -v
```

(統合テストファイル自体は本フェーズの合格条件には含めず、必要時に追加)

- [ ] **Final Step 4: 受け入れ基準 (設計書 Section 11) の充足を確認**

設計書の 7 項目すべてを `gh pr view` のチェックリストで確認後にマージ。

---

## Risks & Mitigations (設計書 Section 10 より)

| リスク | 対応策 |
| --- | --- |
| `vector(1024)` で運用中の既存環境がある可能性 | Phase 6 Task 6.1 の README 追記で次元確認を促す + Task 3.2 の起動時 probe で fail-fast |
| supabase-py の `or_` 構文が表記揺れする可能性 | Task 3.6 の cursor pagination テストで実装と仕様の双方を固定。実装時に supabase-py の最新ドキュメントを確認 |
| `client.postgrest.aclose()` の属性名がバージョン差で異なる | Task 3.1 の `dispose` 実装で `hasattr` ガード済み |
| 将来 `EMBEDDING_DIMENSION` 変更時に SQL/Python の二重更新が必要 | Task 2.2 で `SUPABASE_VECTOR_DIMENSION` 定数を導入し、変更箇所を 2 つ (定数 + migrations) に限定 |
