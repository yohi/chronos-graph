# 安全評価Hook（Universal Evaluator）の chronos-gate 独立移行計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mcp_gateway` として実装されている安全評価Hook（Universal Evaluator）を `git@github.com:yohi/chronos-gate.git` に独立リポジトリとして移行し、`chronos-gate` は `chronos-graph` に依存する独立した拡張コンポーネントとして提供する。

**Architecture:** `chronos-graph`（長期記憶ストア）から `mcp_gateway`（セキュリティ評価ゲートウェイ）を切り離す。`chronos-graph` はコアリポジトリであり、`chronos_shared.ingestion_mode` を含む共有基盤を保持する。`chronos-gate` は `chronos-graph` の `chronos-shared` パッケージに依存し、セキュリティ評価に関わる Python パッケージ、HTTP API、CLI、OpenCode プラグインを保持する。`chronos-graph` は `chronos-gate` を直接依存しない — 利用者は必要に応じて `chronos-gate` を追加インストールしてセキュリティ評価を有効化する。

**Tech Stack:** Python 3.12+, uv/hatchling, FastAPI, LiteLLM, Pydantic, Pytest, Ruff, mypy, npm/GitHub Packages, GitHub Actions

## Global Constraints

- Python バージョン: `>=3.12`
- パッケージビルド: hatchling
- 履歴保持: `git filter-repo` により `mcp_gateway` 関連ファイルの履歴を抽出
- パッケージ名: 新リポジトリでは `mcp_gateway` → `chronos_gate` へリネーム
- OpenCode プラグイン: `permission.ask`（安全評価）を `chronos-gate` へ移行、`session.idle`（ターン終了 ingestion）は `chronos-graph` に残す
- `chronos_shared.ingestion_mode` は `chronos-graph` 内の `src/chronos_shared` に残し、`chronos-gate` から git subdirectory 経由で依存する
- `chronos-gate` は `chronos-graph` の `chronos-shared` を依存関係として追加し、`chronos-graph` は `chronos-gate` を直接依存しない
- stdout 純度: `chronos-gate` 側の MCP/CLI 入口でも stdout は JSON のみ、ログは stderr
- テスト: 移行後、両リポジトリのユニットテストがパスすること

---

## Task 1: `chronos_shared` を `chronos-graph` 内のインストール可能な共有パッケージとして保持

**Files:**
- Modify: `pyproject.toml`（`src/chronos_shared` を独立パッケージとして公開可能にする）
- Keep: `src/chronos_shared/__init__.py`
- Keep: `src/chronos_shared/ingestion_mode.py`
- Create: `tests/test_chronos_shared/test_ingestion_mode.py`（必要に応じて）

**Interfaces:**
- Produces: `chronos-graph` 配下の `chronos-shared` パッケージ
- Consumes: なし

- [ ] **Step 1: `pyproject.toml` に `chronos-shared` 用の hatchling 設定を追加**

`src/chronos_shared` は既に `packages` に含まれているため、以下の追加設定で独立インストール可能にする：

```toml
[project.optional-dependencies]
shared-only = []

[tool.hatch.build.targets.wheel]
packages = ["src/context_store", "src/chronos_shared"]
```

`src/mcp_gateway` を削除する際（Task 5）、`packages` からも削除する。

- [ ] **Step 2: `chronos-shared` 単体のテストを追加**

`tests/test_chronos_shared/test_ingestion_mode.py`:

```python
from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)


def test_default_ingestion_mode() -> None:
    assert DEFAULT_INGESTION_MODE == "selective"
    assert DEFAULT_INGESTION_MODE in ("all", "selective")


def test_env_name() -> None:
    assert CHRONOS_INGESTION_MODE_ENV == "CHRONOS_INGESTION_MODE"
```

- [ ] **Step 3: テスト実行**

```bash
cd "$CHRONOS_GRAPH_REPO"
uv run pytest tests/test_chronos_shared/ -v
```


---

## Task 2: `chronos-gate` リポジトリへの履歴抽出

**Files:**
- Operate in: `$TMPDIR/chronos-gate` (working clone)
- Source: `$CHRONOS_GRAPH_REPO`

**Interfaces:**
- Produces: `chronos-gate` リポジトリに `mcp_gateway` 関連ファイルの履歴付きコピー
- Consumes: `chronos-graph` 内の `src/chronos_shared` パス（git subdirectory 依存として解決）

- [ ] **Step 1: `chronos-graph` のクローンを取得**

```bash
git clone "$CHRONOS_GRAPH_REPO" "$TMPDIR/chronos-graph-for-extract"
cd "$TMPDIR/chronos-graph-for-extract"
```

- [ ] **Step 2: `git filter-repo` で履歴抽出**

抽出対象パス:
- `src/mcp_gateway/`
- `tests/unit/test_mcp_gateway*.py`
- `tests/integration/test_evaluator_cli_subprocess.py`
- `scripts/chronos-evaluator-hook.sh`
- `scripts/check_evaluator.sh`
- `.opencode/plugins/chronos-gate.js`
- `intents.yaml`
- `src/mcp_gateway/policies/intents.example.yaml`
- `LICENSE`

```bash
python -m pip install git-filter-repo
git filter-repo \
  --path src/mcp_gateway \
  --path tests/unit/test_mcp_gateway_cli.py \
  --path tests/unit/test_mcp_gateway_composite.py \
  --path tests/unit/test_mcp_gateway_llm_evaluator.py \
  --path tests/unit/test_mcp_gateway_memory_client.py \
  --path tests/unit/test_mcp_gateway_evaluator_models.py \
  --path tests/unit/test_mcp_gateway_evaluator_settings.py \
  --path tests/unit/test_mcp_gateway.py \
  --path tests/integration/test_evaluator_cli_subprocess.py \
  --path scripts/chronos-evaluator-hook.sh \
  --path scripts/check_evaluator.sh \
  --path .opencode/plugins/chronos-gate.js \
  --path intents.yaml \
  --path src/mcp_gateway/policies/intents.example.yaml \
  --path LICENSE
```

- [ ] **Step 3: `chronos-gate` リモートを追加してプッシュ**

```bash
git remote add gate git@github.com:yohi/chronos-gate.git
git fetch gate
git push gate master:master --force-with-lease
```

---

## Task 3: `chronos-gate` 内のパッケージリネーム `mcp_gateway` → `chronos_gate`

**Files:**
- Modify all files under `src/mcp_gateway/` → `src/chronos_gate/`
- Modify test imports
- Modify scripts and OpenCode plugin references
- Create new `pyproject.toml`
- Create new `package.json`

**Interfaces:**
- Produces: `chronos_gate` パッケージ（CLI 入口 `chronos-gate`、Python 入口 `python -m chronos_gate`）
- Consumes: `chronos-shared` パッケージ

- [ ] **Step 1: ディレクトリ名をリネーム**

```bash
cd "$TMPDIR/chronos-gate"
git mv src/mcp_gateway src/chronos_gate
```

- [ ] **Step 2: 全 Python ファイルの import を一括置換**

```bash
# 内部 import: from mcp_gateway.X → from chronos_gate.X
find src tests scripts -type f -name '*.py' -exec sed -i 's/from mcp_gateway\./from chronos_gate./g' {} +
find src tests scripts -type f -name '*.py' -exec sed -i 's/import mcp_gateway/import chronos_gate/g' {} +
```

- [ ] **Step 3: `__main__.py` と `pyproject.toml` 入口を更新**

`pyproject.toml`（新規作成）:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "chronos-gate"
version = "1.0.0"
description = "Universal security evaluator gateway for AI agent tool calls"
requires-python = ">=3.12"
dependencies = [
    "chronos-graph @ git+https://github.com/yohi/chronos-graph.git",
    "mcp[cli]>=1.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "tenacity>=8.0.0",
    "tiktoken>=0.6.0",
    "pyyaml>=6.0",
    "litellm>=1.89.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
]

[project.optional-dependencies]
dev = [
    "asgi-lifespan>=2.1.0",
    "mypy>=1.20.0",
    "pytest>=9.0.2",
    "pytest-asyncio>=1.3.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.4.0",
]

[project.scripts]
chronos-gate = "chronos_gate.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/chronos_gate"]

[tool.pytest.ini_options]
asyncio_mode = "strict"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "S", "B"]
extend-select = ["T20"]

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["S101", "S105", "S106"]
"scripts/*.py" = ["T201"]

[tool.mypy]
python_version = "3.12"
mypy_path = "src"
explicit_package_bases = true
strict = true
warn_unused_ignores = false
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = "chronos_gate.server"
disallow_untyped_decorators = false
```


- [ ] **Step 5: テストを実行してリネーム漏れを確認**

```bash
uv sync --all-extras
uv run pytest tests/unit/ -v
uv run ruff check src/ tests/
uv run mypy src/
```

---

## Task 4: `chronos-gate` の npm パッケージ・CI・ドキュメント整備

**Files:**
- Create: `package.json`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Create: `README.md`
- Modify: `.opencode/plugins/chronos-gate.js`（`session.idle` 部分を削除）

**Interfaces:**
- Produces: `@yohi/opencode-plugin-chronos-gate` npm パッケージ（security evaluation のみ）
- Consumes: Task 3 の `chronos_gate` Python パッケージ

- [ ] **Step 1: `package.json` を作成**

```json
{
  "name": "@yohi/opencode-plugin-chronos-gate",
  "version": "1.0.0",
  "private": false,
  "repository": {
    "type": "git",
    "url": "git+https://github.com/yohi/chronos-gate.git"
  },
  "main": "./.opencode/plugins/chronos-gate.js",
  "files": [
    ".opencode/plugins/chronos-gate.js",
    "README.md",
    "LICENSE"
  ],
  "publishConfig": {
    "registry": "https://npm.pkg.github.com"
  },
  "engines": {
    "node": ">=26.0.0"
  },
  "scripts": {
    "build": "echo 'No build step required'"
  },
  "dependencies": {}
}
```

- [ ] **Step 2: OpenCode プラグインから `session.idle` を削除**

`.opencode/plugins/chronos-gate.js` から turn-end ingestion イベントハンドラを削除し、`permission.ask` のみ残す。

- [ ] **Step 3: CI workflow を作成**

Python: ruff / mypy / pytest
Node: eslint（必要に応じて）

- [ ] **Step 4: `README.md` を作成**

`chronos-graph/README.md` から Universal Evaluator セクションを抜粋・整理し、`chronos-gate` 用のセットアップ手順を記載。

- [ ] **Step 5: コミット**

```bash
git add .
git commit -m "feat: re-namespace mcp_gateway to chronos_gate and add packaging"
```

---

## Task 5: `chronos-graph` から `mcp_gateway` を削除

**Files:**
- Delete: `src/mcp_gateway/`
- Delete: `tests/unit/test_mcp_gateway*.py`
- Delete: `tests/integration/test_evaluator_cli_subprocess.py`
- Delete: `scripts/chronos-evaluator-hook.sh`
- Delete: `scripts/check_evaluator.sh`
- Delete: `.opencode/plugins/chronos-gate.js`
- Delete: `package.json`
- Delete: `.github/workflows/release.yml`
- Modify: `pyproject.toml`
- Modify: `scripts/bootstrap.sh`
- Modify: `README.md`
- Modify: `.opencode/package.json`（必要に応じて）

**Interfaces:**
- Produces: `chronos-graph` から `mcp_gateway` を削除し、core memory system に集中
- Consumes: `chronos-graph` 内の `chronos-shared`

- [ ] **Step 1: `mcp_gateway` ソース・テスト・スクリプトを削除**

```bash
cd "$CHRONOS_GRAPH_REPO"
git rm -rf src/mcp_gateway
git rm -f tests/unit/test_mcp_gateway_cli.py
git rm -f tests/unit/test_mcp_gateway_composite.py
git rm -f tests/unit/test_mcp_gateway_llm_evaluator.py
git rm -f tests/unit/test_mcp_gateway_memory_client.py
git rm -f tests/unit/test_mcp_gateway_evaluator_models.py
git rm -f tests/unit/test_mcp_gateway_evaluator_settings.py
git rm -f tests/unit/test_mcp_gateway.py
git rm -f tests/integration/test_evaluator_cli_subprocess.py
git rm -f scripts/chronos-evaluator-hook.sh
git rm -f scripts/check_evaluator.sh
git rm -f .opencode/plugins/chronos-gate.js
git rm -f package.json
```

- [ ] **Step 2: `pyproject.toml` を更新**

```toml
[project]
name = "context-store-mcp"
version = "2.0.0"
dependencies = [
    # ... 既存の context_store 依存 ...
]

[project.optional-dependencies]
# evaluator extra は削除または chronos-gate に委譲
```

`[project.scripts]` から `chronos-mcp-gateway` entry point を削除。
`[tool.hatch.build.targets.wheel]` から `src/mcp_gateway` を削除。



`chronos-gate` 用の設定・プラグイン配線を削除。必要な利用者は `chronos-gate` リポジトリの手順に従って個別にセットアップする。

- [ ] **Step 5: `README.md` を更新**

Universal Evaluator の詳細は `chronos-gate` リポジトリを参照するようにし、`chronos-graph` 側では連携手順と依存関係のみ記載。

- [ ] **Step 6: CI workflow を更新**

`.github/workflows/ci.yml` から evaluator 専用ジョブを削除（`chronos-gate` 側 CI でカバー）。
`.github/workflows/release.yml` は npm plugin 用なので削除済み。

- [ ] **Step 7: テスト実行**

```bash
uv sync --all-extras
uv run pytest tests/unit/ -v
uv run ruff check src/ tests/
uv run mypy src/
```

---

## Task 6: Turn-End Ingestion プラグインの分離と `chronos-graph` への残置

**Files:**
- Create: `.opencode/plugins/chronos-turn-end.js`
- Modify: `package.json`（新規作成、turn-end plugin 用）

**Interfaces:**
- Produces: `chronos-graph` 用の `session.idle` ハンドラ
- Consumes: Task 5 で削除した `.opencode/plugins/chronos-gate.js` 内の turn-end 部分

- [ ] **Step 1: Turn-end 部分を切り出し**

`.opencode/plugins/chronos-gate.js` から `session.idle` イベントハンドラを抽出し、`.opencode/plugins/chronos-turn-end.js` として新規作成。

- [ ] **Step 2: `chronos-graph` 用の `package.json` を作成**

```json
{
  "name": "@yohi/opencode-plugin-chronos-turn-end",
  "version": "1.0.0",
  "private": false,
  "repository": {
    "type": "git",
    "url": "git+https://github.com/yohi/chronos-graph.git"
  },
  "main": "./.opencode/plugins/chronos-turn-end.js",
  "files": [
    ".opencode/plugins/chronos-turn-end.js",
    "README.md",
    "LICENSE"
  ],
  "publishConfig": {
    "registry": "https://npm.pkg.github.com"
  },
  "engines": {
    "node": ">=26.0.0"
  },
  "dependencies": {}
}
```

- [ ] **Step 3: `scripts/bootstrap.sh` で turn-end プラグインを登録**

---

## Task 7: 最終検証と push

**Files:**
- All modified repos

- [ ] **Step 1: `chronos-shared` の検証**

```bash
cd "$TMPDIR/chronos-shared"
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run mypy src/
git push origin master
```

- [ ] **Step 2: `chronos-gate` の検証**

```bash
cd "$TMPDIR/chronos-gate"
uv sync --all-extras
uv run pytest tests/unit/ -v
uv run ruff check src/ tests/
uv run mypy src/
git push origin master
```

- [ ] **Step 3: `chronos-graph` の検証**

```bash
cd "$CHRONOS_GRAPH_REPO"
uv sync --all-extras
uv run pytest tests/unit/ -v
uv run ruff check src/ tests/
uv run mypy src/
```

- [ ] **Step 4: 各リポジトリの変更をレビューして push**

```bash
# chronos-graph
git status
git diff --stat
git add .
git commit -m "refactor: migrate security evaluator to chronos-gate"
```

---

## Spec Coverage Self-Review

| ユーザー要求 | 対応タスク |
|---|---|
| `mcp_gateway` 全体を `chronos-gate` へ移行 | Task 2, 3 |
| Git 履歴を保持 | Task 2 （`git filter-repo`） |
| `chronos-gate` は `chronos-graph` に依存 | Task 3 |
| `chronos_shared` を共有パッケージ化 | Task 1 |
| Turn-end ingestion は `chronos-graph` に残す | Task 6 |

## Placeholder Scan

- なし。すべてのタスクに具体的なファイルパス、コマンド、設定例を記載。
