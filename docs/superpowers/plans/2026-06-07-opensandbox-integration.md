# OpenSandbox Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chronos-graph プロジェクトに OpenSandbox を導入し、AIエージェントがセキュアで使い捨てのサンドボックス環境でテスト・静的解析を実行できるようにする。

**Architecture:** OpenSandbox Python SDK を介してDockerベースのLiteサンドボックスプールを管理し、`sandbox_runner.py` がタスクタイプに応じたプロファイル自動選択・依存関係インストール・コマンド実行・コンテナ破棄のライフサイクルを一元制御する。Phase 2では結合テスト用 `integration` プロファイルでDevcontainerのDB群（Postgres/Neo4j/Redis）へ接続する。

**Tech Stack:** Python 3.12, OpenSandbox Python SDK, Docker, uv, pnpm, pytest

**Design Document:** [`docs/superpowers/specs/2026-06-07-opensandbox-integration-design.md`](../specs/2026-06-07-opensandbox-integration-design.md)

---

## Git Branch Workflow (AI-Native Stacked PR)

> **運用ルール全文:** <https://different-sunday-448.notion.site/AI-Native-Stacked-PR-Workflow-3611669a4c16802eb032eb4ab05a8adb>

### ブランチ戦略

```text
master
 └─ feat/opensandbox-phase1  (Phase 1 Base)
     ├─ feat/opensandbox-p1-task1  (Lite Dockerfile + sandbox.yaml)
     ├─ feat/opensandbox-p1-task2  (docker-compose opensandbox service)
     ├─ feat/opensandbox-p1-task3  (sandbox_runner.py core)
     └─ feat/opensandbox-p1-task4  (sandbox_runner unit tests)
 └─ feat/opensandbox-phase2  (Phase 2 Base)
     ├─ feat/opensandbox-p2-task1  (pnpm migration)
     ├─ feat/opensandbox-p2-task2  (test DB isolation)
     ├─ feat/opensandbox-p2-task3  (conftest.py sandbox-aware fixture)
     └─ feat/opensandbox-p2-task4  (pyproject.toml + CI update)
```

### 派生元の判断ルール

| 条件 | 派生元 |
|---|---|
| Task が**単体で完結**し、Phase Base のコードだけで動作する | **Phase Base** から派生 |
| Task が**直前の Task の成果物に依存**する | **直前 Task のブランチ**から派生 |

### PRフロー

1. 各 Task 完了時 → **Phase Base に向けた Draft PR** を作成
2. Phase 全 Task 完了後 → Phase Base を **master に向けた PR** として提出
3. master への直接コミットは**厳禁**

---

## File Structure

| File | Action | Phase | Purpose |
|---|---|---|---|
| `.devcontainer/opensandbox/lite.Dockerfile` | Create | P1-T1 | Lite サンドボックスイメージ定義 |
| `.devcontainer/opensandbox/sandbox.yaml` | Create | P1-T1 | プロファイル定義（lite / integration） |
| `docker-compose.yml` | Modify | P1-T2 | `opensandbox` サービス追加（sandbox profile） |
| `scripts/sandbox_runner.py` | Create | P1-T3 | サンドボックスランナー（ルーティング + ライフサイクル） |
| `tests/unit/test_sandbox_runner.py` | Create | P1-T4 | sandbox_runner のユニットテスト |
| `frontend/pnpm-lock.yaml` | Create | P2-T1 | pnpm ロックファイル（`pnpm import`） |
| `frontend/.npmrc` | Create | P2-T1 | `shamefully-hoist=true` |
| `frontend/package-lock.json` | Delete | P2-T1 | npm → pnpm 移行 |
| `frontend/playwright.config.ts` | Modify | P2-T1 | `npm run dev` → `pnpm dev` |
| `docker/postgres/init.sql` | Modify | P2-T2 | `context_store_test` DB 追加 |
| `tests/conftest.py` | Modify | P2-T3 | `OPENSANDBOX` env-aware SQLite パス切替 |
| `pyproject.toml` | Modify | P2-T4 | `opensandbox` dev 依存追加 |

---

## Phase 1: Sandbox Infrastructure & Runner

> **Phase Base Branch:** `feat/opensandbox-phase1` (from `master`)

### Task 1.1: Lite Dockerfile & Sandbox Configuration

**派生元:** Phase Base (`feat/opensandbox-phase1`)

**Files:**
- Create: `.devcontainer/opensandbox/lite.Dockerfile`
- Create: `.devcontainer/opensandbox/sandbox.yaml`

- [ ] **Step 1: Create the opensandbox directory**

```bash
mkdir -p .devcontainer/opensandbox
```

- [ ] **Step 2: Create lite.Dockerfile**

Create `.devcontainer/opensandbox/lite.Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/tmp/.venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:latest /uvx /usr/local/bin/uvx

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && corepack enable && corepack prepare pnpm@latest --activate \
    && apt-get purge -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 sandbox && \
    useradd -m -u 1000 -g sandbox -s /bin/bash sandbox
USER sandbox

WORKDIR /workspace
CMD ["bash"]
```

- [ ] **Step 3: Create sandbox.yaml**

Create `.devcontainer/opensandbox/sandbox.yaml`:

```yaml
profiles:
  lite:
    image: chronos-graph-sandbox-lite:latest
    resource_limits:
      cpu: "2"
      memory: "2Gi"
    timeout: 300
    pool:
      min_ready: 1
      max_instances: 3
      idle_timeout: 600
    egress:
      default: deny
      allow:
        - pypi.org
        - files.pythonhosted.org
        - registry.npmjs.org
    working_dir: /workspace
    mounts:
      - source: "${PROJECT_ROOT}"
        target: /workspace
        read_only: false

  integration:
    extends: lite
    egress:
      default: deny
      allow:
        - pypi.org
        - files.pythonhosted.org
        - registry.npmjs.org
        - "${TEST_DB_HOST:-host.docker.internal}"
    env:
      OPENSANDBOX: "1"
      POSTGRES_HOST: "${TEST_DB_HOST:-host.docker.internal}"
      POSTGRES_PORT: "${TEST_DB_PORT:-5435}"
      POSTGRES_DB: "${TEST_DB_NAME:-context_store_test}"
      POSTGRES_USER: "${TEST_DB_USER:-context_store}"
      POSTGRES_PASSWORD: "${TEST_DB_PASSWORD}"
      NEO4J_URI: "${TEST_NEO4J_URI:-bolt://host.docker.internal:7687}"
      NEO4J_AUTH: "${TEST_NEO4J_AUTH}"
      REDIS_URL: "${TEST_REDIS_URL:-redis://host.docker.internal:6379}"
```

- [ ] **Step 4: Verify Dockerfile builds**

Run: `docker build -f .devcontainer/opensandbox/lite.Dockerfile -t chronos-graph-sandbox-lite:latest .`
Expected: Image builds successfully, includes `uv`, `node`, `pnpm` binaries.

- [ ] **Step 5: Verify sandbox.yaml syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.devcontainer/opensandbox/sandbox.yaml'))"`
Expected: No errors. YAML parses cleanly.

- [ ] **Step 6: Commit**

```bash
git add .devcontainer/opensandbox/
git commit -m "feat(sandbox): Lite Dockerfile と sandbox.yaml プロファイル定義を追加"
```

- [ ] **Step 7: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p1-task1` → `feat/opensandbox-phase1` (Draft)

---

### Task 1.2: docker-compose OpenSandbox Service

**派生元:** Phase Base (`feat/opensandbox-phase1`)
— docker-compose の変更は sandbox.yaml の存在に依存するが、ファイルパスの参照のみであり、単体で構文的に完結する。

**Files:**
- Modify: `docker-compose.yml` (add `opensandbox` service at the end, before `volumes:`)

- [ ] **Step 1: Add opensandbox service to docker-compose.yml**

Add the following service definition to `docker-compose.yml`, immediately before the `volumes:` section (before line 113):

```yaml
  opensandbox:
    image: opensandbox/opensandbox-server:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./.devcontainer/opensandbox/sandbox.yaml:/etc/opensandbox/config.yaml:ro
      - .:/project:ro
    environment:
      OSB_RUNTIME: docker
      OSB_CONFIG_PATH: /etc/opensandbox/config.yaml
    ports:
      - "127.0.0.1:8090:8080"
    profiles:
      - sandbox
```

- [ ] **Step 2: Validate docker-compose syntax**

Run: `docker compose config --profiles sandbox`
Expected: Valid YAML output including the `opensandbox` service definition.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(sandbox): docker-compose に OpenSandbox サービスを追加 (sandbox profile)"
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p1-task2` → `feat/opensandbox-phase1` (Draft)

---

### Task 1.3: Sandbox Runner Implementation

**派生元:** Phase Base (`feat/opensandbox-phase1`)
— `sandbox_runner.py` はスタンドアロンスクリプトであり、他 Task の成果物なしで作成・コミット可能。

**Files:**
- Create: `scripts/sandbox_runner.py`

- [ ] **Step 1: Create sandbox_runner.py**

Create `scripts/sandbox_runner.py`:

```python
"""OpenSandbox runner for AI agent task execution."""

import argparse
import os
import re
import signal
import sys
import time

from opensandbox import SandboxClient


ROUTING_RULES: list[tuple[str, str]] = [
    (r"tests/integration",   "integration"),
    (r"\btest_postgres\b",   "integration"),
    (r"\btest_neo4j\b",      "integration"),
    (r"\btest_redis\b",      "integration"),
]
DEFAULT_PROFILE = "lite"
MAX_RETRIES = 2


def resolve_profile(command: list[str], explicit: str | None) -> str:
    """Resolve sandbox profile from command pattern or explicit override."""
    if explicit:
        return explicit
    cmd_str = " ".join(command)
    for pattern, profile in ROUTING_RULES:
        if re.search(pattern, cmd_str):
            return profile
    return DEFAULT_PROFILE


def install_dependencies(
    client: SandboxClient,
    sandbox_id: str,
    command: list[str],
) -> None:
    """Install project dependencies based on the command context."""
    cmd_str = " ".join(command)

    if any(kw in cmd_str for kw in ["ruff", "mypy", "pytest", "uv"]):
        client.execute(sandbox_id, ["uv", "sync", "--frozen", "--all-extras"])

    if any(kw in cmd_str for kw in ["pnpm", "tsc", "eslint", "frontend"]):
        client.execute(
            sandbox_id,
            ["bash", "-c", "cd /workspace/frontend && pnpm install --frozen-lockfile"],
        )


def setup_sandbox(client: SandboxClient, profile: str) -> str:
    """Acquire a sandbox from the pool with retry on pool exhaustion."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.create(profile=profile)
        except Exception as exc:
            if "pool" in str(exc).lower() and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                print(f"[sandbox] Pool exhausted, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    # Unreachable, but satisfies type checker
    raise RuntimeError("Failed to acquire sandbox")  # pragma: no cover


def execute_in_sandbox(
    client: SandboxClient,
    sandbox_id: str,
    command: list[str],
    working_dir: str = "/workspace",
) -> int:
    """Execute command in sandbox, stream output, return exit code.

    The runner guarantees OPENSANDBOX=1 in the process environment so
    Phase 2 test hooks in tests/conftest.py (_sandbox_aware_sqlite) will
    activate inside the sandbox.
    """
    result = client.execute(
        sandbox_id, command, working_dir=working_dir, stream=True,
        env={"OPENSANDBOX": "1"},
    )
    return result.exit_code


def teardown_sandbox(client: SandboxClient, sandbox_id: str) -> None:
    """Destroy sandbox (stateless guarantee)."""
    try:
        client.destroy(sandbox_id)
    except Exception:
        print(f"[sandbox] Warning: failed to destroy {sandbox_id}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run commands in OpenSandbox")
    parser.add_argument("--profile", choices=["lite", "integration"], default=None)
    parser.add_argument(
        "--server-url",
        default=os.environ.get("OPENSANDBOX_URL", "http://localhost:8090"),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("Error: No command specified", file=sys.stderr)
        return 1

    profile = resolve_profile(command, args.profile)
    print(f"[sandbox] Profile: {profile}", file=sys.stderr)

    client = SandboxClient(base_url=args.server_url)
    sandbox_id: str | None = None
    _cleaned_up = False

    def _cleanup(signum: int, frame: object) -> None:
        nonlocal _cleaned_up
        if sandbox_id and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(client, sandbox_id)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        sandbox_id = setup_sandbox(client, profile)
        install_dependencies(client, sandbox_id, command)
        return execute_in_sandbox(client, sandbox_id, command)
    finally:
        if sandbox_id and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(client, sandbox_id)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('scripts/sandbox_runner.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run ruff check**

Run: `uv run ruff check scripts/sandbox_runner.py`
Expected: No errors (note: `scripts/*.py` has `T201` ignored per `pyproject.toml`).

- [ ] **Step 4: Commit**

```bash
git add scripts/sandbox_runner.py
git commit -m "feat(sandbox): sandbox_runner.py を追加（プロファイルルーティング + ライフサイクル管理）"
```

- [ ] **Step 5: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p1-task3` → `feat/opensandbox-phase1` (Draft)

---

### Task 1.4: Sandbox Runner Unit Tests

**派生元:** 直前 Task (`feat/opensandbox-p1-task3`)
— テストは `sandbox_runner.py` の関数を直接インポートするため、Task 1.3 の成果物が必須。

**Files:**
- Create: `tests/unit/test_sandbox_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_sandbox_runner.py`:

```python
"""Unit tests for scripts/sandbox_runner.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# sandbox_runner.py は src/ パッケージ外のスクリプトなので sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture(autouse=True)
def _mock_opensandbox_import():
    """opensandbox パッケージが未インストールでもテスト可能にする。"""
    mock_module = MagicMock()
    mock_module.SandboxClient = MagicMock
    with patch.dict("sys.modules", {"opensandbox": mock_module}):
        yield


def _import_runner():
    """テストごとにモジュールをリロードする。"""
    import importlib
    if "sandbox_runner" in sys.modules:
        return importlib.reload(sys.modules["sandbox_runner"])
    return importlib.import_module("sandbox_runner")


class TestResolveProfile:
    """resolve_profile() のテスト。"""

    def test_default_profile(self):
        runner = _import_runner()
        result = runner.resolve_profile(["ruff", "check", "src/"], None)
        assert result == "lite"

    def test_integration_path(self):
        runner = _import_runner()
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/integration/", "-v"], None
        )
        assert result == "integration"

    def test_integration_test_postgres(self):
        runner = _import_runner()
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/unit/test_postgres.py"], None
        )
        assert result == "integration"

    def test_integration_test_neo4j(self):
        runner = _import_runner()
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/unit/test_neo4j.py"], None
        )
        assert result == "integration"

    def test_integration_test_redis(self):
        runner = _import_runner()
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/unit/test_redis.py"], None
        )
        assert result == "integration"

    def test_explicit_override(self):
        runner = _import_runner()
        result = runner.resolve_profile(["ruff", "check", "src/"], "integration")
        assert result == "integration"

    def test_explicit_override_lite(self):
        runner = _import_runner()
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/integration/"], "lite"
        )
        assert result == "lite"


class TestInstallDependencies:
    """install_dependencies() のテスト。"""

    def test_python_keywords_trigger_uv_sync(self):
        runner = _import_runner()
        mock_client = MagicMock()
        runner.install_dependencies(
            mock_client, "sandbox-123", ["uv", "run", "pytest", "tests/unit/"]
        )
        mock_client.execute.assert_called_once_with(
            "sandbox-123", ["uv", "sync", "--frozen", "--all-extras"]
        )

    def test_frontend_keywords_trigger_pnpm_install(self):
        runner = _import_runner()
        mock_client = MagicMock()
        runner.install_dependencies(
            mock_client,
            "sandbox-123",
            ["bash", "-c", "cd frontend && pnpm lint"],
        )
        mock_client.execute.assert_called_once_with(
            "sandbox-123",
            ["bash", "-c", "cd /workspace/frontend && pnpm install --frozen-lockfile"],
        )

    def test_ruff_triggers_uv_sync(self):
        runner = _import_runner()
        mock_client = MagicMock()
        runner.install_dependencies(
            mock_client, "sandbox-123", ["ruff", "check", "src/"]
        )
        mock_client.execute.assert_called_once_with(
            "sandbox-123", ["uv", "sync", "--frozen", "--all-extras"]
        )

    def test_no_matching_keywords(self):
        runner = _import_runner()
        mock_client = MagicMock()
        runner.install_dependencies(
            mock_client, "sandbox-123", ["echo", "hello"]
        )
        mock_client.execute.assert_not_called()


class TestSetupSandbox:
    """setup_sandbox() のテスト。"""

    def test_success_first_try(self):
        runner = _import_runner()
        mock_client = MagicMock()
        mock_client.create.return_value = "sandbox-abc"
        result = runner.setup_sandbox(mock_client, "lite")
        assert result == "sandbox-abc"
        mock_client.create.assert_called_once_with(profile="lite")

    def test_retry_on_pool_exhaustion(self):
        runner = _import_runner()
        mock_client = MagicMock()
        mock_client.create.side_effect = [
            RuntimeError("pool exhausted"),
            "sandbox-xyz",
        ]
        with patch("sandbox_runner.time.sleep"):
            result = runner.setup_sandbox(mock_client, "lite")
        assert result == "sandbox-xyz"
        assert mock_client.create.call_count == 2

    def test_raises_after_max_retries(self):
        runner = _import_runner()
        mock_client = MagicMock()
        mock_client.create.side_effect = RuntimeError("pool exhausted")
        with patch("sandbox_runner.time.sleep"), pytest.raises(RuntimeError, match="pool"):
            runner.setup_sandbox(mock_client, "lite")
        assert mock_client.create.call_count == runner.MAX_RETRIES + 1


class TestTeardownSandbox:
    """teardown_sandbox() のテスト。"""

    def test_successful_teardown(self):
        runner = _import_runner()
        mock_client = MagicMock()
        runner.teardown_sandbox(mock_client, "sandbox-123")
        mock_client.destroy.assert_called_once_with("sandbox-123")

    def test_teardown_failure_does_not_raise(self, capsys):
        runner = _import_runner()
        mock_client = MagicMock()
        mock_client.destroy.side_effect = RuntimeError("destroy failed")
        runner.teardown_sandbox(mock_client, "sandbox-123")
        captured = capsys.readouterr()
        assert "Warning" in captured.err
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sandbox_runner.py -v`
Expected: All tests PASS (mocks cover the `opensandbox` SDK dependency).

- [ ] **Step 3: Run full unit test suite for regression**

Run: `uv run pytest tests/unit/ -v --tb=short`
Expected: All existing + new tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_sandbox_runner.py
git commit -m "test(sandbox): sandbox_runner のユニットテストを追加"
```

- [ ] **Step 5: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p1-task4` → `feat/opensandbox-phase1` (Draft)

---

### Phase 1 Completion

- [ ] **Phase Base PR を master に向けて作成**

PR: `feat/opensandbox-phase1` → `master`

---

## Phase 2: Integration Test Support & pnpm Migration

> **Phase Base Branch:** `feat/opensandbox-phase2` (from `master`)
> Phase 1 のマージ後に開始。

### Task 2.1: pnpm Migration

**派生元:** Phase Base (`feat/opensandbox-phase2`)
— フロントエンドのパッケージマネージャ変更は他 Task に依存しない。

**Files:**
- Delete: `frontend/package-lock.json`
- Create: `frontend/pnpm-lock.yaml` (generated by `pnpm import`)
- Create: `frontend/.npmrc`
- Modify: `frontend/playwright.config.ts:29`

- [ ] **Step 1: Generate pnpm-lock.yaml from existing lockfile**

```bash
cd frontend && pnpm import
```

Expected: `pnpm-lock.yaml` generated from `package-lock.json`.

- [ ] **Step 2: Delete npm lockfile**

```bash
rm frontend/package-lock.json
```

- [ ] **Step 3: Create .npmrc**

Create `frontend/.npmrc`:

```ini
shamefully-hoist=true
```

- [ ] **Step 4: Verify pnpm install works**

```bash
cd frontend && pnpm install --frozen-lockfile
```

Expected: Successful install with no errors.

- [ ] **Step 5: Update playwright.config.ts**

In `frontend/playwright.config.ts`, change line 29:

```diff
-        command: 'npm run dev',
+        command: 'pnpm dev',
```

- [ ] **Step 6: Run frontend lint to verify**

```bash
cd frontend && pnpm lint
```

Expected: No errors.

- [ ] **Step 7: Run TypeScript check**

```bash
cd frontend && pnpm exec tsc --noEmit
```

Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/.npmrc frontend/pnpm-lock.yaml frontend/playwright.config.ts
git rm frontend/package-lock.json
git commit -m "chore(frontend): npm から pnpm に移行"
```

- [ ] **Step 9: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p2-task1` → `feat/opensandbox-phase2` (Draft)

---

### Task 2.2: Test Database Isolation

**派生元:** Phase Base (`feat/opensandbox-phase2`)
— DB初期化SQLの変更は他 Task に依存しない。

**Files:**
- Modify: `docker/postgres/init.sql`

- [ ] **Step 1: Add test database to init.sql**

Modify `docker/postgres/init.sql` to add test database creation before the schema import:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;

-- Apply schema to default database
\i /docker-entrypoint-initdb.d/schema.sql

-- Test database for sandbox integration tests
CREATE DATABASE context_store_test;
GRANT ALL PRIVILEGES ON DATABASE context_store_test TO context_store;

-- Switch to test database and apply the same schema
\c context_store_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
\i /docker-entrypoint-initdb.d/schema.sql
```

- [ ] **Step 2: Verify SQL syntax**

```bash
docker compose exec postgres psql -U context_store -c "SELECT 1" context_store_test 2>&1 || echo "DB not yet created (expected if Postgres not rebuilt)"
```

Expected: Either a successful query or a message that the DB doesn't exist yet (will be created on next `docker compose up` with fresh volume).

- [ ] **Step 3: Commit**

```bash
git add docker/postgres/init.sql
git commit -m "feat(sandbox): テスト用 context_store_test データベースを init.sql に追加"
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p2-task2` → `feat/opensandbox-phase2` (Draft)

---

### Task 2.3: Sandbox-Aware Test Fixture

**派生元:** Phase Base (`feat/opensandbox-phase2`)
— `OPENSANDBOX` 環境変数チェックのみで、他 Task のコードに依存しない。

**Files:**
- Modify: `tests/conftest.py` (add `os` import, append fixture)
- Create: `tests/unit/test_conftest_sandbox.py`

- [ ] **Step 1: Write the test for the fixture behavior**

Create `tests/unit/test_conftest_sandbox.py`:

```python
"""Tests for the _sandbox_aware_sqlite fixture in conftest.py."""

from __future__ import annotations

import os


def test_sandbox_aware_sqlite_activates(tmp_path, monkeypatch):
    """OPENSANDBOX=1 の場合、SQLITE_DB_PATH と SQLITE_GRAPH_PATH が tmp_path に設定される。"""
    monkeypatch.setenv("OPENSANDBOX", "1")
    monkeypatch.delenv("SQLITE_DB_PATH", raising=False)
    monkeypatch.delenv("SQLITE_GRAPH_PATH", raising=False)

    # conftest.py の実際のヘルパー関数を呼び出してフィクスチャロジックを検証
    from conftest import _apply_sandbox_sqlite_paths

    _apply_sandbox_sqlite_paths(tmp_path, monkeypatch)

    assert os.environ["SQLITE_DB_PATH"] == str(tmp_path / "test.db")
    assert os.environ["SQLITE_GRAPH_PATH"] == str(tmp_path / "test_graph.db")


def test_sandbox_aware_sqlite_inactive_without_env(tmp_path, monkeypatch):
    """OPENSANDBOX が未設定の場合、SQLITE パスは変更されない。"""
    monkeypatch.delenv("OPENSANDBOX", raising=False)
    monkeypatch.delenv("SQLITE_DB_PATH", raising=False)
    monkeypatch.delenv("SQLITE_GRAPH_PATH", raising=False)

    from conftest import _apply_sandbox_sqlite_paths

    _apply_sandbox_sqlite_paths(tmp_path, monkeypatch)

    assert os.environ.get("SQLITE_DB_PATH") is None
    assert os.environ.get("SQLITE_GRAPH_PATH") is None
```

- [ ] **Step 2: Run the tests to verify baseline**

Run: `uv run pytest tests/unit/test_conftest_sandbox.py -v`
Expected: Both tests FAIL — `ImportError: cannot import name '_apply_sandbox_sqlite_paths' from 'conftest'`. This is expected (TDD Red phase); the helper function will be added in Step 3.

- [ ] **Step 3: Add the fixture to conftest.py**

Add `import os` to the top of `tests/conftest.py` (after the existing imports), and append the helper function and fixture after the existing `anyio_backend` fixture:

```python
import os

# ... existing code ...

def _apply_sandbox_sqlite_paths(tmp_path, monkeypatch):
    """Apply sandbox-aware SQLite paths when running in OpenSandbox."""
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("SQLITE_GRAPH_PATH", str(tmp_path / "test_graph.db"))


@pytest.fixture(autouse=True)
def _sandbox_aware_sqlite(tmp_path, monkeypatch):
    """Ensure SQLite tests use temp paths inside sandbox."""
    _apply_sandbox_sqlite_paths(tmp_path, monkeypatch)
```

- [ ] **Step 4: Run full test suite for regression**

Run: `uv run pytest tests/unit/ -v --tb=short`
Expected: All tests PASS. The new fixture is `autouse=True` but only activates when `OPENSANDBOX=1`.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/unit/test_conftest_sandbox.py
git commit -m "feat(sandbox): conftest.py に OPENSANDBOX 環境変数対応の SQLite パス切替 fixture を追加"
```

- [ ] **Step 6: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p2-task3` → `feat/opensandbox-phase2` (Draft)

---

### Task 2.4: pyproject.toml Dependency Update

**派生元:** Phase Base (`feat/opensandbox-phase2`)
— `pyproject.toml` の依存追加は他 Task に依存しない。

**Files:**
- Modify: `pyproject.toml` (add `opensandbox` to dev dependencies)

- [ ] **Step 1: Add opensandbox to dev dependencies**

In `pyproject.toml`, modify the `[dependency-groups]` `dev` section (around line 174):

```diff
 [dependency-groups]
 dev = [
     "asgi-lifespan>=2.1.0",
     "mypy>=1.20.0",
+    "opensandbox>=0.1.0",
     "pytest>=9.0.2",
     "pytest-asyncio>=1.3.0",
     "pytest-benchmark>=4.0.0",
     "pytest-cov>=5.0.0",
     "ruff>=0.4.0",
 ]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --all-extras`
Expected: `opensandbox` package resolved and installed.

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import opensandbox; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run ruff & mypy for regression**

Run:

```bash
uv run ruff check src/ tests/
uv run mypy src/
```

Expected: No new errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): opensandbox を dev 依存に追加"
```

- [ ] **Step 6: Phase Base に向けた Draft PR を作成**

PR: `feat/opensandbox-p2-task4` → `feat/opensandbox-phase2` (Draft)

---

### Phase 2 Completion

- [ ] **Phase Base PR を master に向けて作成**

PR: `feat/opensandbox-phase2` → `master`

---

## Verification Checklist

Phase 1 + Phase 2 完了後に以下を手動検証:

- [ ] Lite イメージビルド: `docker build -f .devcontainer/opensandbox/lite.Dockerfile -t chronos-graph-sandbox-lite:latest .`
- [ ] OpenSandbox 起動: `docker compose --profile sandbox up opensandbox -d`
- [ ] Lint in sandbox: `python scripts/sandbox_runner.py -- uv run ruff check src/`
- [ ] Unit tests in sandbox: `python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v -x`
- [ ] Integration tests in sandbox: `python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v`
- [ ] Frontend lint in sandbox: `python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm install && pnpm lint"`
- [ ] CI passes on all Draft PRs
