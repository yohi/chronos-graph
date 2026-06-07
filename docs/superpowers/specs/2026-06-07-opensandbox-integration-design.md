# OpenSandbox Integration Design — Phase 1 & 2

## 1. Overview

chronos-graph プロジェクトに [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) を導入し、AIエージェント（Gemini, OpenCode 等）がテスト・静的解析を実行する際にセキュアで使い捨て（Ephemeral）な高速サンドボックス環境を利用できるようにする。

**スコープ:**

- **フェーズ1**: 静的解析（ruff, mypy, tsc, eslint）とDB非依存の単体テストをLiteサンドボックスで実行
- **フェーズ2**: 結合テスト（Postgres/Neo4j/Redis依存）をサンドボックスからDevcontainerのDBサービスへ接続して実行

**スコープ外:**

- フェーズ3（E2Eテスト / Heavy Dockerfile / 自己ルーティング高度化）は本specには含めない
- MCPゲートウェイへのサンドボックスツール統合

### 1.1 Design Decisions

| 決定事項 | 選択 | 理由 |
|---|---|---|
| アプローチ | 薄いラッパースクリプト + 宣言的プロファイル | シンプル。YAGNI。段階的拡張可能 |
| Pythonバージョン | 3.12 | `pyproject.toml` の `requires-python = ">=3.12"` に準拠 |
| フロントエンドPM | pnpm | プロンプト要件。npm → pnpm 移行を含む |
| OpenSandboxランタイム | Docker（ローカル） | Kubernetes対応は将来のスコープ |
| サンドボックス利用者 | AIエージェント | Python SDK経由でプログラマティックに操作 |

## 2. Architecture

### 2.1 System Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│  Host Machine                                                │
│                                                              │
│  ┌──────────────────┐     ┌──────────────────────────────┐  │
│  │ Human (Developer) │     │ AI Agent                      │  │
│  │                  │     │ (Gemini / OpenCode etc.)      │  │
│  │  Devcontainer    │     │                              │  │
│  │  (docker-compose)│     │  sandbox_runner.py            │  │
│  │  ┌────────────┐  │     │       │                      │  │
│  │  │ app        │  │     │       ▼                      │  │
│  │  │ postgres   │  │     │  OpenSandbox Python SDK      │  │
│  │  │ neo4j      │  │     │       │                      │  │
│  │  │ redis      │  │     └───────┼──────────────────────┘  │
│  │  └────────────┘  │             │                          │
│  └──────────────────┘             ▼                          │
│                          ┌────────────────────┐              │
│                          │ OpenSandbox Server  │              │
│                          │ (Docker Runtime)    │              │
│                          │                    │              │
│                          │  ┌──────────────┐  │              │
│                          │  │ Lite Pool    │  │              │
│                          │  │ (warm standby)│  │              │
│                          │  │ python:3.12  │  │              │
│                          │  │ + uv + pnpm  │  │              │
│                          │  └──────────────┘  │              │
│                          │                    │              │
│                          │  Egress Control:   │              │
│                          │  pypi.org          │              │
│                          │  registry.npmjs.org│              │
│                          │  test DB (opt.)    │              │
│                          └────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Execution Flow

1. AIエージェントがlint/テスト実行指示を受ける
2. `sandbox_runner.py` が対象タスクの種類を判定（lint / unit-test / integration-test）
3. OpenSandbox Python SDKでLite Poolからサンドボックスを取得（または新規作成）
4. サンドボックス内でコマンド実行（`uv run ruff check`, `uv run pytest tests/unit/` 等）
5. 結果を標準出力/標準エラーで返却
6. サンドボックスを破棄（Stateless原則）

### 2.3 Profile Routing

| Task Type | Profile | DB Connection | Egress |
|---|---|---|---|
| `ruff check`, `ruff format`, `mypy`, `tsc` | `lite` | None | pypi.org, npmjs.org |
| `pytest tests/unit/` | `lite` | In-memory SQLite | pypi.org |
| `pytest tests/integration/` | `integration` | Postgres / Neo4j / Redis | pypi.org + DB host |

Routing logic in `sandbox_runner.py`:

1. If `--profile` is explicitly specified, use it
2. Match command string against `ROUTING_RULES` (regex patterns)
3. First match wins
4. Default: `lite`

```python
ROUTING_RULES: list[tuple[str, str]] = [
    (r"tests/integration",   "integration"),
    (r"\btest_postgres\b",   "integration"),
    (r"\btest_neo4j\b",      "integration"),
    (r"\btest_redis\b",      "integration"),
]
DEFAULT_PROFILE = "lite"
```

## 3. Sandbox Infrastructure

### 3.1 Lite Dockerfile

**Path:** `.devcontainer/opensandbox/lite.Dockerfile`

Lightweight image for static analysis and unit tests:

- **Base:** `python:3.12-slim`
- **System packages:** `uv`, Node.js 22 LTS, `pnpm` (via corepack)
- **No build tools** (no `build-essential`, `git`, `gcc`)
- **Non-root user** `sandbox` (UID 1000)
- **Venv path:** `UV_PROJECT_ENVIRONMENT=/tmp/.venv` (ephemeral, avoids permission issues)

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

### 3.2 Sandbox Configuration

**Path:** `.devcontainer/opensandbox/sandbox.yaml`

Declarative profile definitions for the OpenSandbox server:

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
    # Constraint: All test DB services MUST be reachable via a single host
    # (default: host.docker.internal). If TEST_DB_HOST is overridden,
    # TEST_NEO4J_URI and TEST_REDIS_URL MUST point to the same host.
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

### 3.3 OpenSandbox Server (docker-compose)

Added to root `docker-compose.yml` under `sandbox` profile (does not affect existing `docker compose up`):

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

- `profiles: [sandbox]` — requires `docker compose --profile sandbox up opensandbox`
- Docker socket mount for container management (DinD)
- `127.0.0.1` bind for local access only

## 4. Sandbox Runner

### 4.1 Interface

**Path:** `scripts/sandbox_runner.py`

```bash
# Auto-detect profile
python scripts/sandbox_runner.py -- ruff check src/ tests/
python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v
python scripts/sandbox_runner.py -- uv run pytest tests/integration/ -v

# Explicit profile override
python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v

# Frontend tasks
python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm install && pnpm lint"
python scripts/sandbox_runner.py -- bash -c "cd frontend && npx tsc --noEmit"
```

### 4.2 Responsibilities

1. Parse command and options
2. Auto-select profile (lite / integration) via regex routing
3. Acquire sandbox from pool → execute command → stream output → destroy
4. Propagate exit code to caller
5. Install dependencies before command execution (`uv sync` / `pnpm install`)

### 4.3 Structure

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

### 4.4 Error Handling

- **Pool exhaustion**: Exponential backoff retry (max 2 retries)
- **Timeout**: `sandbox.yaml` `timeout: 300` — OpenSandbox server forcibly reclaims after 5 minutes
- **Signal handling**: `SIGTERM`/`SIGINT` triggers `teardown_sandbox` before exit
- **finally block**: Guarantees `teardown_sandbox` even on unexpected exceptions

## 5. Phase 2: Integration Test Standardization

### 5.1 SQLite In-Memory Test Standardization

Add sandbox-aware fixture to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _sandbox_aware_sqlite(tmp_path, monkeypatch):
    """Ensure SQLite tests use temp paths inside sandbox."""
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
        monkeypatch.setenv("SQLITE_GRAPH_PATH", str(tmp_path / "test_graph.db"))
```

- Only activates when `OPENSANDBOX=1` is set (no impact on existing tests)
- `sandbox_runner.py` guarantees `OPENSANDBOX=1` in the process environment for **all** sandbox executions (both `lite` and `integration` profiles) via the `env` parameter passed to `client.execute()`

### 5.2 DB Connection for Integration Tests

Sandbox → Devcontainer DB via host network:

```text
┌──────────────────────┐        ┌────────────────────┐
│ OpenSandbox Container│        │ Devcontainer        │
│                      │──net──▶│  postgres:5435      │
│  pytest integration  │        │  neo4j:7687         │
│                      │        │  redis:6379         │
└──────────────────────┘        └────────────────────┘
```

Connection via `host.docker.internal` (Docker bridge gateway). Devcontainer DB services already expose ports to host:

- Postgres: `5435:5432`
- Neo4j: `7474:7474`, `7687:7687`
- Redis: `6379:6379`

### 5.3 Test DB Isolation

To prevent sandbox tests from polluting development databases:

- **Postgres**: Create `context_store_test` database (separate from `context_store`). Add to `docker/postgres/init.sql`:

```sql
-- Test database for sandbox integration tests
CREATE DATABASE context_store_test;
GRANT ALL PRIVILEGES ON DATABASE context_store_test TO context_store;
```

- **Neo4j**: Community Edition single-DB — rely on test setup/teardown for cleanup (existing pattern)
- **Redis**: Use `SELECT 1` (DB number 1) to isolate from development data (DB number 0)

### 5.4 Egress Control

`integration` profile allows only:

- `pypi.org`, `files.pythonhosted.org` (package registry)
- `host.docker.internal` (DB access via Docker bridge)
- **All other outbound traffic is blocked**

## 6. pnpm Migration

Migrate frontend package manager from npm to pnpm:

1. Delete `frontend/package-lock.json`
2. Run `pnpm import` in `frontend/` to generate `pnpm-lock.yaml` from existing lockfile
3. Create `frontend/.npmrc` with `shamefully-hoist=true` (React/Vite compatibility)
4. Update `frontend/playwright.config.ts`: `command: 'npm run dev'` → `command: 'pnpm dev'`
5. No changes needed in `frontend/package.json` scripts (pnpm runs npm scripts natively)

## 7. File Change Summary

| File | Action | Purpose |
|---|---|---|
| `.devcontainer/opensandbox/lite.Dockerfile` | Create | Lite sandbox image |
| `.devcontainer/opensandbox/sandbox.yaml` | Create | Profile definitions (lite / integration) |
| `docker-compose.yml` | Modify | Add `opensandbox` service (sandbox profile) |
| `docker/postgres/init.sql` | Modify | Add `context_store_test` database |
| `scripts/sandbox_runner.py` | Create | Sandbox runner (routing + lifecycle) |
| `tests/conftest.py` | Modify | `OPENSANDBOX` env-aware SQLite path switching |
| `frontend/package-lock.json` | Delete | npm → pnpm migration |
| `frontend/pnpm-lock.yaml` | Create | pnpm lockfile (via `pnpm import`) |
| `frontend/.npmrc` | Create | `shamefully-hoist=true` |
| `frontend/playwright.config.ts` | Modify | `npm run dev` → `pnpm dev` |
| `pyproject.toml` | Modify | Add `opensandbox` to dev dependencies |

## 8. Testing Strategy

### 8.1 Sandbox Runner Unit Tests

`tests/unit/test_sandbox_runner.py`:

- `test_resolve_profile_default` — no pattern match → `lite`
- `test_resolve_profile_integration_paths` — `tests/integration/` → `integration`
- `test_resolve_profile_explicit_override` — `--profile` flag takes precedence
- `test_install_dependencies_python` — Python keywords trigger `uv sync`
- `test_install_dependencies_frontend` — Frontend keywords trigger `pnpm install`

### 8.2 Integration Validation

Manual validation steps after implementation:

1. Build lite image: `docker build -f .devcontainer/opensandbox/lite.Dockerfile -t chronos-graph-sandbox-lite:latest .`
2. Start OpenSandbox: `docker compose --profile sandbox up opensandbox -d`
3. Run lint in sandbox: `python scripts/sandbox_runner.py -- uv run ruff check src/`
4. Run unit tests in sandbox: `python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v -x`
5. Run integration tests in sandbox: `python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v`

## 9. Constraints & Non-Goals

### Constraints

1. **Execution isolation**: Tests/lint MUST NOT run inside the human's Devcontainer. Always use OpenSandbox.
2. **Dependency management**: Backend uses `uv` exclusively (never `pip`). Frontend uses `pnpm`.
3. **Statelessness**: Lite containers hold no state. Cleanup (container destroy) is guaranteed via `finally` + signal handlers + server timeout.
4. **No dependency bleed**: `mcp_gateway/` and `context_store/` remain decoupled. Sandbox runner is a standalone script in `scripts/`.
5. **Docker socket security**: The `/var/run/docker.sock` mount is restricted to the `sandbox` profile with `127.0.0.1` binding. It is intended for local development only and MUST NOT be used in production or shared environments.
6. **Single DB host for integration**: All test DB services (Postgres, Neo4j, Redis) MUST be reachable via a single host (default: `host.docker.internal`) to match the egress allow list. Splitting services across multiple hosts requires updating `egress.allow` in `sandbox.yaml`.

### Non-Goals

- Phase 3 features (Heavy Dockerfile, Headless Chrome, Playwright E2E in sandbox)
- MCP gateway sandbox tool integration
- Kubernetes runtime support
- CI/CD pipeline integration with OpenSandbox
