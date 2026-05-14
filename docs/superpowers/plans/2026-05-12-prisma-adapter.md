# PrismaStorageAdapter 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. All tests/lint MUST be executed **inside the Devcontainer**, never on the host Python.

**Goal:** 社内ネットワークでの PostgreSQL 直接接続遮断を回避するため、HTTPS (443) 経由で Prisma Accelerate を介して PostgreSQL に接続する `StorageAdapter` 実装を追加し、`STORAGE_BACKEND=prisma` で切替可能にする。

**Architecture:** 既存 `StorageAdapter` プロトコルに準拠する新規 `PrismaStorageAdapter` を `src/context_store/storage/prisma.py` に実装する。SQL は既存 `PostgresStorageAdapter` の `$1, $2, ...` プレースホルダ表現をそのまま流用し、`prisma.Prisma.query_raw / execute_raw` を介して発行する。pgvector / HNSW / GIN 等の DDL は既存 SQL マイグレーションファイル側に維持し、Prisma Migrate は導入しない。Accelerate の 5 MB / 10 s 制約に対しては `top_k` ハードリミット (200) と batch fetch チャンク分割 (250) + 縮小リトライ (1 回限り) のフェールセーフを設計に組み込む。

**Tech Stack:** Python 3.12 / asyncio / Prisma Client Python (`prisma>=0.15.0`, generator `prisma-client-py` async) / Pydantic v2 / pytest + `AsyncMock` / Node.js 20 (Devcontainer 内、`prisma generate` 専用)。

**Reference:** 設計書 `docs/superpowers/specs/2026-05-12-prisma-adapter-design.md`

---

## ファイル構成

各タスクが触れるファイルと責務:

| パス | 種別 | 責務 |
|---|---|---|
| `prisma/schema.prisma` | 新規 | Prisma Client 生成のためのスキーマ定義 (`memories` モデル + datasource/generator)。HNSW/GIN は対象外。 |
| `pyproject.toml` | 編集 | `storage-prisma` extras に `prisma>=0.15.0` を追加。`prisma.*` 用 mypy override を追加。 |
| `src/context_store/config.py` | 編集 | `storage_backend` Literal に `"prisma"` を追加。`prisma_database_url: SecretStr` を追加。`_validate_storage_config` を拡張。 |
| `src/context_store/storage/prisma.py` | 新規 | `PrismaStorageAdapter` 本体 + `_PrismaMigrationRunner` (private) + 定数 `PRISMA_MAX_TOP_K=200` / `PRISMA_BATCH_FETCH_CHUNK_SIZE=250` / `PRISMA_TIMEOUT_CODES` / `PRISMA_PAYLOAD_TOO_LARGE_CODES`。 |
| `src/context_store/storage/factory.py` | 編集 | `storage_backend == "prisma"` の分岐を追加。`read_only=True` で `NotImplementedError`、`graph_enabled=True` で `ValueError`。 |
| `.devcontainer/setup.sh` | 編集 | Node.js 20 を GPG 検証付きでインストール後、`prisma generate` を実行。 |
| `.devcontainer/devcontainer.json` | 編集 | `Install Dependencies` タスクを bare `pip` から `uv sync --all-extras --dev` に置換。`Prisma Generate` タスクを新設。 |
| `.github/workflows/ci.yml` | 編集 | Node.js セットアップステップ + `prisma generate` ステップを追加。 |
| `tests/unit/storage/test_prisma_adapter.py` | 新規 | `AsyncMock` ベースの単体テスト。`top_k` クランプ、チャンク分割境界、タイムアウトフォールバック、`P6004`/`P6009` シミュレーションを網羅。 |

---

## Phase 構成と Git ブランチ運用

| Phase | 内容 | 親ブランチ |
|---|---|---|
| Phase 1 | 基盤整備 (schema / extras / Settings / Devcontainer / CI) — 独立タスク中心 | `feature/phase1_prisma_foundation__base` (from `master`) |
| Phase 2 | `PrismaStorageAdapter` 本体実装 — 同一ファイルへの数珠つなぎ | `feature/phase2_prisma_adapter__base` (from `master`、Phase 1 が `master` にマージ済みであることが前提) |
| Phase 3 | Factory 統合 + Live (opt-in) スモークテスト | `feature/phase3_prisma_factory__base` (from `master`、Phase 2 が `master` にマージ済みであることが前提) |

**Phase 進行の絶対ルール (再掲):**

- 前 Phase の Draft PR が `master` にマージされるまで、次 Phase の作業に進まない。
- Task ブランチを `feature/phaseX_*__base` にマージしてはならない (Draft PR でレビューのみ実施)。
- `master` への直 push および `master` への PR マージは禁止。マージは人手レビュー後に実施。
- すべてのテスト・ruff・mypy は **Devcontainer 内**で実行する。ホスト Python では実行しない。

**Devcontainer 起動の前提コマンド (各 Phase / Task 開始時):**

```bash
# VS Code: "Dev Containers: Reopen in Container"
# または CLI:
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash
```

以降のコマンド (`pytest`, `ruff`, `mypy`, `prisma generate`) はすべて Devcontainer のシェル内で実行する。

---

## Phase 1: 基盤整備

**Phase Base ブランチ作成:**

```bash
git checkout master
git pull --ff-only origin master
git checkout -b feature/phase1_prisma_foundation__base
git push -u origin feature/phase1_prisma_foundation__base
```

このベースブランチには変更を一切加えない (各 Task ブランチが Draft PR でレビューを受ける)。

---

### Task 1.1: `prisma/schema.prisma` 新規作成

**派生元:** `feature/phase1_prisma_foundation__base` (Base 派生 — 単独ファイル、他タスクと無依存)

**Files:**
- Create: `prisma/schema.prisma`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_prisma_foundation__base
git checkout -b feature/phase1-task1_schema_prisma
```

- [ ] **Step 2: `prisma/schema.prisma` を新規作成**

```prisma
// prisma/schema.prisma

generator client {
  provider             = "prisma-client-py"
  interface            = "asyncio"
  recursive_type_depth = 5
}

datasource db {
  provider = "postgresql"
  url      = env("PRISMA_DATABASE_URL")
}

model memories {
  id                 String                       @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  content            String
  memory_type        String                       @db.VarChar(20)
  source_type        String                       @db.VarChar(20)
  source_metadata    Json                         @default("{}")
  embedding          Unsupported("vector(768)")?
  semantic_relevance Float                        @default(0.5)
  importance_score   Float                        @default(0.5)
  access_count       Int                          @default(0)
  last_accessed_at   DateTime                     @default(now()) @db.Timestamptz
  created_at         DateTime                     @default(now()) @db.Timestamptz
  updated_at         DateTime                     @default(now()) @db.Timestamptz
  archived_at        DateTime?                    @db.Timestamptz
  tags               String[]                     @default([])
  project            String?
  content_hash       String                       @unique
}
```

- [ ] **Step 3: Devcontainer 内で `prisma generate` のドライランを試行**

Devcontainer の Node.js が Task 1.4 で導入されるため、本タスクでは構文確認のみを行う。`prisma` CLI が手元になければ Step 4 へ進む (Task 1.4 マージ後に `feature/phase1-task1_schema_prisma` のローカル確認時に通る)。

```bash
# Devcontainer 内、prisma CLI が利用可能な場合のみ
which prisma && prisma format --schema=./prisma/schema.prisma
```
Expected: 構文エラーなし、または `prisma not found` (この場合は本タスクではスキップ可)。

- [ ] **Step 4: コミット**

```bash
git add prisma/schema.prisma
git commit -m "feat(storage): add Prisma schema for memories model"
```

- [ ] **Step 5: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase1-task1_schema_prisma
gh pr create \
  --base feature/phase1_prisma_foundation__base \
  --head feature/phase1-task1_schema_prisma \
  --draft \
  --title "[Phase1/Task1] Prisma schema for memories model" \
  --body "$(cat <<'EOF'
## Summary
- `prisma/schema.prisma` を新規追加し、`memories` モデルと datasource/generator を定義
- HNSW/GIN/`::vector` キャストなどは引き続き SQL マイグレーション側で管理 (本 PR では Prisma Migrate を導入しない)

## Test plan
- [ ] Devcontainer 内で `prisma format --schema=./prisma/schema.prisma` がエラーなく完了する (Task 1.4 マージ後)
- [ ] `prisma generate --schema=./prisma/schema.prisma` で `prisma` パッケージが生成される (Task 1.4 マージ後)
EOF
)"
```

---

### Task 1.2: `pyproject.toml` に `storage-prisma` extras と mypy override を追加

**派生元:** `feature/phase1_prisma_foundation__base` (Base 派生 — `pyproject.toml` 単独編集、他タスク無依存)

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_prisma_foundation__base
git checkout -b feature/phase1-task2_pyproject_extras
```

- [x] **Step 2: `pyproject.toml` の `[project.optional-dependencies]` に `storage-prisma` を追加**

`pyproject.toml` の `storage-postgres` の直後に以下を追加する:

```toml
storage-prisma = [
    "prisma>=0.15.0",
]
```

- [x] **Step 3: `pyproject.toml` の `[tool.mypy.overrides]` セクションに `prisma.*` 用 override を追加**

`asyncpg.*` の override の直後に追加する:

```toml
[[tool.mypy.overrides]]
module = "prisma.*"
ignore_missing_imports = true
```

- [x] **Step 4: メタ extras (例: `context-store-mcp[...]`) に `storage-prisma` を追記しない**

`storage-prisma` は opt-in。既存利用者への影響を避けるため、メタ extras には含めない。

- [x] **Step 5: ロックファイル更新を Devcontainer 内で実行**

```bash
# Devcontainer 内
uv lock
```
Expected: `uv.lock` が更新され、`prisma==0.15.x` が追加される。

- [x] **Step 6: Devcontainer 内で extras 解決を確認**

```bash
uv sync --all-extras
uv run python -c "import prisma; print(prisma.__version__)"
```
Expected: バージョン (例: `0.15.0`) が出力される。

- [x] **Step 7: 静的解析を Devcontainer 内で実行**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```
Expected: いずれもエラーなく完了。

- [ ] **Step 8: コミット**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add storage-prisma extras and mypy override for prisma"
```

- [ ] **Step 9: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase1-task2_pyproject_extras
gh pr create \
  --base feature/phase1_prisma_foundation__base \
  --head feature/phase1-task2_pyproject_extras \
  --draft \
  --title "[Phase1/Task2] Add storage-prisma extras and mypy override" \
  --body "$(cat <<'EOF'
## Summary
- `storage-prisma = ["prisma>=0.15.0"]` を `[project.optional-dependencies]` に追加 (opt-in)
- `prisma.*` モジュール用 mypy override を追加

## Test plan
- [ ] Devcontainer 内で `uv sync --all-extras` が成功
- [ ] `uv run python -c "import prisma"` が成功
- [ ] `mypy src/` がエラーなし
EOF
)"
```

---

### Task 1.3: `Settings` (config.py) を `storage_backend="prisma"` 対応に拡張

**派生元:** `feature/phase1_prisma_foundation__base` (Base 派生 — `config.py` 単独編集、Task 1.2 と物理的依存なし。`prisma` モジュールを import しないため pyproject.toml 変更不要)

**Files:**
- Modify: `src/context_store/config.py:57` (Literal 拡張)
- Modify: `src/context_store/config.py:73` 付近 (新フィールド追加)
- Modify: `src/context_store/config.py:226-235` (`_validate_storage_config` 拡張)
- Modify: `src/context_store/config.py:264-272` (`graph_backend` 拡張)
- Test: `tests/unit/test_config.py` (既存ファイルに追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_prisma_foundation__base
git checkout -b feature/phase1-task3_settings_prisma_backend
```

- [ ] **Step 2: 失敗するテストを `tests/unit/test_config.py` に追加**

`tests/unit/test_config.py` の末尾に以下を追加:

```python
import pytest

from pydantic import ValidationError

from context_store.config import Settings


def test_settings_accepts_prisma_backend(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv(
        "PRISMA_DATABASE_URL",
        "prisma://accelerate.prisma-data.net/?api_key=test-key",
    )
    settings = Settings()
    assert settings.storage_backend == "prisma"
    assert settings.prisma_database_url.get_secret_value().startswith("prisma://")


def test_settings_rejects_empty_prisma_url_when_backend_is_prisma(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv("PRISMA_DATABASE_URL", "")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "PRISMA_DATABASE_URL" in str(exc_info.value)


def test_settings_rejects_non_prisma_scheme_url(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv(
        "PRISMA_DATABASE_URL",
        "postgresql://user:pass@host:5432/db",
    )
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "prisma://" in str(exc_info.value) or "prismas://" in str(exc_info.value)


def test_settings_rejects_prisma_with_graph_enabled(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv(
        "PRISMA_DATABASE_URL",
        "prisma://accelerate.prisma-data.net/?api_key=test-key",
    )
    monkeypatch.setenv("GRAPH_ENABLED", "true")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "graph" in str(exc_info.value).lower()


def test_graph_backend_is_disabled_for_prisma(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv(
        "PRISMA_DATABASE_URL",
        "prisma://accelerate.prisma-data.net/?api_key=test-key",
    )
    settings = Settings()
    assert settings.graph_backend == "disabled"
```

- [ ] **Step 3: テストを実行して失敗を確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/test_config.py -v -k "prisma"
```
Expected: 5 件すべて FAIL (`Settings` がまだ `"prisma"` を許容しないため)。

- [ ] **Step 4: `src/context_store/config.py:57` の Literal を拡張**

```python
storage_backend: Literal["sqlite", "postgres", "prisma"] = "sqlite"
```

- [ ] **Step 5: `src/context_store/config.py:73` 付近 (PostgreSQL ブロックの直後) に新フィールドを追加**

```python
    # --- Prisma Accelerate (storage_backend=prisma の場合) ---
    prisma_database_url: SecretStr = SecretStr("")
```

- [ ] **Step 6: `_validate_storage_config` (`config.py:226-235`) を拡張**

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
                raise ValueError(
                    "PRISMA_DATABASE_URL は storage_backend=prisma の場合に必須です。"
                )
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
        return self
```

- [ ] **Step 7: `graph_backend` computed_field (`config.py:264-272`) を拡張**

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
        # prisma は graph_enabled=true との組合せを拒否するため到達不可
        return "disabled"
```

- [ ] **Step 8: テストを実行して PASS を確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/test_config.py -v -k "prisma"
```
Expected: 5 件すべて PASS。

- [ ] **Step 9: 既存テストの回帰がないか確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/test_config.py -v
uv run ruff check src/context_store/config.py tests/unit/test_config.py
uv run mypy src/context_store/config.py
```
Expected: 全 PASS、lint/mypy エラーなし。

- [ ] **Step 10: コミット**

```bash
git add src/context_store/config.py tests/unit/test_config.py
git commit -m "feat(config): add prisma storage backend literal and validators"
```

- [ ] **Step 11: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase1-task3_settings_prisma_backend
gh pr create \
  --base feature/phase1_prisma_foundation__base \
  --head feature/phase1-task3_settings_prisma_backend \
  --draft \
  --title "[Phase1/Task3] Settings: storage_backend=prisma literal and validators" \
  --body "$(cat <<'EOF'
## Summary
- `storage_backend` Literal に `"prisma"` を追加
- `prisma_database_url: SecretStr` フィールドを追加
- `_validate_storage_config` を拡張し、空 URL / 非 prisma スキーム / `graph_enabled=true` の組合せを拒否

## Test plan
- [ ] `pytest tests/unit/test_config.py -v -k prisma` が全 PASS
- [ ] 既存 `pytest tests/unit/test_config.py -v` に回帰なし
- [ ] `mypy src/context_store/config.py` がエラーなし
EOF
)"
```

---

### Task 1.4: Devcontainer に Node.js 20 + `prisma generate` を組込み

**派生元:** `feature/phase1_prisma_foundation__base` (Base 派生 — Devcontainer 関連ファイルのみ。Task 1.1 の schema.prisma がなくても `prisma generate` ステップは Task 1.1 マージ後に動作するため、コードとしては独立)

**Files:**
- Modify: `.devcontainer/setup.sh`
- Modify: `.devcontainer/devcontainer.json` (`Install Dependencies` task + `Prisma Generate` task 新設)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_prisma_foundation__base
git checkout -b feature/phase1-task4_devcontainer_prisma
```

- [ ] **Step 2: `.devcontainer/setup.sh` を編集**

既存 `setup.sh` の `uv sync --frozen --all-extras` の前後に以下を追加:

```bash
#!/bin/bash
set -e

cd /workspaces/chronos-graph

# Node.js (Prisma CLI 用) - GPG 署名検証を含むセキュアなインストール
if ! command -v node >/dev/null 2>&1; then
  NODE_MAJOR=20
  sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
    | sudo tee /etc/apt/sources.list.d/nodesource.list
  sudo apt-get update && sudo apt-get install -y nodejs
fi

echo "Installing dependencies..."
uv sync --frozen --all-extras

# Prisma Client Python の生成 (schema.prisma → ./prisma/ パッケージ生成)
if [ -f ./prisma/schema.prisma ]; then
  uv run prisma generate --schema=./prisma/schema.prisma
fi

echo "Devcontainer setup complete!"
echo ""
echo "Available tasks (Ctrl+Shift+P → Tasks: Run Task):"
echo "  - Run Tests"
echo "  - Run Ruff Check"
echo "  - Run MyPy"
echo "  - Run Full Lint"
echo "  - Start Infrastructure"
echo "  - Prisma Generate"
echo ""
echo "Or run manually:"
echo "  pytest tests/ -v"
echo "  ruff check src/ tests/"
echo "  mypy src/"
echo "  prisma generate --schema=./prisma/schema.prisma"
```

- [ ] **Step 3: `.devcontainer/devcontainer.json` の `Install Dependencies` タスクの command を更新**

既存 `pip install -e ".[dev,storage-postgres]"` は bare `pip` 呼び出しで
uv 管理 venv の外にインストールされる恐れがあるため、setup.sh / CI と同一の
`uv sync --all-extras --dev` に置換する。これにより `pyproject.toml` の
`storage-prisma` extras が自動的に取り込まれ、タスク定義側に extras 名を
列挙する必要がなくなる (設計書 §7.3)。

```jsonc
{
  "label": "Install Dependencies",
  "type": "shell",
  "command": "uv sync --all-extras --dev",
  ...
}
```

- [ ] **Step 4: `.devcontainer/devcontainer.json` の `tasks` 配列に `Prisma Generate` を新設**

`Install Dependencies` タスクの直後に追加:

```jsonc
{
  "label": "Prisma Generate",
  "type": "shell",
  "command": "prisma generate --schema=./prisma/schema.prisma",
  "problemMatcher": [],
  "presentation": {
    "reveal": "always",
    "panel": "shared"
  },
  "dependsOn": [
    "Install Dependencies"
  ]
},
```

- [x] **Step 5: setup.sh の構文を Devcontainer 内で検証**

```bash
bash -n .devcontainer/setup.sh
```
Expected: 構文エラーなし。

- [x] **Step 6: devcontainer.json の JSON 構文を検証**

```bash
uv run python -c "import json; json.load(open('.devcontainer/devcontainer.json'))"
```
Expected: エラーなく完了 (JSON-with-comments を許容するなら `json5` パーサ。VS Code は JSONC を受け付ける)。

> **Note:** `.devcontainer/devcontainer.json` は JSONC (コメント許可) のため、純 JSON パーサだとコメント行で失敗する。その場合は `npx -y jsonc-parser` あるいは VS Code の `Dev Containers: Validate` を利用してもよい。

- [ ] **Step 7: 統合確認 (Task 1.1 と Task 1.2 が Devcontainer 内に既にローカル merge されている必要があるため、本タスク単体では `prisma generate` 実行を後送りでよい)**

本タスクではスクリプト変更のレビューが目的であり、`prisma generate` の実機動作確認は Phase 1 全体の `master` マージ後の Devcontainer 再構築で行う。

- [ ] **Step 8: コミット**

```bash
git add .devcontainer/setup.sh .devcontainer/devcontainer.json
git commit -m "feat(devcontainer): install Node.js 20 and run prisma generate on setup"
```

- [ ] **Step 9: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase1-task4_devcontainer_prisma
gh pr create \
  --base feature/phase1_prisma_foundation__base \
  --head feature/phase1-task4_devcontainer_prisma \
  --draft \
  --title "[Phase1/Task4] Devcontainer: Node.js 20 and prisma generate on setup" \
  --body "$(cat <<'EOF'
## Summary
- `.devcontainer/setup.sh` に GPG 検証付き Node.js 20 インストールと `prisma generate` を追加
- `.devcontainer/devcontainer.json` の `Install Dependencies` タスクを bare `pip install -e` から `uv sync --all-extras --dev` に置換 (uv 管理 venv との整合性確保)
- `Prisma Generate` タスクを新設

## Test plan
- [ ] `bash -n .devcontainer/setup.sh` が成功
- [ ] Devcontainer の再構築で Node.js 20 がインストールされる (Phase 1 マージ後の検証)
- [ ] Devcontainer の再構築で `prisma generate` が成功する (Phase 1 マージ後の検証)
EOF
)"
```

---

### Task 1.5: CI ワークフローに Prisma 用ステップを追加

**派生元:** `feature/phase1_prisma_foundation__base` (Base 派生 — `.github/workflows/ci.yml` 単独編集。コードとしては Task 1.1/1.2 と独立。実行確認は Phase 1 マージ後に行う)

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_prisma_foundation__base
git checkout -b feature/phase1-task5_ci_prisma
```

- [ ] **Step 2: `.github/workflows/ci.yml` に Node.js セットアップと `prisma generate` ステップを追加**

`Install dependencies` ステップの直後、`Run ruff check` ステップの直前に挿入する:

```yaml
      - name: Setup Node.js (for Prisma CLI)
        uses: actions/setup-node@<COMMIT_SHA_TO_BE_LOOKED_UP> # vX.Y.Z (実装時に最新 v4 安定版を確認)
        with:
          node-version: '20'

      - name: Generate Prisma Client
        run: uv run prisma generate --schema=./prisma/schema.prisma
```

> **⚠ 重要 — SHA pin の検証手順 (実装時に必ず実施すること):**
>
> 上記の `<COMMIT_SHA_TO_BE_LOOKED_UP>` を**そのままコピー** / **過去のドキュメント例をコピー**してはならない。実装時点で最新の `actions/setup-node` v4 安定版を以下の手順で照会し、返ってきた SHA と対応タグを `# vX.Y.Z` コメントとともに pin する。
>
> ```bash
> # 1. 最新の v4 系タグ一覧を取得 (リリース日と関連付け)
> gh api repos/actions/setup-node/releases --jq \
>   '.[] | select(.tag_name | startswith("v4.")) | {tag: .tag_name, published: .published_at}' \
>   | head -20
>
> # 2. 採用するタグ (例: v4.X.Y) を決めたら、そのタグが指す commit SHA を取得
> TAG="v4.X.Y"  # 実際に採用するタグに置換
> gh api repos/actions/setup-node/git/ref/tags/${TAG} --jq '.object.sha'
>
> # 3. 取得した SHA が tag オブジェクトの場合は dereference して commit SHA を取得
> SHA_FROM_TAG=$(gh api repos/actions/setup-node/git/ref/tags/${TAG} --jq '.object.sha')
> OBJECT_TYPE=$(gh api repos/actions/setup-node/git/ref/tags/${TAG} --jq '.object.type')
> if [ "$OBJECT_TYPE" = "tag" ]; then
>   gh api repos/actions/setup-node/git/tags/${SHA_FROM_TAG} --jq '.object.sha'
> else
>   echo "$SHA_FROM_TAG"
> fi
> ```
>
> 検証チェック:
> - 取得した commit SHA が 40 文字の hex であること
> - タグの `published_at` が `actions/setup-node` の Releases ページ ([https://github.com/actions/setup-node/releases](https://github.com/actions/setup-node/releases)) と一致すること
> - 該当 commit のセキュリティアドバイザリ ([https://github.com/actions/setup-node/security/advisories](https://github.com/actions/setup-node/security/advisories)) に有効な脆弱性報告がないこと
> - YAML 内のコメント `# vX.Y.Z` がタグ名と一致すること

- [ ] **Step 3: ワークフローの YAML 構文を検証 (Devcontainer 内)**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```
Expected: エラーなく完了。

- [ ] **Step 4: コミット**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add Node.js setup and prisma generate step"
```

- [ ] **Step 5: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase1-task5_ci_prisma
gh pr create \
  --base feature/phase1_prisma_foundation__base \
  --head feature/phase1-task5_ci_prisma \
  --draft \
  --title "[Phase1/Task5] CI: add Node.js setup and prisma generate step" \
  --body "$(cat <<'EOF'
## Summary
- CI に Node.js 20 セットアップステップを追加
- `Install dependencies` の直後に `uv run prisma generate --schema=./prisma/schema.prisma` を追加

## Test plan
- [ ] GitHub Actions の `CI / test` ジョブが PASS する (Phase 1 マージ後)
- [ ] `prisma generate` ステップが緑になる (Phase 1 マージ後)
EOF
)"
```

---

### Phase 1 完了アクション

- [ ] Phase 1 の全 Task Draft PR (Task 1.1〜1.5) のレビューを完了する。
- [ ] レビューア承認後、人手でベースブランチに各 Task の変更を取り込む (例: Task 1.1〜1.5 の commit を `feature/phase1_prisma_foundation__base` に cherry-pick または rebase merge)。
- [ ] Devcontainer を再構築して `prisma generate` が成功することを実機確認する。
- [ ] Devcontainer 内で全静的解析・テストが PASS することを確認する:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v
```

- [ ] `master` をターゲットとした Phase 1 Draft PR を作成する:

```bash
gh pr create \
  --base master \
  --head feature/phase1_prisma_foundation__base \
  --draft \
  --title "[Phase1] Prisma adapter foundation: schema, extras, settings, devcontainer, CI" \
  --body "$(cat <<'EOF'
## Summary
- Prisma Accelerate 経由 PostgreSQL アクセスに必要な基盤を整備
  - `prisma/schema.prisma` (memories モデル)
  - `pyproject.toml` の `storage-prisma` extras + mypy override
  - `Settings.storage_backend="prisma"` + `prisma_database_url` + バリデータ
  - Devcontainer に Node.js 20 + `prisma generate`
  - CI に Node.js セットアップ + `prisma generate` ステップ

## Test plan
- [ ] Devcontainer 内 `prisma generate --schema=./prisma/schema.prisma` が成功
- [ ] `pytest tests/unit/test_config.py -v` が全 PASS
- [ ] CI 全ジョブ green
EOF
)"
```

---

## Phase 2: PrismaStorageAdapter 本体実装

**前提:** Phase 1 の PR が `master` にマージ済みであること。

**Phase Base ブランチ作成:**

```bash
git checkout master
git pull --ff-only origin master
git checkout -b feature/phase2_prisma_adapter__base
git push -u origin feature/phase2_prisma_adapter__base
```

> **設計方針 (Phase 2 全タスク共通):**
> - すべてのタスクは新規ファイル `src/context_store/storage/prisma.py` を拡張する。
> - 同一ファイルへの連続編集のため、Task 2.2 以降は **直前 Task 派生 (数珠つなぎ)** となる。
> - 各メソッドの SQL は既存 `PostgresStorageAdapter` (`src/context_store/storage/postgres.py`) のものを物理的に同一文字列でコピーし、`pool.acquire() / conn.fetchrow / fetch / execute` の呼び出しのみ `prisma.query_first_raw / query_raw / execute_raw` に置き換える。
> - テストは `tests/unit/storage/test_prisma_adapter.py` に `AsyncMock` ベースで蓄積する。

---

### Task 2.1: アダプタースケルトン + ヘルパー再利用 + `create` / `dispose` + マイグレーションランナー

**派生元:** `feature/phase2_prisma_adapter__base` (Base 派生 — 新規ファイル作成)

**Files:**
- Create: `src/context_store/storage/prisma.py`
- Create: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_prisma_adapter__base
git checkout -b feature/phase2-task1_adapter_skeleton
```

- [ ] **Step 2: 失敗するテストを作成**

`tests/unit/storage/test_prisma_adapter.py` を新規作成:

```python
"""Unit tests for PrismaStorageAdapter using AsyncMock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.storage.prisma import (
    PRISMA_BATCH_FETCH_CHUNK_SIZE,
    PRISMA_MAX_TOP_K,
    PRISMA_PAYLOAD_TOO_LARGE_CODES,
    PRISMA_TIMEOUT_CODES,
    PrismaStorageAdapter,
)


@pytest.fixture
def mock_prisma() -> MagicMock:
    """Build an AsyncMock prisma.Prisma client."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.query_raw = AsyncMock(return_value=[])
    client.query_first_raw = AsyncMock(return_value=None)
    client.execute_raw = AsyncMock(return_value=0)
    return client


def test_constants_have_expected_values():
    assert PRISMA_MAX_TOP_K == 200
    assert PRISMA_BATCH_FETCH_CHUNK_SIZE == 250
    assert "P2024" in PRISMA_TIMEOUT_CODES
    assert "P2028" in PRISMA_TIMEOUT_CODES
    assert "P6004" in PRISMA_TIMEOUT_CODES
    assert "P6009" in PRISMA_PAYLOAD_TOO_LARGE_CODES


@pytest.mark.asyncio
async def test_dispose_disconnects_client(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.dispose()
    mock_prisma.disconnect.assert_awaited_once()


# -----------------------------------------------------------------------------
# _PrismaMigrationRunner unit tests (graph 非対応、baseline 検出、適用ロジック)
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_tx_context(mock_prisma) -> MagicMock:
    """Wire mock_prisma.tx() to behave as an async context manager."""
    tx = MagicMock()
    tx.execute_raw = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=tx)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_prisma.tx = MagicMock(return_value=cm)
    return tx


@pytest.mark.asyncio
async def test_migration_runner_filters_out_graph_migrations(mock_prisma, mock_tx_context, tmp_path, monkeypatch):
    """0002_graph.sql 等の graph 関連マイグレーションは Prisma 対象外として除外される。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    # ダミーの migrations ディレクトリを構築
    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE schema_migrations(version TEXT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")
    (migrations_dir / "0002_graph.sql").write_text("CREATE TABLE memory_nodes(id UUID);")

    # _PrismaMigrationRunner が参照する base ディレクトリを差し替え
    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    # 1) schema_migrations 不在 → ensure_system_migration が走る
    # 2) _get_applied_migrations は空集合
    # 3) baseline 検出のため pg_tables を問い合わせる ("memories" のみ要求)
    mock_prisma.query_raw = AsyncMock(side_effect=[
        Exception("relation \"schema_migrations\" does not exist"),  # ensure_system_migration の存在確認
        [],  # _get_applied_migrations: 空
        [],  # _tables_exist for 0001 (memories): なし
    ])
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # 0002_graph.sql は適用試行されない (tx.execute_raw に SQL 内容として渡されない)
    sqls_applied = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    assert not any("memory_nodes" in sql for sql in sqls_applied)
    # 0000_system.sql と 0001_initial.sql は適用される
    assert any("schema_migrations" in sql for sql in sqls_applied)
    assert any("memories" in sql for sql in sqls_applied)


@pytest.mark.asyncio
async def test_migration_runner_baselines_existing_memories_table(mock_prisma, mock_tx_context, tmp_path, monkeypatch):
    """memories テーブルが既存の場合、0001 を applied として記録 (再実行しない)。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("CREATE TABLE schema_migrations(version TEXT);")
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE memories(id UUID);")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    mock_prisma.query_raw = AsyncMock(side_effect=[
        [{"1": 1}],  # ensure_system_migration: schema_migrations 存在
        [],          # _get_applied_migrations: 空
        [{"tablename": "memories"}],  # _tables_exist for 0001: 既存
        [{"version": "0001_initial.sql"}],  # baseline 後の _get_applied_migrations
    ])
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # baseline INSERT が 0001_initial.sql で呼ばれる
    insert_calls = [
        call for call in mock_prisma.execute_raw.await_args_list
        if "INSERT INTO schema_migrations" in call.args[0]
    ]
    versions_inserted = {call.args[1] for call in insert_calls}
    assert "0001_initial.sql" in versions_inserted
    # 0001_initial.sql の SQL 本文は tx 経由では実行されない (baseline 済みのため)
    sqls_in_tx = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    assert not any("CREATE TABLE memories" in sql for sql in sqls_in_tx)


@pytest.mark.asyncio
async def test_migration_runner_applies_sequential_files(mock_prisma, mock_tx_context, tmp_path, monkeypatch):
    """複数の未適用ファイルを定義順に sequential に execute_raw する。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0000_system.sql").write_text("-- system")
    (migrations_dir / "0001_initial.sql").write_text("-- initial")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    mock_prisma.query_raw = AsyncMock(side_effect=[
        [{"1": 1}],  # ensure_system_migration: 存在
        [],          # _get_applied_migrations: 空
        [],          # _tables_exist for 0001: 不在 → baseline 対象なし
        [],          # baseline 後の _get_applied_migrations
    ])
    mock_prisma.execute_raw = AsyncMock(return_value=1)

    runner = _PrismaMigrationRunner(mock_prisma)
    await runner.run()

    # tx 内で実行された SQL の順序を検証 (0000 → 0001)
    sql_sequence = [call.args[0] for call in mock_tx_context.execute_raw.await_args_list]
    # 各マイグレーションは「本体 SQL → INSERT INTO schema_migrations」の 2 ステップ
    assert sql_sequence[0] == "-- system"
    assert "INSERT INTO schema_migrations" in sql_sequence[1]
    assert sql_sequence[2] == "-- initial"
    assert "INSERT INTO schema_migrations" in sql_sequence[3]


@pytest.mark.asyncio
async def test_migration_runner_transaction_failure_propagates(mock_prisma, tmp_path, monkeypatch):
    """tx 内の execute_raw が失敗した場合、例外が伝播し INSERT は実行されない。"""
    from context_store.storage.prisma import _PrismaMigrationRunner

    migrations_dir = tmp_path / "migrations" / "postgres"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "0001_initial.sql").write_text("-- broken")

    monkeypatch.setattr(
        "context_store.storage.prisma.__file__",
        str(tmp_path / "prisma.py"),
    )

    # tx() がコンテキストマネージャを返し、execute_raw で例外を送出
    tx = MagicMock()
    tx.execute_raw = AsyncMock(side_effect=RuntimeError("syntax error"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=tx)
    cm.__aexit__ = AsyncMock(return_value=False)  # 例外を抑制しない
    mock_prisma.tx = MagicMock(return_value=cm)

    mock_prisma.query_raw = AsyncMock(side_effect=[
        [],  # _get_applied_migrations: 空
        [],  # _tables_exist for 0001: 不在
        [],  # baseline 後の _get_applied_migrations
    ])
    mock_prisma.execute_raw = AsyncMock(return_value=0)

    runner = _PrismaMigrationRunner(mock_prisma)
    with pytest.raises(RuntimeError, match="syntax error"):
        await runner.run()

    # INSERT INTO schema_migrations は呼ばれていない (tx 内で失敗、外側の
    # execute_raw は baseline 用途のみで未呼び出し)
    assert tx.execute_raw.await_count >= 1
    # baseline は requirements に該当しないため execute_raw は呼ばれない
    assert mock_prisma.execute_raw.await_count == 0
```

- [ ] **Step 3: テストを実行して失敗確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: FAIL (`ImportError: cannot import name 'PrismaStorageAdapter' from 'context_store.storage.prisma'`)。

- [ ] **Step 4: `src/context_store/storage/prisma.py` を新規作成 (スケルトンのみ)**

```python
"""Prisma Accelerate-backed Storage Adapter.

社内ネットワークでの PostgreSQL 直接接続遮断を回避するため、HTTPS (443) 経由で
Prisma Accelerate を介して PostgreSQL にアクセスする実装。

設計仕様: docs/superpowers/specs/2026-05-12-prisma-adapter-design.md
"""

from __future__ import annotations

import logging
from typing import Any

from prisma import Prisma  # type: ignore[import-not-found]

from context_store.config import Settings
from context_store.storage.protocols import StorageError

logger = logging.getLogger(__name__)

# --- Accelerate 制約に対する定数 (設計書 4.3) ---
PRISMA_MAX_TOP_K: int = 200
PRISMA_BATCH_FETCH_CHUNK_SIZE: int = 250
PRISMA_TIMEOUT_CODES: frozenset[str] = frozenset({"P2024", "P2028", "P6004"})
PRISMA_PAYLOAD_TOO_LARGE_CODES: frozenset[str] = frozenset({"P6009"})


# ヘルパー関数は既存 PostgresStorageAdapter のものを物理的に再利用する。
# DRY の観点から本ファイルで再定義するのではなく、postgres.py から import する。
from context_store.storage.postgres import (  # noqa: E402
    _content_hash,
    _embedding_to_pg,
    _parse_embedding,
    _record_to_memory,
)

__all__ = [
    "PRISMA_BATCH_FETCH_CHUNK_SIZE",
    "PRISMA_MAX_TOP_K",
    "PRISMA_PAYLOAD_TOO_LARGE_CODES",
    "PRISMA_TIMEOUT_CODES",
    "PrismaStorageAdapter",
]
# 注: _content_hash / _embedding_to_pg / _parse_embedding / _record_to_memory は
# プライベートヘルパーであり再エクスポート対象としない (`from prisma import *` に
# 含めない)。本ファイル内部でのみ参照する。


class PrismaStorageAdapter:
    """StorageAdapter implementation backed by Prisma Accelerate (HTTPS)."""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    @classmethod
    async def create(cls, settings: Settings) -> "PrismaStorageAdapter":
        """Connect to Prisma Accelerate and apply migrations."""
        url = settings.prisma_database_url.get_secret_value().strip()
        client = Prisma(
            datasource={"url": url},
        )
        await client.connect()
        adapter = cls(client=client)
        try:
            await adapter.initialize()
        except Exception:
            await client.disconnect()
            raise
        return adapter

    async def initialize(self) -> None:
        """Apply schema migrations (既存 postgres/ ディレクトリの SQL を順次実行)."""
        runner = _PrismaMigrationRunner(self._client)
        await runner.run()

    async def dispose(self) -> None:
        """Disconnect the Prisma client."""
        await self._client.disconnect()


class _PrismaMigrationRunner:
    """Apply existing postgres/*.sql migrations via prisma.execute_raw."""

    def __init__(self, client: Prisma) -> None:
        self._client = client

    # Prisma バックエンドが処理対象とするマイグレーションのみを許可するファイル名 prefix。
    # 設計書 §2 で graph 機能は Prisma の対象外とされているため、0002_graph.sql 以降の
    # graph 関連マイグレーションは Prisma 経由では適用しない。
    _PRISMA_ALLOWED_MIGRATION_PREFIXES: frozenset[str] = frozenset({"0000", "0001"})

    async def run(self) -> None:
        """Apply pending migrations in order.

        実装方針:
        - postgres/ ディレクトリの SQL ファイルを `pathlib.Path` で列挙
        - `_PRISMA_ALLOWED_MIGRATION_PREFIXES` に含まれる prefix のもののみを対象とする
          (graph 関連の 0002* 等は Prisma バックエンドの対象外、設計書 §2)
        - `schema_migrations` テーブル存在チェックは `query_raw`
        - 適用済みバージョン取得は `query_raw`
        - 未適用ファイルを sequential に `execute_raw` で適用
        - `pg_catalog.pg_tables` を用いた baseline 検出は既存 MigrationRunner と同等
        """
        from pathlib import Path

        migrations_dir = (
            Path(__file__).parent / "migrations" / "postgres"
        )
        all_files = sorted(migrations_dir.glob("*.sql"))
        files = [
            f for f in all_files
            if f.name.split("_")[0] in self._PRISMA_ALLOWED_MIGRATION_PREFIXES
        ]

        # 0000_system.sql を必ず最初に確保
        system_file = migrations_dir / "0000_system.sql"
        if system_file.exists():
            await self._ensure_system_migration(system_file)

        applied = await self._get_applied_migrations()

        # Baseline: 既存テーブルが存在する場合は対応マイグレーションを applied として記録
        if not applied or applied == {"0000_system.sql"}:
            await self._handle_baseline(files, applied)
            applied = await self._get_applied_migrations()

        for file_path in files:
            version = file_path.name
            if version not in applied:
                await self._apply_migration(file_path)
                logger.info("Applied migration via Prisma: %s", version)

    async def _ensure_system_migration(self, file_path: "Path") -> None:  # type: ignore[name-defined]
        try:
            await self._client.query_raw("SELECT 1 FROM schema_migrations LIMIT 1")
            return
        except Exception:
            pass
        await self._apply_migration(file_path)

    async def _get_applied_migrations(self) -> set[str]:
        try:
            rows = await self._client.query_raw("SELECT version FROM schema_migrations")
        except Exception:
            return set()
        return {row["version"] for row in rows}

    async def _handle_baseline(
        self, files: list["Path"], applied: set[str]  # type: ignore[name-defined]
    ) -> None:
        # graph (memory_nodes / memory_edges) は Prisma バックエンド対象外のため
        # baseline 検出対象に含めない (設計書 §2)。
        requirements = {"0001": ["memories"]}
        to_baseline: list[str] = []
        for file_path in files:
            prefix = file_path.name.split("_")[0]
            req_tables = requirements.get(prefix)
            if req_tables and await self._tables_exist(req_tables):
                to_baseline.append(file_path.name)
        for version in to_baseline:
            await self._client.execute_raw(
                "INSERT INTO schema_migrations (version) VALUES ($1) "
                "ON CONFLICT DO NOTHING",
                version,
            )

    async def _tables_exist(self, table_names: list[str]) -> bool:
        rows = await self._client.query_raw(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE tablename = ANY($1::text[])",
            table_names,
        )
        return len(rows) == len(table_names)

    async def _apply_migration(self, file_path: "Path") -> None:  # type: ignore[name-defined]
        sql = file_path.read_text()
        version = file_path.name
        async with self._client.tx() as tx:
            await tx.execute_raw(sql)
            await tx.execute_raw(
                "INSERT INTO schema_migrations (version) VALUES ($1)", version
            )
```

- [ ] **Step 5: テストを実行して PASS を確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: 6 件すべて PASS (`test_constants_have_expected_values`, `test_dispose_disconnects_client`, および `_PrismaMigrationRunner` の 4 件 = graph 除外 / baseline / sequential / トランザクション失敗)。

- [ ] **Step 6: 静的解析を Devcontainer 内で実行**

```bash
uv run ruff check src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: いずれもエラーなし。

- [ ] **Step 7: コミット**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): add PrismaStorageAdapter skeleton with migration runner"
```

- [ ] **Step 8: Push & Draft PR 作成 (target: Phase Base)**

```bash
git push -u origin feature/phase2-task1_adapter_skeleton
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task1_adapter_skeleton \
  --draft \
  --title "[Phase2/Task1] PrismaStorageAdapter skeleton + migration runner" \
  --body "$(cat <<'EOF'
## Summary
- `PrismaStorageAdapter` の最小スケルトン (`create`, `dispose`, `initialize`)
- `_PrismaMigrationRunner` (private) で `postgres/*.sql` のうち prefix が 0000/0001 のみを順次適用 (graph: 0002* は Prisma 対象外として除外、設計書 §2)
- Accelerate 制約用定数 (`PRISMA_MAX_TOP_K=200`, `PRISMA_BATCH_FETCH_CHUNK_SIZE=250`, タイムアウト/payload too large コード)
- `__all__` は公開 API (アダプター + 定数) のみ。プライベートヘルパーは内部参照のみ
- `_PrismaMigrationRunner` の単体テスト 4 件 (graph 除外 / baseline / sequential / トランザクション失敗) を含む

## Test plan
- [ ] `pytest tests/unit/storage/test_prisma_adapter.py -v` が全 PASS (6 件)
- [ ] `ruff check` / `mypy` がエラーなし
EOF
)"
```

---

### Task 2.2: `save_memory` 実装

**派生元:** `feature/phase2-task1_adapter_skeleton` (直前 Task 派生 — 同一ファイル `prisma.py` 拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py` (`PrismaStorageAdapter` クラスにメソッド追加)
- Modify: `tests/unit/storage/test_prisma_adapter.py` (テスト追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task1_adapter_skeleton
git checkout -b feature/phase2-task2_save_memory
```

- [ ] **Step 2: 失敗するテストを追加**

`tests/unit/storage/test_prisma_adapter.py` の末尾に追加:

```python
from datetime import datetime, timezone
from uuid import uuid4

from context_store.models.memory import Memory, MemoryType, SourceType


def _build_memory(content: str = "hello") -> Memory:
    return Memory(
        id=str(uuid4()),
        content=content,
        memory_type=MemoryType.SEMANTIC,
        source_type=SourceType.MANUAL,
        source_metadata={},
        embedding=[0.1, 0.2, 0.3],
        semantic_relevance=0.5,
        importance_score=0.5,
        access_count=0,
        last_accessed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        archived_at=None,
        tags=[],
        project=None,
    )


@pytest.mark.asyncio
async def test_save_memory_inserts_and_returns_id(mock_prisma):
    memory = _build_memory("hello world")
    mock_prisma.query_first_raw = AsyncMock(return_value={"id": memory.id})

    adapter = PrismaStorageAdapter(client=mock_prisma)
    result_id = await adapter.save_memory(memory)

    assert result_id == memory.id
    mock_prisma.query_first_raw.assert_awaited_once()
    sql_arg = mock_prisma.query_first_raw.await_args.args[0]
    assert "INSERT INTO memories" in sql_arg
    assert "RETURNING id" in sql_arg


@pytest.mark.asyncio
async def test_save_memory_raises_duplicate_content(mock_prisma):
    from prisma.errors import UniqueViolationError  # type: ignore[import-not-found]

    memory = _build_memory("dup")
    mock_prisma.query_first_raw = AsyncMock(
        side_effect=UniqueViolationError("duplicate content_hash")
    )

    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "DUPLICATE_CONTENT"
    assert exc_info.value.recoverable is False
```

- [ ] **Step 3: テスト失敗確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py::test_save_memory_inserts_and_returns_id tests/unit/storage/test_prisma_adapter.py::test_save_memory_raises_duplicate_content -v
```
Expected: FAIL (`AttributeError: 'PrismaStorageAdapter' object has no attribute 'save_memory'`)。

- [ ] **Step 4: `PrismaStorageAdapter` に `save_memory` を実装**

`src/context_store/storage/prisma.py` の `PrismaStorageAdapter` クラスに以下を追加:

```python
    async def save_memory(self, memory: "Memory") -> str:  # type: ignore[name-defined]
        """Persist a memory and return its string ID."""
        import json

        from prisma.errors import UniqueViolationError  # type: ignore[import-not-found]

        from context_store.models.memory import Memory  # noqa: F401

        embedding_str = _embedding_to_pg(memory.embedding)
        content_hash = _content_hash(memory.content)

        sql = """
            INSERT INTO memories (
                id, content, memory_type, source_type, source_metadata,
                embedding, semantic_relevance, importance_score, access_count,
                last_accessed_at, created_at, updated_at, archived_at,
                tags, project, content_hash
            ) VALUES (
                $1, $2, $3, $4, $5::jsonb,
                $6::vector, $7, $8, $9,
                $10, $11, $12, $13,
                $14, $15, $16
            )
            RETURNING id
        """

        try:
            row = await self._client.query_first_raw(
                sql,
                memory.id,
                memory.content,
                memory.memory_type.value,
                memory.source_type.value,
                json.dumps(memory.source_metadata),
                embedding_str,
                memory.semantic_relevance,
                memory.importance_score,
                memory.access_count,
                memory.last_accessed_at,
                memory.created_at,
                memory.updated_at,
                memory.archived_at,
                memory.tags,
                memory.project,
                content_hash,
            )
        except UniqueViolationError as e:
            raise StorageError(
                message=str(e),
                code="DUPLICATE_CONTENT",
                recoverable=False,
            ) from e
        if row is None:
            raise StorageError(
                message="INSERT RETURNING returned no row",
                code="STORAGE_ERROR",
                recoverable=False,
            )
        return str(row["id"])
```

- [ ] **Step 5: テスト PASS 確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: 8 件 (累積) すべて PASS (Task 2.1 の 6 件 + 本タスクの 2 件)。

- [ ] **Step 6: 静的解析 (Devcontainer 内)**

```bash
uv run ruff check src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: エラーなし。

- [ ] **Step 7: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): implement PrismaStorageAdapter.save_memory"
git push -u origin feature/phase2-task2_save_memory
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task2_save_memory \
  --draft \
  --title "[Phase2/Task2] PrismaStorageAdapter.save_memory" \
  --body "## Summary
- save_memory を `query_first_raw` ベースで実装
- UniqueViolationError → StorageError(DUPLICATE_CONTENT) マッピング

## Test plan
- [ ] save_memory 系テスト 2 件が PASS"
```

---

### Task 2.3: `get_memory` + `get_memories_batch` (チャンク分割境界含む)

**派生元:** `feature/phase2-task2_save_memory` (直前 Task 派生 — 同一ファイル拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py`
- Modify: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task2_save_memory
git checkout -b feature/phase2-task3_get_memory_batch
```

- [ ] **Step 2: 失敗するテストを追加 (設計書 8.2 (b) の境界ケース全 6 件)**

`tests/unit/storage/test_prisma_adapter.py` に追加:

```python
@pytest.mark.asyncio
async def test_get_memory_returns_none_when_missing(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value=None)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memory("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_get_memories_batch_empty_list_returns_empty(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memories_batch([])
    assert result == []
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "n_ids, expected_chunk_sizes",
    [
        (249, [249]),
        (250, [250]),
        (251, [250, 1]),
        (499, [250, 249]),
        (500, [250, 250]),
        (501, [250, 250, 1]),
    ],
)
async def test_get_memories_batch_chunk_boundary(
    mock_prisma, n_ids: int, expected_chunk_sizes: list[int]
):
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(n_ids)]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    assert mock_prisma.query_raw.await_count == len(expected_chunk_sizes)
    actual_sizes = [
        len(call.args[1]) for call in mock_prisma.query_raw.await_args_list
    ]
    assert actual_sizes == expected_chunk_sizes


@pytest.mark.asyncio
async def test_get_memories_batch_preserves_input_order(mock_prisma):
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(3)]

    def _record(memory_id: str) -> dict[str, Any]:
        from datetime import datetime, timezone

        return {
            "id": memory_id,
            "content": f"content-{memory_id}",
            "memory_type": "semantic",
            "source_type": "manual",
            "source_metadata": {},
            "embedding": [0.1],
            "semantic_relevance": 0.5,
            "importance_score": 0.5,
            "access_count": 0,
            "last_accessed_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "archived_at": None,
            "tags": [],
            "project": None,
        }

    # 返却順序を逆にしても、入力 ids の順序が保たれる
    mock_prisma.query_raw = AsyncMock(
        return_value=[_record(ids[2]), _record(ids[0]), _record(ids[1])]
    )

    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_memories_batch(ids)
    assert [m.id for m in result] == ids


@pytest.mark.asyncio
async def test_get_memories_batch_skips_invalid_uuid(mock_prisma):
    from uuid import uuid4

    valid = str(uuid4())
    ids = ["not-a-uuid", valid, "also-bad"]
    mock_prisma.query_raw = AsyncMock(return_value=[])

    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)

    passed_ids = mock_prisma.query_raw.await_args.args[1]
    assert passed_ids == [valid]
```

- [ ] **Step 3: テスト失敗確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: 上記の新規テストが FAIL。

- [ ] **Step 4: `get_memory` + `get_memories_batch` を実装**

`PrismaStorageAdapter` に追加:

```python
    async def get_memory(self, memory_id: str) -> "Memory | None":  # type: ignore[name-defined]
        """Retrieve a memory by ID."""
        sql = "SELECT * FROM memories WHERE id = $1"
        row = await self._client.query_first_raw(sql, memory_id)
        if row is None:
            return None
        return _record_to_memory(row)

    async def get_memories_batch(self, memory_ids: list[str]) -> "list[Memory]":  # type: ignore[name-defined]
        """Retrieve multiple memories by ID, preserving input order.

        Accelerate の 5MB 応答上限への対策として、チャンクサイズ
        ``PRISMA_BATCH_FETCH_CHUNK_SIZE`` で分割実行する。
        """
        from uuid import UUID

        if not memory_ids:
            return []

        cleaned: list[str] = []
        for memory_id in memory_ids:
            try:
                cleaned.append(str(UUID(str(memory_id))))
            except (TypeError, ValueError, AttributeError):
                continue
        if not cleaned:
            return []

        sql = "SELECT * FROM memories WHERE id = ANY($1::uuid[])"
        memory_map: dict[str, Any] = {}
        for offset in range(0, len(cleaned), PRISMA_BATCH_FETCH_CHUNK_SIZE):
            chunk = cleaned[offset : offset + PRISMA_BATCH_FETCH_CHUNK_SIZE]
            rows = await self._client.query_raw(sql, chunk)
            for row in rows:
                memory_map[str(row["id"])] = _record_to_memory(row)

        results = []
        for memory_id in memory_ids:
            try:
                norm_id = str(UUID(str(memory_id)))
            except (TypeError, ValueError, AttributeError):
                continue
            memory = memory_map.get(norm_id)
            if memory is not None:
                results.append(memory)
        return results
```

- [ ] **Step 5: テスト PASS 確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: 全 PASS。

- [ ] **Step 6: 静的解析 (Devcontainer 内)**

```bash
uv run ruff check src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: エラーなし。

- [ ] **Step 7: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): implement get_memory and get_memories_batch with chunking"
git push -u origin feature/phase2-task3_get_memory_batch
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task3_get_memory_batch \
  --draft \
  --title "[Phase2/Task3] PrismaStorageAdapter: get_memory + chunked get_memories_batch" \
  --body "## Summary
- get_memory を query_first_raw で実装
- get_memories_batch を 250 件チャンク分割 + 入力順保持で実装
- 不正 UUID 文字列はスキップ

## Test plan
- [ ] チャンク境界 6 ケース (249/250/251/499/500/501) PASS
- [ ] 入力順保持テスト PASS
- [ ] 不正 UUID スキップテスト PASS"
```

---

### Task 2.4: `update_memory` + `delete_memory` + `increment_memory_access_count`

**派生元:** `feature/phase2-task3_get_memory_batch` (直前 Task 派生 — 同一ファイル拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py`
- Modify: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task3_get_memory_batch
git checkout -b feature/phase2-task4_update_delete_increment
```

- [ ] **Step 2: 失敗するテストを追加**

```python
@pytest.mark.asyncio
async def test_delete_memory_returns_true_when_deleted(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.delete_memory("some-id") is True


@pytest.mark.asyncio
async def test_delete_memory_returns_false_when_not_found(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=0)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.delete_memory("missing-id") is False


@pytest.mark.asyncio
async def test_update_memory_returns_false_for_empty_updates(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.update_memory("id", {}) is False
    mock_prisma.execute_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_memory_updates_content_with_hash(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.update_memory("id-1", {"content": "new content"})
    assert result is True
    sql = mock_prisma.execute_raw.await_args.args[0]
    assert "content_hash" in sql


@pytest.mark.asyncio
async def test_increment_memory_access_count_returns_true(mock_prisma):
    mock_prisma.execute_raw = AsyncMock(return_value=1)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    assert await adapter.increment_memory_access_count("id-1") is True
```

- [ ] **Step 3: テスト失敗確認**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
```
Expected: 新規 5 件 FAIL。

- [ ] **Step 4: メソッドを実装**

`PrismaStorageAdapter` に追加 (既存 `PostgresStorageAdapter.delete_memory` / `update_memory` / `increment_memory_access_count` の SQL を物理的にコピー、`conn.execute` を `self._client.execute_raw` に置換、戻り値判定を `affected >= 1` に変更):

```python
    async def delete_memory(self, memory_id: str) -> bool:
        sql = "DELETE FROM memories WHERE id = $1"
        affected = await self._client.execute_raw(sql, memory_id)
        return int(affected) >= 1

    async def update_memory(self, memory_id: str, updates: dict[str, Any]) -> bool:
        import json

        if not updates:
            return False

        allowed_columns = {
            "content",
            "memory_type",
            "source_type",
            "source_metadata",
            "embedding",
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
            if col == "content":
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}")
                params.append(_content_hash(str(val)))
                set_parts.append(f"content_hash = ${len(params)}")
                continue
            if col == "embedding":
                val = _embedding_to_pg(val) if isinstance(val, list) else val
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}::vector")
                continue
            if col == "source_metadata" and isinstance(val, dict):
                val = json.dumps(val)
                params.append(val)
                set_parts.append(f"{col} = ${len(params)}::jsonb")
                continue
            params.append(val)
            set_parts.append(f"{col} = ${len(params)}")

        if not set_parts:
            return False

        params.append(memory_id)
        sql = " ".join(
            [
                "UPDATE memories",
                f"SET {', '.join(set_parts)}",
                f"WHERE id = ${len(params)}",
            ]
        )
        affected = await self._client.execute_raw(sql, *params)
        return int(affected) >= 1

    async def increment_memory_access_count(self, memory_id: str) -> bool:
        sql = (
            "UPDATE memories "
            "SET access_count = access_count + 1, "
            "    last_accessed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE id = $1"
        )
        affected = await self._client.execute_raw(sql, memory_id)
        return int(affected) >= 1
```

- [ ] **Step 5: テスト PASS 確認**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
uv run ruff check src/context_store/storage/prisma.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: 全 PASS、lint/mypy エラーなし。

- [ ] **Step 6: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): implement update_memory, delete_memory, increment_access_count"
git push -u origin feature/phase2-task4_update_delete_increment
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task4_update_delete_increment \
  --draft \
  --title "[Phase2/Task4] PrismaStorageAdapter: update/delete/increment" \
  --body "## Summary
- update_memory: 動的 SET 構築、content 更新時は content_hash も更新
- delete_memory / increment_memory_access_count: execute_raw の戻り値 (affected rows >= 1) で判定

## Test plan
- [ ] update/delete/increment テスト 5 件 PASS"
```

---

### Task 2.5: `vector_search` + `keyword_search` (`top_k` クランプ含む)

**派生元:** `feature/phase2-task4_update_delete_increment` (直前 Task 派生 — 同一ファイル拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py`
- Modify: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task4_update_delete_increment
git checkout -b feature/phase2-task5_search_methods
```

- [ ] **Step 2: 失敗するテストを追加 (設計書 8.2 (a) の `top_k` クランプケース全件)**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_top_k, expected_effective_top_k, expects_warning",
    [
        (10, 10, False),
        (200, 200, False),
        (500, 200, True),  # クランプ
    ],
)
async def test_vector_search_top_k_clamp(
    mock_prisma, caplog, input_top_k, expected_effective_top_k, expects_warning
):
    import logging

    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with caplog.at_level(logging.WARNING, logger="context_store.storage.prisma"):
        await adapter.vector_search(embedding=[0.1] * 768, top_k=input_top_k)

    params = mock_prisma.query_raw.await_args.args
    assert expected_effective_top_k in params
    if expects_warning:
        assert any("clamped" in r.message.lower() for r in caplog.records)
    else:
        assert not any("clamped" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_top_k", [0, -1])
async def test_vector_search_rejects_non_positive_top_k(mock_prisma, invalid_top_k):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.vector_search(embedding=[0.1] * 768, top_k=invalid_top_k)
    assert exc_info.value.code == "INVALID_PARAMETER"
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_vector_search_empty_embedding_returns_empty(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.vector_search(embedding=[], top_k=10)
    assert result == []
    mock_prisma.query_raw.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyword_search_top_k_clamp(mock_prisma, caplog):
    import logging

    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with caplog.at_level(logging.WARNING, logger="context_store.storage.prisma"):
        await adapter.keyword_search(query="test", top_k=300)
    params = mock_prisma.query_raw.await_args.args
    assert 200 in params
    assert any("clamped" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 3: テスト失敗確認**

- [ ] **Step 4: `vector_search` + `keyword_search` を実装 (クランプヘルパー含む)**

`PrismaStorageAdapter` に追加:

```python
    def _clamp_top_k(self, top_k: int, method_name: str) -> int:
        """Validate and clamp top_k to PRISMA_MAX_TOP_K."""
        if top_k <= 0:
            raise StorageError(
                message=f"top_k must be >= 1 (got {top_k})",
                code="INVALID_PARAMETER",
                recoverable=False,
            )
        if top_k > PRISMA_MAX_TOP_K:
            logger.warning(
                "%s: top_k clamped %d -> %d (PRISMA_MAX_TOP_K)",
                method_name,
                top_k,
                PRISMA_MAX_TOP_K,
            )
            return PRISMA_MAX_TOP_K
        return top_k

    async def vector_search(
        self,
        embedding: list[float],
        top_k: int,
        project: str | None = None,
    ) -> "list[ScoredMemory]":  # type: ignore[name-defined]
        from context_store.models.memory import MemorySource, ScoredMemory

        embedding_str = _embedding_to_pg(embedding)
        if embedding_str is None:
            return []

        effective_top_k = self._clamp_top_k(top_k, "vector_search")

        if project is not None:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL AND project = $3 "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, embedding_str, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1 - (embedding <=> $1::vector) AS score "
                "FROM memories "
                "WHERE archived_at IS NULL AND embedding IS NOT NULL "
                "ORDER BY embedding <=> $1::vector "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, embedding_str, effective_top_k)

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.VECTOR,
            )
            for row in rows
        ]

    async def keyword_search(
        self,
        query: str,
        top_k: int,
        project: str | None = None,
    ) -> "list[ScoredMemory]":  # type: ignore[name-defined]
        from context_store.models.memory import MemorySource, ScoredMemory

        effective_top_k = self._clamp_top_k(top_k, "keyword_search")
        like_query = f"%{query}%"

        if project is not None:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 AND project = $3 "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, like_query, effective_top_k, project)
        else:
            sql = (
                "SELECT *, 1.0 AS score FROM memories "
                "WHERE archived_at IS NULL AND content LIKE $1 "
                "LIMIT $2"
            )
            rows = await self._client.query_raw(sql, like_query, effective_top_k)

        return [
            ScoredMemory(
                memory=_record_to_memory(row),
                score=float(row["score"]),
                source=MemorySource.KEYWORD,
            )
            for row in rows
        ]
```

- [ ] **Step 5: テスト PASS 確認**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
uv run ruff check src/context_store/storage/prisma.py
uv run mypy src/context_store/storage/prisma.py
```

- [ ] **Step 6: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): implement vector_search and keyword_search with top_k clamp"
git push -u origin feature/phase2-task5_search_methods
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task5_search_methods \
  --draft \
  --title "[Phase2/Task5] PrismaStorageAdapter: vector_search + keyword_search with top_k clamp" \
  --body "## Summary
- vector_search / keyword_search を query_raw で実装
- _clamp_top_k ヘルパーで PRISMA_MAX_TOP_K=200 にクランプ、warning ログ出力
- top_k <= 0 は INVALID_PARAMETER

## Test plan
- [ ] クランプ 3 ケース (10/200/500) PASS
- [ ] top_k=0, -1 で INVALID_PARAMETER 送出"
```

---

### Task 2.6: `list_by_filter` + `count_by_filter` + `list_projects` + `get_vector_dimension`

**派生元:** `feature/phase2-task5_search_methods` (直前 Task 派生 — 同一ファイル拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py`
- Modify: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task5_search_methods
git checkout -b feature/phase2-task6_list_count_projects_dimension
```

- [ ] **Step 2: 失敗するテストを追加**

`tests/unit/storage/test_prisma_adapter.py` に追加:

```python
from context_store.storage.protocols import MemoryFilters


@pytest.mark.asyncio
async def test_list_by_filter_invokes_query_raw(mock_prisma):
    mock_prisma.query_raw = AsyncMock(return_value=[])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.list_by_filter(MemoryFilters(project="proj-a"))
    sql = mock_prisma.query_raw.await_args.args[0]
    assert "SELECT * FROM memories" in sql
    assert "project = $1" in sql


@pytest.mark.asyncio
async def test_list_by_filter_invalid_sort_column_raises(mock_prisma):
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.list_by_filter(MemoryFilters(order_by="malicious_col"))
    assert exc_info.value.code == "INVALID_PARAMETER"


@pytest.mark.asyncio
async def test_count_by_filter_returns_int(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value={"count": 42})
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.count_by_filter(MemoryFilters())
    assert result == 42


@pytest.mark.asyncio
async def test_list_projects_returns_distinct_projects(mock_prisma):
    mock_prisma.query_raw = AsyncMock(
        return_value=[{"project": "a"}, {"project": "b"}]
    )
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.list_projects()
    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_int(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value={"vector_dims": 768})
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_vector_dimension()
    assert result == 768


@pytest.mark.asyncio
async def test_get_vector_dimension_returns_none_when_no_data(mock_prisma):
    mock_prisma.query_first_raw = AsyncMock(return_value=None)
    adapter = PrismaStorageAdapter(client=mock_prisma)
    result = await adapter.get_vector_dimension()
    assert result is None
```

- [ ] **Step 3: テスト失敗確認**

- [ ] **Step 4: `list_by_filter` / `count_by_filter` / `list_projects` / `get_vector_dimension` を実装**

`PostgresStorageAdapter._build_where_clause` をそのまま `prisma.py` の `PrismaStorageAdapter` 内に物理的にコピー (`ALLOWED_SORT_COLUMNS` の import を忘れずに)。`conn.fetch` → `self._client.query_raw`、`conn.fetchval` → `self._client.query_first_raw` に置換する。

```python
from context_store.storage.protocols import ALLOWED_SORT_COLUMNS, MemoryFilters  # 既存 import に追加
```

`PrismaStorageAdapter` に以下を追加 (`_build_where_clause` 含む):

```python
    def _build_where_clause(self, filters: "MemoryFilters") -> tuple[str, list[Any]]:
        # PostgresStorageAdapter._build_where_clause と完全に同一実装
        # (上記から物理的にコピー)
        ...

    async def list_by_filter(self, filters: "MemoryFilters") -> "list[Memory]":  # type: ignore[name-defined]
        # PostgresStorageAdapter.list_by_filter と SQL/ロジック同一
        # conn.fetch → self._client.query_raw に置換
        where_clause, params = self._build_where_clause(filters)
        # ... ORDER BY / LIMIT / OFFSET 構築は PostgresStorageAdapter と同一 ...
        rows = await self._client.query_raw(sql, *params)
        return [_record_to_memory(row) for row in rows]

    async def count_by_filter(self, filters: "MemoryFilters") -> int:
        where_clause, params = self._build_where_clause(filters)
        sql = " ".join(
            part for part in ["SELECT COUNT(*) AS count", "FROM memories", where_clause] if part
        ).strip()
        row = await self._client.query_first_raw(sql, *params)
        if row is None:
            return 0
        return int(row.get("count", 0) or 0)

    async def list_projects(self) -> list[str]:
        sql = "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL AND project != ''"
        rows = await self._client.query_raw(sql)
        return [str(row["project"]) for row in rows]

    async def get_vector_dimension(self) -> int | None:
        sql = (
            "SELECT vector_dims(embedding) AS vector_dims "
            "FROM memories WHERE embedding IS NOT NULL LIMIT 1"
        )
        row = await self._client.query_first_raw(sql)
        if row is None or row.get("vector_dims") is None:
            return None
        return int(row["vector_dims"])
```

> **Note (DRY):** `_build_where_clause` は `PostgresStorageAdapter` と完全同一のロジックだが、設計書 4.4 で「YAGNI の観点で SQL 共有モジュール抽出は別タスク」とされているため、本タスクでは物理コピーで対応する。将来別タスクで共通化する。

- [ ] **Step 5: テスト PASS 確認**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
uv run ruff check src/context_store/storage/prisma.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: 全 PASS、lint/mypy エラーなし。

- [ ] **Step 6: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): implement list/count/projects/get_vector_dimension"
git push -u origin feature/phase2-task6_list_count_projects_dimension
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task6_list_count_projects_dimension \
  --draft \
  --title "[Phase2/Task6] PrismaStorageAdapter: list/count/projects/dimension" \
  --body "## Summary
- list_by_filter / count_by_filter / list_projects / get_vector_dimension を実装
- _build_where_clause は PostgresStorageAdapter から物理コピー (共通化は別タスク)

## Test plan
- [ ] list/count/projects/dimension テスト 6 件 PASS"
```

---

### Task 2.7: エラーマッピング + Accelerate フェールセーフ (タイムアウト / 応答サイズ縮小リトライ)

**派生元:** `feature/phase2-task6_list_count_projects_dimension` (直前 Task 派生 — 同一ファイル拡張)

**Files:**
- Modify: `src/context_store/storage/prisma.py`
- Modify: `tests/unit/storage/test_prisma_adapter.py`

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2-task6_list_count_projects_dimension
git checkout -b feature/phase2-task7_error_mapping_fallback
```

- [ ] **Step 2: 失敗するテストを追加 (設計書 8.2 (c) (d) の全フォールバックケース)**

```python
def _prisma_error(code: str):
    """Construct a prisma.errors.PrismaError with a given code."""
    from prisma.errors import PrismaError  # type: ignore[import-not-found]

    err = PrismaError("simulated")
    err.code = code  # type: ignore[attr-defined]
    return err


@pytest.mark.asyncio
async def test_vector_search_timeout_retries_with_half_top_k(mock_prisma):
    # 1 回目: timeout, 2 回目: 成功
    mock_prisma.query_raw = AsyncMock(side_effect=[_prisma_error("P2024"), []])
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.vector_search(embedding=[0.1] * 768, top_k=100)
    assert mock_prisma.query_raw.await_count == 2
    second_call_params = mock_prisma.query_raw.await_args_list[1].args
    assert 50 in second_call_params  # top_k=100 -> 50


@pytest.mark.asyncio
async def test_vector_search_timeout_after_retry_raises_storage_timeout(mock_prisma):
    mock_prisma.query_raw = AsyncMock(
        side_effect=[_prisma_error("P2024"), _prisma_error("P2024")]
    )
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.vector_search(embedding=[0.1] * 768, top_k=100)
    assert exc_info.value.code == "STORAGE_TIMEOUT"
    assert exc_info.value.recoverable is True
    assert mock_prisma.query_raw.await_count == 2


@pytest.mark.asyncio
async def test_vector_search_top_k_1_no_third_retry(mock_prisma):
    mock_prisma.query_raw = AsyncMock(
        side_effect=[_prisma_error("P2024"), _prisma_error("P2024")]
    )
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.vector_search(embedding=[0.1] * 768, top_k=1)
    assert exc_info.value.code == "STORAGE_TIMEOUT"
    # max(1, 1//2) = 1 でリトライ。それでも失敗 → 計 2 回のみ
    assert mock_prisma.query_raw.await_count == 2


@pytest.mark.asyncio
async def test_vector_search_payload_too_large_maps_to_payload_code(mock_prisma):
    mock_prisma.query_raw = AsyncMock(
        side_effect=[_prisma_error("P6009"), _prisma_error("P6009")]
    )
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.vector_search(embedding=[0.1] * 768, top_k=100)
    assert exc_info.value.code == "STORAGE_PAYLOAD_TOO_LARGE"
    assert exc_info.value.recoverable is True


@pytest.mark.asyncio
async def test_list_by_filter_timeout_no_retry(mock_prisma):
    mock_prisma.query_raw = AsyncMock(side_effect=_prisma_error("P2024"))
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.list_by_filter(MemoryFilters())
    assert exc_info.value.code == "STORAGE_TIMEOUT"
    assert exc_info.value.recoverable is True
    assert mock_prisma.query_raw.await_count == 1


@pytest.mark.asyncio
async def test_save_memory_timeout_no_retry(mock_prisma):
    memory = _build_memory("x")
    mock_prisma.query_first_raw = AsyncMock(side_effect=_prisma_error("P2024"))
    adapter = PrismaStorageAdapter(client=mock_prisma)
    with pytest.raises(StorageError) as exc_info:
        await adapter.save_memory(memory)
    assert exc_info.value.code == "STORAGE_TIMEOUT"
    assert exc_info.value.recoverable is True
    assert mock_prisma.query_first_raw.await_count == 1


@pytest.mark.asyncio
async def test_get_memories_batch_chunk_retry(mock_prisma):
    """1 chunk (250 件) の P2024 → 125 件 × 2 にリトライして成功。"""
    from uuid import uuid4

    ids = [str(uuid4()) for _ in range(600)]
    # 1: chunk 1 (250) timeout, 2-3: 125 + 125 成功, 4: chunk 2 (250) 成功, 5: chunk 3 (100) 成功
    mock_prisma.query_raw = AsyncMock(
        side_effect=[_prisma_error("P2024"), [], [], [], []]
    )
    adapter = PrismaStorageAdapter(client=mock_prisma)
    await adapter.get_memories_batch(ids)
    assert mock_prisma.query_raw.await_count == 5
```

- [ ] **Step 3: テスト失敗確認**

- [ ] **Step 4: エラーマッピング + フォールバックヘルパーを実装**

`PrismaStorageAdapter` に追加し、既存メソッド (save_memory, vector_search, keyword_search, get_memories_batch, list_by_filter 等) をフォールバック対応に書き換える:

```python
    @staticmethod
    def _classify_prisma_error(exc: Exception) -> tuple[str, bool] | None:
        """Return (storage_code, is_fallback_candidate) for known Prisma errors.

        Returns None if not a recognized retryable error.
        """
        from prisma.errors import PrismaError  # type: ignore[import-not-found]

        if not isinstance(exc, PrismaError):
            return None
        code = getattr(exc, "code", None)
        if code in PRISMA_TIMEOUT_CODES:
            return ("STORAGE_TIMEOUT", True)
        if code in PRISMA_PAYLOAD_TOO_LARGE_CODES:
            return ("STORAGE_PAYLOAD_TOO_LARGE", True)
        return None

    async def _search_with_fallback(
        self, sql_builder, top_k: int
    ) -> list[Any]:
        """Execute a search with one-shot retry (top_k halved) on timeout/payload-too-large.

        sql_builder(top_k: int) -> Awaitable[list[dict]] を期待する。
        """
        try:
            return await sql_builder(top_k)
        except Exception as exc:
            classified = self._classify_prisma_error(exc)
            if classified is None:
                raise self._map_to_storage_error(exc) from exc
            storage_code, _ = classified
            new_top_k = max(1, top_k // 2)
            try:
                return await sql_builder(new_top_k)
            except Exception as retry_exc:
                raise StorageError(
                    message=f"{storage_code} after retry (top_k={top_k} -> {new_top_k})",
                    code=storage_code,
                    recoverable=True,
                ) from retry_exc

    @staticmethod
    def _map_to_storage_error(exc: Exception) -> StorageError:
        """Map an arbitrary Prisma exception to StorageError (no retry)."""
        from prisma.errors import (  # type: ignore[import-not-found]
            PrismaError,
            RawQueryError,
            UniqueViolationError,
        )

        if isinstance(exc, UniqueViolationError):
            return StorageError(
                message=str(exc), code="DUPLICATE_CONTENT", recoverable=False
            )
        if isinstance(exc, RawQueryError):
            return StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False)
        if isinstance(exc, PrismaError):
            code = getattr(exc, "code", None)
            if code in PRISMA_TIMEOUT_CODES:
                return StorageError(
                    message=str(exc), code="STORAGE_TIMEOUT", recoverable=True
                )
            if code in PRISMA_PAYLOAD_TOO_LARGE_CODES:
                return StorageError(
                    message=str(exc),
                    code="STORAGE_PAYLOAD_TOO_LARGE",
                    recoverable=True,
                )
            return StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=True)
        return StorageError(message=str(exc), code="STORAGE_ERROR", recoverable=False)
```

そして既存の `vector_search` / `keyword_search` 内の `await self._client.query_raw(...)` を `_search_with_fallback` 経由に書き換える。`save_memory` / `update_memory` / `delete_memory` / `increment_memory_access_count` / `list_by_filter` / `count_by_filter` / `list_projects` / `get_vector_dimension` は内部リトライしない (例外を `_map_to_storage_error` で包んで送出)。

`get_memories_batch` はチャンク単位でフォールバック (timeout/payload-too-large → そのチャンクのみ半分に分割)。

具体的な書き換え方針:
- 各 try ブロックで `except Exception as exc: raise self._map_to_storage_error(exc) from exc` を使う。
- `vector_search` / `keyword_search` は `_search_with_fallback` を経由。
- `get_memories_batch` のチャンクループでは、各 `query_raw` 呼び出しを try/except で囲み、Prisma エラーかつ fallback 候補なら半分に分けて再試行 (1 回のみ)。

> **TDD ループ:** Step 4 のコードを実装したら Step 2 のテストが全 PASS することを Devcontainer 内で確認する。テストが期待通り動くまで実装を調整する。

- [ ] **Step 5: テスト PASS 確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_prisma_adapter.py -v
uv run ruff check src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
uv run mypy src/context_store/storage/prisma.py
```
Expected: 全 PASS、lint/mypy エラーなし。

- [ ] **Step 6: 全テスト回帰なしを確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit -v
```
Expected: 既存テスト含めて全 PASS。

- [ ] **Step 7: コミット & Draft PR**

```bash
git add src/context_store/storage/prisma.py tests/unit/storage/test_prisma_adapter.py
git commit -m "feat(storage): error mapping and Accelerate timeout/size fallback"
git push -u origin feature/phase2-task7_error_mapping_fallback
gh pr create \
  --base feature/phase2_prisma_adapter__base \
  --head feature/phase2-task7_error_mapping_fallback \
  --draft \
  --title "[Phase2/Task7] PrismaStorageAdapter: error mapping + Accelerate fallback" \
  --body "$(cat <<'EOF'
## Summary
- _classify_prisma_error / _map_to_storage_error / _search_with_fallback ヘルパー追加
- vector_search / keyword_search: P2024/P2028/P6004/P6009 で top_k を半分にして 1 回リトライ
- get_memories_batch: チャンク単位で同様にリトライ (250→125 分割)
- list_by_filter / count_by_filter / save / update / delete / increment: リトライなし、即 StorageError 送出
- STORAGE_TIMEOUT と STORAGE_PAYLOAD_TOO_LARGE を別コードとして区別 (recoverable=True 共通)

## Test plan
- [ ] フォールバック 7 ケース (timeout retry success / retry fail / top_k=1 no third / payload too large / list no retry / save no retry / batch chunk retry) PASS
- [ ] tests/unit 全体に回帰なし
EOF
)"
```

---

### Phase 2 完了アクション

- [ ] Phase 2 の Task 2.1〜2.7 の Draft PR レビュー完了。
- [ ] レビューア承認後、最終 Task ブランチ (`feature/phase2-task7_error_mapping_fallback`) のコミットを `feature/phase2_prisma_adapter__base` に取り込む (rebase merge または cherry-pick)。
- [ ] Devcontainer 内で全テストと静的解析を再実行:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v --cov=src/context_store
```

- [ ] `master` をターゲットとした Phase 2 Draft PR を作成:

```bash
gh pr create \
  --base master \
  --head feature/phase2_prisma_adapter__base \
  --draft \
  --title "[Phase2] PrismaStorageAdapter implementation" \
  --body "$(cat <<'EOF'
## Summary
- PrismaStorageAdapter の全 StorageAdapter プロトコルメソッドを実装
- Accelerate 制約に対するフェールセーフ (top_k clamp / chunk split / one-shot retry) を内蔵
- prisma.errors → StorageError マッピング (DUPLICATE_CONTENT / STORAGE_TIMEOUT / STORAGE_PAYLOAD_TOO_LARGE / STORAGE_ERROR)

## Test plan
- [ ] tests/unit/storage/test_prisma_adapter.py 全 PASS
- [ ] tests/unit 全体回帰なし
- [ ] mypy / ruff エラーなし
EOF
)"
```

---

## Phase 3: Factory 統合

**前提:** Phase 2 の PR が `master` にマージ済みであること。

**Phase Base ブランチ作成:**

```bash
git checkout master
git pull --ff-only origin master
git checkout -b feature/phase3_prisma_factory__base
git push -u origin feature/phase3_prisma_factory__base
```

---

### Task 3.1: Factory に `prisma` 分岐を追加 + バリデーション二重化

**派生元:** `feature/phase3_prisma_factory__base` (Base 派生 — 単独ファイル変更、他タスク無依存)

**Files:**
- Modify: `src/context_store/storage/factory.py:291-309` (`_create_storage_adapter` に分岐)
- Modify: `src/context_store/storage/factory.py:312-349` (`_create_graph_adapter` で prisma+graph を拒否)
- Modify: `tests/unit/storage/test_factory.py` (既存ファイルがあれば追記、なければ作成)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase3_prisma_factory__base
git checkout -b feature/phase3-task1_factory_prisma_branch
```

- [ ] **Step 2: 失敗するテストを追加**

`tests/unit/storage/test_factory.py` に以下を追加 (ファイルが無ければ新規作成):

```python
"""Tests for factory.py prisma branch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_store.config import Settings
from context_store.storage.factory import _create_graph_adapter, _create_storage_adapter


def _prisma_settings(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "prisma")
    monkeypatch.setenv(
        "PRISMA_DATABASE_URL", "prisma://accelerate.prisma-data.net/?api_key=test"
    )
    return Settings()


@pytest.mark.asyncio
async def test_create_storage_adapter_prisma_branch(monkeypatch):
    settings = _prisma_settings(monkeypatch)
    fake_adapter = object()
    with patch(
        "context_store.storage.prisma.PrismaStorageAdapter.create",
        new=AsyncMock(return_value=fake_adapter),
    ) as create_mock:
        result = await _create_storage_adapter(settings, read_only=False)
        assert result is fake_adapter
        create_mock.assert_awaited_once_with(settings)


@pytest.mark.asyncio
async def test_create_storage_adapter_prisma_read_only_raises(monkeypatch):
    settings = _prisma_settings(monkeypatch)
    with pytest.raises(NotImplementedError):
        await _create_storage_adapter(settings, read_only=True)


@pytest.mark.asyncio
async def test_create_graph_adapter_prisma_raises_value_error(monkeypatch):
    # Settings バリデータで graph_enabled=true は弾かれるため、
    # ここでは Settings を bypass して factory 単体の防御を確認する
    settings = _prisma_settings(monkeypatch)
    # graph_enabled を強制的に True に上書き (post-init validation bypass のため
    # model_construct を使う)
    forced = Settings.model_construct(**{**settings.model_dump(), "graph_enabled": True})
    with pytest.raises(ValueError, match="prisma"):
        await _create_graph_adapter(forced, read_only=False)
```

- [ ] **Step 3: テスト失敗確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_factory.py -v -k "prisma"
```
Expected: 3 件すべて FAIL (`Unsupported storage_backend: 'prisma'`)。

- [ ] **Step 4: `_create_storage_adapter` に分岐を追加**

`src/context_store/storage/factory.py:291` 付近の `_create_storage_adapter` を編集し、`postgres` 分岐の直後 (return 前) に prisma 分岐を追加:

```python
    if settings.storage_backend == "prisma":
        from context_store.storage.prisma import PrismaStorageAdapter

        if read_only:
            raise NotImplementedError(
                "read_only mode for prisma backend is not yet supported"
            )
        return await PrismaStorageAdapter.create(settings)
```

- [ ] **Step 5: `_create_graph_adapter` に prisma 拒否を追加**

`src/context_store/storage/factory.py:312-349` の最終 `raise ValueError(...)` の直前に追加:

```python
    if settings.storage_backend == "prisma":
        raise ValueError(
            "Graph adapter is not supported for storage_backend=prisma "
            "(Neo4j Bolt cannot be tunneled over HTTPS)"
        )
```

- [ ] **Step 6: テスト PASS 確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit/storage/test_factory.py -v -k "prisma"
```
Expected: 3 件すべて PASS。

- [ ] **Step 7: 既存テスト回帰なしを確認 (Devcontainer 内)**

```bash
uv run pytest tests/unit -v
uv run ruff check src/context_store/storage/factory.py tests/unit/storage/test_factory.py
uv run mypy src/context_store/storage/factory.py
```
Expected: 全 PASS、lint/mypy エラーなし。

- [ ] **Step 8: コミット & Draft PR**

```bash
git add src/context_store/storage/factory.py tests/unit/storage/test_factory.py
git commit -m "feat(factory): wire PrismaStorageAdapter and reject graph+prisma combo"
git push -u origin feature/phase3-task1_factory_prisma_branch
gh pr create \
  --base feature/phase3_prisma_factory__base \
  --head feature/phase3-task1_factory_prisma_branch \
  --draft \
  --title "[Phase3/Task1] Factory: wire PrismaStorageAdapter" \
  --body "$(cat <<'EOF'
## Summary
- _create_storage_adapter に prisma 分岐を追加 (read_only=True は NotImplementedError)
- _create_graph_adapter で prisma backend + graph_enabled を ValueError で拒否 (Settings バリデータと二重化)

## Test plan
- [ ] factory prisma テスト 3 件 PASS
- [ ] tests/unit 全体回帰なし
EOF
)"
```

---

### Phase 3 完了アクション

- [ ] Phase 3 Task のレビュー承認 → ベースに取り込み。
- [ ] Devcontainer 内最終確認:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
uv run pytest tests/unit -v --cov=src/context_store
```

- [ ] `master` をターゲットとした Phase 3 Draft PR を作成:

```bash
gh pr create \
  --base master \
  --head feature/phase3_prisma_factory__base \
  --draft \
  --title "[Phase3] Factory integration for PrismaStorageAdapter" \
  --body "$(cat <<'EOF'
## Summary
- Factory に prisma 分岐を追加し、PrismaStorageAdapter を本番ディスパッチに組込み
- prisma + graph_enabled の組合せを Settings/Factory 両層で拒否

## Test plan
- [ ] tests/unit 全体 PASS
- [ ] CI 全ジョブ green
- [ ] (任意) Devcontainer 内で STORAGE_BACKEND=prisma を設定し orchestrator スモークテストが起動できる
EOF
)"
```

---

## Self-Review チェックリスト

### Spec coverage

- 設計書 §2 (read_only=NotImplementedError, graph禁止) → Task 3.1 ✅
- 設計書 §3.2 (コンポーネント表) → Task 1.1 / 1.2 / 1.3 / 1.4 / 1.5 / 2.1〜2.7 / 3.1 ✅
- 設計書 §4.1 (API マッピング) → Task 2.2〜2.6 ✅
- 設計書 §4.3 (a) top_k ハードリミット → Task 2.5 (`_clamp_top_k`) ✅
- 設計書 §4.3 (b) チャンク分割 → Task 2.3 ✅
- 設計書 §4.3 (c) タイムアウト/サイズ超過フォールバック → Task 2.7 ✅
- 設計書 §5 例外マッピング → Task 2.7 (`_map_to_storage_error`) ✅
- 設計書 §6 `schema.prisma` → Task 1.1 ✅
- 設計書 §7 Devcontainer → Task 1.4 ✅
- 設計書 §8.2 (a) クランプテスト → Task 2.5 (5 ケース) ✅
- 設計書 §8.2 (b) チャンク境界 → Task 2.3 (6 ケース) ✅
- 設計書 §8.2 (c) timeout fallback → Task 2.7 (7 ケース) ✅
- 設計書 §8.2 (d) 5MB / Accelerate コード → Task 2.7 (P6004/P6009 ケース) ✅
- 設計書 §9 Settings → Task 1.3 ✅
- 設計書 §10 Factory → Task 3.1 ✅
- 設計書 §11 ファイル変更サマリと実装順序 → Phase 1〜3 で網羅 ✅
- 設計書 §12 セキュリティ (SecretStr) → Task 1.3 / Task 2.1 (`get_secret_value()` は create 時のみ) ✅

### Placeholder scan

- すべての Step に具体的なコード/コマンド/期待結果を記載 ✅
- 「TBD」「TODO」「実装は後で」等のプレースホルダは存在しない ✅

### Type consistency

- `PRISMA_MAX_TOP_K`, `PRISMA_BATCH_FETCH_CHUNK_SIZE`, `PRISMA_TIMEOUT_CODES`, `PRISMA_PAYLOAD_TOO_LARGE_CODES` は Task 2.1 で定義、Task 2.3 / 2.5 / 2.7 で参照 ✅
- `StorageError.code` 値は設計書 §5 と一致 (`DUPLICATE_CONTENT`, `STORAGE_TIMEOUT`, `STORAGE_PAYLOAD_TOO_LARGE`, `STORAGE_ERROR`, `INVALID_PARAMETER`) ✅
- `PrismaStorageAdapter` のメソッドシグネチャは `PostgresStorageAdapter` と同一 (StorageAdapter プロトコル準拠) ✅

### 既知の挙動 (本計画では意図的に未修正)

- **`keyword_search` の LIKE エスケープ未対応**: Task 2.5 で実装する `keyword_search` は `like_query = f"%{query}%"` の形で `%` / `_` をエスケープしない。これは既存 `PostgresStorageAdapter` (`postgres.py:322`) と同一挙動であり、設計書 §3.1 (PostgresStorageAdapter の SQL 再利用) および §13 (リスクと未解決事項) に明記済み。両アダプター共通の修正は設計書 §4.4 で示す SQL 共有モジュール抽出と併せた別タスクで対応する。本計画では片側だけの修正によるバックエンド切替時の挙動差異を避けるため、現挙動を維持する。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-12-prisma-adapter.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration via `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

**Which approach?**
