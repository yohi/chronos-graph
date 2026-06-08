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

- **Base:** `python:3.12-slim` + multi-stage `node:22.11.0-slim` (no `curl | bash`)
- **System packages:** `uv 0.5.0`, Node.js 22 LTS, `pnpm 9.15.4` (via corepack, all version-pinned)
- **No build tools** (no `build-essential`, `git`, `gcc`)
- **Non-root user** `sandbox` (UID 1000)
- **Venv path:** `UV_PROJECT_ENVIRONMENT=/tmp/.venv` (ephemeral, avoids permission issues)
- **Verification step:** `uv --version && uvx --version && node -v && npm -v && pnpm -v` runs both before and after `USER sandbox` to catch permission issues early

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22.11.0-slim AS node_source
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/tmp/.venv

COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uvx /usr/local/bin/uvx

# Copy Node.js from node_source instead of downloading via curl | bash.
COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
COPY --from=node_source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && corepack enable && corepack prepare pnpm@9.15.4 --activate \
    && rm -rf /var/lib/apt/lists/*

RUN uv --version && uvx --version && node -v && npm -v && pnpm -v

RUN groupadd -g 1000 sandbox && \
    useradd -m -u 1000 -g sandbox -s /bin/bash sandbox
USER sandbox

RUN uv --version && uvx --version && node -v && npm -v && pnpm -v

WORKDIR /workspace
CMD ["bash"]
```

### 3.2 Sandbox Configuration

**Path:** `.devcontainer/opensandbox/sandbox.yaml`

Declarative profile definitions for the OpenSandbox server.

> **NOTE (Dual definition):** `sandbox_runner.py` passes egress rules and DB environment
> variables directly as SDK parameters (`build_network_policy()`, `build_profile_env()`)
> when creating a sandbox via `SandboxSync.create()`. This means the runner overrides the
> server-side profile at runtime. The `sandbox.yaml` values serve as the server-side
> default for direct API usage or manual `docker compose` invocations. When modifying
> DB connection or egress settings, **update both** `sandbox.yaml` and the corresponding
> functions in `sandbox_runner.py` to keep them in sync.
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
      POSTGRES_PASSWORD: "${TEST_DB_PASSWORD:-dev_password}"
      NEO4J_URI: "${TEST_NEO4J_URI:-bolt://host.docker.internal:7687}"
      NEO4J_USER: "${TEST_NEO4J_USER:-neo4j}"
      NEO4J_PASSWORD: "${TEST_NEO4J_PASSWORD:-dev_password}"
      REDIS_URL: "${TEST_REDIS_URL:-redis://host.docker.internal:6379/1}"
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
python scripts/sandbox_runner.py -- uv run ruff check src/ tests/
python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v
python scripts/sandbox_runner.py -- uv run pytest tests/integration/ -v

# Explicit profile override
python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v

# Frontend tasks
python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm install && pnpm lint"
python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm exec tsc --noEmit"
```

### 4.2 Responsibilities

1. Parse command and options
2. Auto-select profile (lite / integration) via regex routing
3. Normalize bare tool commands (e.g. `ruff check` → `uv run ruff check`) via `normalize_command()`
4. Acquire sandbox from pool → execute command → stream output → destroy
5. Propagate exit code to caller (None → 1 as fail-safe)
6. Install dependencies before command execution (`uv sync` / `pnpm install`); raise `RuntimeError` on failure

### 4.3 Structure

```python
"""OpenSandbox runner for AI agent task execution."""

import argparse
import os
import re
import shlex
import signal
import sys
import time
from urllib.parse import urlparse

from opensandbox import SandboxSync
from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import Host, NetworkPolicy, NetworkRule, Volume

ROUTING_RULES: list[tuple[str, str]] = [
    (r"tests/integration", "integration"),
    (r"\btest_postgres\b", "integration"),
    (r"\btest_neo4j\b", "integration"),
    (r"\btest_redis\b", "integration"),
]
DEFAULT_PROFILE = "lite"
MAX_RETRIES = 2

# Maps sandbox.yaml profile names to their container image references.
PROFILE_IMAGES: dict[str, str] = {
    "lite": "chronos-graph-sandbox-lite:latest",
    "integration": "chronos-graph-sandbox-lite:latest",
}

BASE_EGRESS_ALLOWLIST = [
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
]
RESOURCE_LIMITS = {"cpu": "2", "memory": "2Gi"}
UV_RUN_COMMANDS = {"ruff", "mypy", "pytest"}


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
    sandbox: SandboxSync,
    command: list[str],
) -> None:
    """Install project dependencies based on the command context."""
    cmd_str = " ".join(command)

    if any(kw in cmd_str for kw in ["ruff", "mypy", "pytest", "uv"]):
        result = sandbox.commands.run(
            "uv sync --frozen --all-extras",
            opts=RunCommandOpts(working_directory="/workspace"),
        )
        exit_code = result.exit_code
        if exit_code is None or exit_code != 0:
            raise RuntimeError(f"[sandbox] uv sync failed (exit {exit_code})")

    if any(kw in cmd_str for kw in ["pnpm", "tsc", "eslint", "frontend"]):
        result = sandbox.commands.run(
            "bash -c 'cd /workspace/frontend && pnpm install --frozen-lockfile'",
            opts=RunCommandOpts(working_directory="/workspace"),
        )
        exit_code = result.exit_code
        if exit_code is None or exit_code != 0:
            raise RuntimeError(f"[sandbox] pnpm install failed (exit {exit_code})")


def resolve_project_root() -> str:
    return os.environ.get("PROJECT_ROOT", os.getcwd())


def build_profile_env(profile: str) -> dict[str, str]:
    """Build environment variables for sandbox creation.

    Always includes OPENSANDBOX=1 (for both lite and integration).
    Integration profile additionally sets DB connection variables.
    These override sandbox.yaml env at the SDK level.
    """
    env = {"OPENSANDBOX": "1"}
    if profile != "integration":
        return env

    test_db_host = os.environ.get("TEST_DB_HOST", "host.docker.internal")
    env.update(
        {
            "POSTGRES_HOST": test_db_host,
            "POSTGRES_PORT": os.environ.get("TEST_DB_PORT", "5435"),
            "POSTGRES_DB": os.environ.get("TEST_DB_NAME", "context_store_test"),
            "POSTGRES_USER": os.environ.get("TEST_DB_USER", "context_store"),
            "POSTGRES_PASSWORD": os.environ.get("TEST_DB_PASSWORD", "dev_password"),
            "NEO4J_URI": os.environ.get("TEST_NEO4J_URI", "bolt://host.docker.internal:7687"),
            "NEO4J_USER": os.environ.get("TEST_NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": os.environ.get("TEST_NEO4J_PASSWORD", "dev_password"),
            "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://host.docker.internal:6379/1"),
        }
    )
    return env


def build_network_policy(profile: str) -> NetworkPolicy:
    """Build egress network policy for sandbox creation.

    Overrides sandbox.yaml egress at the SDK level.
    """
    allowlist = [*BASE_EGRESS_ALLOWLIST]
    if profile == "integration":
        allowlist.append(os.environ.get("TEST_DB_HOST", "host.docker.internal"))
    return NetworkPolicy(
        defaultAction="deny",
        egress=[NetworkRule(action="allow", target=target) for target in allowlist],
    )


def build_workspace_volumes() -> list[Volume]:
    return [
        Volume(
            name="workspace",
            host=Host(path=resolve_project_root()),
            mountPath="/workspace",
            readOnly=False,
        )
    ]


def setup_sandbox(connection_config: ConnectionConfigSync, profile: str) -> SandboxSync:
    """Acquire a sandbox from the pool with retry on pool exhaustion."""
    image = PROFILE_IMAGES.get(profile, PROFILE_IMAGES[DEFAULT_PROFILE])
    env = build_profile_env(profile)
    network_policy = build_network_policy(profile)
    volumes = build_workspace_volumes()
    for attempt in range(MAX_RETRIES + 1):
        try:
            return SandboxSync.create(
                image=image,
                env=env,
                metadata={"profile": profile},
                resource=RESOURCE_LIMITS,
                network_policy=network_policy,
                volumes=volumes,
                connection_config=connection_config,
            )
        except Exception as exc:
            if "pool" in str(exc).lower() and attempt < MAX_RETRIES:
                wait = 2**attempt
                print(f"[sandbox] Pool exhausted, retry in {wait}s", file=sys.stderr)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Failed to acquire sandbox")  # pragma: no cover


def normalize_command(command: list[str]) -> list[str]:
    """Prefix bare Python tool commands with `uv run`.

    When the first element of the command is a known Python tool (ruff, mypy,
    pytest), it is automatically prefixed with `uv run` so that the tool is
    resolved from the project's virtual environment. If the command already
    starts with `uv`, it is returned as-is (avoiding double-prefixing).
    """
    if command and command[0] in UV_RUN_COMMANDS:
        return ["uv", "run", *command]
    return command


def forward_command_output(result: object) -> None:
    """Stream sandbox command stdout/stderr to the host process."""
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    if isinstance(stdout, bytes):
        stdout = stdout.decode()
    if isinstance(stderr, bytes):
        stderr = stderr.decode()
    if isinstance(stdout, str) and stdout:
        print(stdout, end="")
    if isinstance(stderr, str) and stderr:
        print(stderr, end="", file=sys.stderr)


def execute_in_sandbox(
    sandbox: SandboxSync,
    command: list[str],
    working_dir: str = "/workspace",
) -> int:
    """Execute command in sandbox, stream output, return exit code.

    The runner guarantees OPENSANDBOX=1 in the process environment so
    Phase 2 test hooks in tests/conftest.py (_sandbox_aware_sqlite) will
    activate inside the sandbox. OPENSANDBOX=1 is set both at container
    creation time (build_profile_env) and at command execution time
    (RunCommandOpts.envs) for belt-and-suspenders reliability.
    """
    result = sandbox.commands.run(
        shlex.join(normalize_command(command)),
        opts=RunCommandOpts(
            working_directory=working_dir,
            envs={"OPENSANDBOX": "1"},
        ),
    )
    forward_command_output(result)
    return result.exit_code if result.exit_code is not None else 1


def teardown_sandbox(sandbox: SandboxSync) -> None:
    """Destroy sandbox (stateless guarantee)."""
    try:
        sandbox.kill()
    except Exception as exc:
        print(
            f"[sandbox] Warning: failed to destroy {sandbox.id}: {exc}",
            file=sys.stderr,
        )


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

    parsed = urlparse(args.server_url)
    connection_config = ConnectionConfigSync(
        domain=parsed.netloc,
        protocol=parsed.scheme or "http",
    )

    sandbox: SandboxSync | None = None
    _cleaned_up = False

    def _cleanup(signum: int, frame: object) -> None:
        nonlocal _cleaned_up
        if sandbox and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(sandbox)
        sys.exit(128 + signum)

    signal.signal(signal.SIGTERM, _cleanup)
    signal.signal(signal.SIGINT, _cleanup)

    try:
        sandbox = setup_sandbox(connection_config, profile)
        install_dependencies(sandbox, command)
        return execute_in_sandbox(sandbox, command)
    finally:
        if sandbox and not _cleaned_up:
            _cleaned_up = True
            teardown_sandbox(sandbox)


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
def _sandbox_aware_sqlite(tmp_path, monkeypatch, sandbox_aware_sqlite_env):
    """Ensure SQLite tests use temp paths inside sandbox."""
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
```

- Only activates when `OPENSANDBOX=1` is set (no impact on existing tests)
- NOTE: Only `SQLITE_DB_PATH` is set. The SQLite backend stores both memories
  and the internal graph in a SINGLE file (`Settings.sqlite_db_path`); there is
  no separate `sqlite_graph_path` field, so a `SQLITE_GRAPH_PATH` env var would
  be a no-op and is intentionally NOT set.
- `tests/unit/conftest.py::clean_env` skips deleting `SQLITE_DB_PATH` when
  `OPENSANDBOX=1`, so this path switch is not clobbered regardless of autouse
  fixture ordering.
- `sandbox_runner.py` guarantees `OPENSANDBOX=1` in the process environment for **all** sandbox executions (both `lite` and `integration` profiles). It is set at **two points**: (1) container creation via `build_profile_env()` → `SandboxSync.create(env=...)`, and (2) command execution via `RunCommandOpts(envs={"OPENSANDBOX": "1"})`. This belt-and-suspenders approach ensures the env var is available regardless of how the container's entrypoint inherits environment variables.

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

-- Switch to test database and apply the same schema
\c context_store_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
\i /docker-entrypoint-initdb.d/schema.sql
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
