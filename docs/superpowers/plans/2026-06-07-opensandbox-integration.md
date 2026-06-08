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
      POSTGRES_PASSWORD: "${TEST_DB_PASSWORD:-dev_password}"
      NEO4J_URI: "${TEST_NEO4J_URI:-bolt://host.docker.internal:7687}"
      NEO4J_USER: "${TEST_NEO4J_USER:-neo4j}"
      NEO4J_PASSWORD: "${TEST_NEO4J_PASSWORD:-dev_password}"
      REDIS_URL: "${TEST_REDIS_URL:-redis://host.docker.internal:6379/1}"
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

> NOTE: The code below reflects the actual implementation using the real OpenSandbox
> SDK (`SandboxSync` / `ConnectionConfigSync` / `RunCommandOpts`). The source of truth
> is `scripts/sandbox_runner.py`; if any discrepancy exists, the source file wins.
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
    """Prefix bare Python tool commands with `uv run`."""
    if command and command[0] in UV_RUN_COMMANDS:
        return ["uv", "run", *command]
    return command


def forward_command_output(result: object) -> None:
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
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _add_scripts_to_path(monkeypatch):
    scripts_path = str(Path(__file__).resolve().parents[2] / "scripts")
    monkeypatch.syspath_prepend(scripts_path)


@pytest.fixture(autouse=True)
def _mock_opensandbox_import():
    # Mock the top-level package and all submodules imported by sandbox_runner.
    # CI may not have 'opensandbox' installed as a proper package, so we stub
    # every dotted path the script imports at module level.
    @dataclass
    class _RunCommandOpts:
        working_directory: str = ""
        envs: dict = field(default_factory=dict)

    @dataclass
    class _Host:
        path: str

    @dataclass
    class _NetworkRule:
        action: str
        target: str

    @dataclass
    class _NetworkPolicy:
        defaultAction: str = "deny"
        egress: list[_NetworkRule] | None = None

    @dataclass
    class _Volume:
        name: str
        host: _Host | None
        mountPath: str
        readOnly: bool = False

    mock_opensandbox = MagicMock()
    mock_config_sync = MagicMock()
    mock_models_execd = MagicMock()
    mock_models_sandboxes = MagicMock()
    mock_models_execd.RunCommandOpts.side_effect = _RunCommandOpts
    mock_models_sandboxes.Host = _Host
    mock_models_sandboxes.NetworkPolicy = _NetworkPolicy
    mock_models_sandboxes.NetworkRule = _NetworkRule
    mock_models_sandboxes.Volume = _Volume
    mock_modules = {
        "opensandbox": mock_opensandbox,
        "opensandbox.config": MagicMock(),
        "opensandbox.config.connection_sync": mock_config_sync,
        "opensandbox.models": MagicMock(),
        "opensandbox.models.execd": mock_models_execd,
        "opensandbox.models.sandboxes": mock_models_sandboxes,
    }
    with patch.dict("sys.modules", mock_modules):
        yield


def _import_runner():
    import importlib

    if "sandbox_runner" in sys.modules:
        return importlib.reload(sys.modules["sandbox_runner"])
    return importlib.import_module("sandbox_runner")


@pytest.fixture
def runner():
    return _import_runner()


class TestResolveProfile:
    def test_default_profile(self, runner):
        result = runner.resolve_profile(["ruff", "check", "src/"], None)
        assert result == "lite"

    def test_integration_path(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/integration/", "-v"], None)
        assert result == "integration"

    def test_integration_test_postgres(self, runner):
        result = runner.resolve_profile(
            ["uv", "run", "pytest", "tests/unit/test_postgres.py"], None
        )
        assert result == "integration"

    def test_integration_test_neo4j(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/unit/test_neo4j.py"], None)
        assert result == "integration"

    def test_integration_test_redis(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/unit/test_redis.py"], None)
        assert result == "integration"

    def test_explicit_override(self, runner):
        result = runner.resolve_profile(["ruff", "check", "src/"], "integration")
        assert result == "integration"

    def test_explicit_override_lite(self, runner):
        result = runner.resolve_profile(["uv", "run", "pytest", "tests/integration/"], "lite")
        assert result == "lite"


class TestInstallDependencies:
    def test_python_keywords_trigger_uv_sync(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(mock_sandbox, ["uv", "run", "pytest", "tests/unit/"])
        mock_sandbox.commands.run.assert_called_once_with(
            "uv sync --frozen --all-extras",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_frontend_keywords_trigger_pnpm_install(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(
            mock_sandbox,
            ["bash", "-c", "cd frontend && pnpm lint"],
        )
        mock_sandbox.commands.run.assert_called_once_with(
            "bash -c 'cd /workspace/frontend && pnpm install --frozen-lockfile'",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_ruff_triggers_uv_sync(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        runner.install_dependencies(mock_sandbox, ["ruff", "check", "src/"])
        mock_sandbox.commands.run.assert_called_once_with(
            "uv sync --frozen --all-extras",
            opts=runner.RunCommandOpts(working_directory="/workspace"),
        )

    def test_uv_sync_failure_raises_runtime_error(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"uv sync failed"):
            runner.install_dependencies(mock_sandbox, ["ruff", "check", "src/"])

    def test_pnpm_install_failure_raises_runtime_error(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 1
        with pytest.raises(RuntimeError, match=r"pnpm install failed"):
            runner.install_dependencies(
                mock_sandbox,
                ["bash", "-c", "cd frontend && pnpm lint"],
            )

    def test_no_matching_keywords(self, runner):
        mock_sandbox = MagicMock()
        runner.install_dependencies(mock_sandbox, ["echo", "hello"])
        mock_sandbox.commands.run.assert_not_called()


class TestSetupSandbox:
    def test_success_first_try(self, runner):
        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(runner.SandboxSync, "create", return_value=mock_sandbox) as mock_create:
            result = runner.setup_sandbox(mock_cfg, "lite")
        assert result is mock_sandbox
        mock_create.assert_called_once_with(
            image=runner.PROFILE_IMAGES["lite"],
            env={"OPENSANDBOX": "1"},
            metadata={"profile": "lite"},
            resource={"cpu": "2", "memory": "2Gi"},
            network_policy=runner.NetworkPolicy(
                defaultAction="deny",
                egress=[
                    runner.NetworkRule(action="allow", target="pypi.org"),
                    runner.NetworkRule(action="allow", target="files.pythonhosted.org"),
                    runner.NetworkRule(action="allow", target="registry.npmjs.org"),
                ],
            ),
            volumes=[
                runner.Volume(
                    name="workspace",
                    host=runner.Host(path=runner.resolve_project_root()),
                    mountPath="/workspace",
                    readOnly=False,
                )
            ],
            connection_config=mock_cfg,
        )

    def test_integration_profile_expands_db_env_and_network_policy(self, runner):
        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(runner.SandboxSync, "create", return_value=mock_sandbox) as mock_create:
            result = runner.setup_sandbox(mock_cfg, "integration")

        assert result is mock_sandbox
        mock_create.assert_called_once_with(
            image=runner.PROFILE_IMAGES["integration"],
            env={
                "OPENSANDBOX": "1",
                "POSTGRES_HOST": "host.docker.internal",
                "POSTGRES_PORT": "5435",
                "POSTGRES_DB": "context_store_test",
                "POSTGRES_USER": "context_store",
                "POSTGRES_PASSWORD": "dev_password",
                "NEO4J_URI": "bolt://host.docker.internal:7687",
                "NEO4J_USER": "neo4j",
                "NEO4J_PASSWORD": "dev_password",
                "REDIS_URL": "redis://host.docker.internal:6379/1",
            },
            metadata={"profile": "integration"},
            resource={"cpu": "2", "memory": "2Gi"},
            network_policy=runner.NetworkPolicy(
                defaultAction="deny",
                egress=[
                    runner.NetworkRule(action="allow", target="pypi.org"),
                    runner.NetworkRule(action="allow", target="files.pythonhosted.org"),
                    runner.NetworkRule(action="allow", target="registry.npmjs.org"),
                    runner.NetworkRule(action="allow", target="host.docker.internal"),
                ],
            ),
            volumes=[
                runner.Volume(
                    name="workspace",
                    host=runner.Host(path=runner.resolve_project_root()),
                    mountPath="/workspace",
                    readOnly=False,
                )
            ],
            connection_config=mock_cfg,
        )

    def test_retry_on_pool_exhaustion(self, runner):
        mock_sandbox = MagicMock()
        mock_cfg = MagicMock()
        with patch.object(
            runner.SandboxSync,
            "create",
            side_effect=[RuntimeError("pool exhausted"), mock_sandbox],
        ) as mock_create:
            with patch("sandbox_runner.time.sleep"):
                result = runner.setup_sandbox(mock_cfg, "lite")
        assert result is mock_sandbox
        assert mock_create.call_count == 2

    def test_raises_after_max_retries(self, runner):
        mock_cfg = MagicMock()
        with patch.object(
            runner.SandboxSync,
            "create",
            side_effect=RuntimeError("pool exhausted"),
        ) as mock_create:
            with patch("sandbox_runner.time.sleep"), pytest.raises(RuntimeError, match="pool"):
                runner.setup_sandbox(mock_cfg, "lite")
        assert mock_create.call_count == runner.MAX_RETRIES + 1


class TestExecuteInSandbox:
    def test_direct_python_tool_commands_run_through_uv(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0

        runner.execute_in_sandbox(mock_sandbox, ["ruff", "check", "src/"])

        mock_sandbox.commands.run.assert_called_once_with(
            "uv run ruff check src/",
            opts=runner.RunCommandOpts(
                working_directory="/workspace",
                envs={"OPENSANDBOX": "1"},
            ),
        )

    def test_execute_forwards_stdout_and_stderr(self, runner, capsys):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0
        mock_sandbox.commands.run.return_value.stdout = "command output\n"
        mock_sandbox.commands.run.return_value.stderr = "command warning\n"

        exit_code = runner.execute_in_sandbox(mock_sandbox, ["echo", "test"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == "command output\n"
        assert captured.err == "command warning\n"

    def test_execute_parameters_and_exit_code_propagation(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 42

        exit_code = runner.execute_in_sandbox(
            mock_sandbox,
            ["echo", "test"],
            working_dir="/workspace/subdir",
        )

        assert exit_code == 42

    def test_execute_default_working_dir(self, runner):
        mock_sandbox = MagicMock()
        mock_sandbox.commands.run.return_value.exit_code = 0

        runner.execute_in_sandbox(mock_sandbox, ["echo", "test"])

        mock_sandbox.commands.run.assert_called_once_with(
            "echo test",
            opts=runner.RunCommandOpts(
                working_directory="/workspace",
                envs={"OPENSANDBOX": "1"},
            ),
        )


class TestTeardownSandbox:
    def test_successful_teardown(self, runner):
        mock_sandbox = MagicMock()
        runner.teardown_sandbox(mock_sandbox)
        mock_sandbox.kill.assert_called_once_with()

    def test_teardown_failure_does_not_raise(self, runner, capsys):
        mock_sandbox = MagicMock()
        mock_sandbox.kill.side_effect = RuntimeError("kill failed")
        mock_sandbox.id = "sandbox-123"
        runner.teardown_sandbox(mock_sandbox)
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "kill failed" in captured.err
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

Test database creation cannot live in the static `docker/postgres/init.sql`
(plain SQL run by psql cannot read the `TEST_DB_NAME` env var). The actual
implementation keeps `init.sql` minimal (extensions only) and delegates DB
creation + schema application to `docker/postgres/zz-apply-schema.sh`, which
honors `TEST_DB_NAME` (default `context_store_test`):

```bash
# docker/postgres/zz-apply-schema.sh (excerpt)
apply_schema "${POSTGRES_DB:-context_store}"
ensure_database "${TEST_DB_NAME:-context_store_test}"
apply_schema "${TEST_DB_NAME:-context_store_test}"

-- Switch to test database and apply the same schema
```
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

import pytest


    @pytest.fixture
    def sandbox_aware_sqlite_env(
    clean_env,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    ) -> None:
    if request.node.name == "test_sandbox_aware_sqlite_activates":
        monkeypatch.setenv("OPENSANDBOX", "1")
    else:
        monkeypatch.delenv("OPENSANDBOX", raising=False)


class TestSandboxAwareSqlite:
    def test_sandbox_aware_sqlite_activates(self, tmp_path):
        """OPENSANDBOX=1 の場合、SQLITE_DB_PATH が tmp_path に設定される。"""
        assert os.environ["SQLITE_DB_PATH"] == str(tmp_path / "test.db")

    def test_sandbox_aware_sqlite_inactive_without_env(self, tmp_path):
        """OPENSANDBOX が未設定の場合、SQLITE パスは変更されない。"""
        assert os.environ.get("SQLITE_DB_PATH") is None
```

- NOTE: The autouse `_sandbox_aware_sqlite` fixture lives in the root
  `tests/conftest.py`; this test drives it via a local `sandbox_aware_sqlite_env`
  override (which depends on `clean_env` to force ordering). Only `SQLITE_DB_PATH`
  is asserted — `SQLITE_GRAPH_PATH` is not used by the codebase (single SQLite file).

- [ ] **Step 2: Run the tests to verify baseline**

Run: `uv run pytest tests/unit/test_conftest_sandbox.py -v`
Expected: Tests PASS once the root fixture below is in place.

- [ ] **Step 3: Add the fixture to conftest.py**

Add `import os` to the top of `tests/conftest.py` (after the existing imports), and append the helper function and fixture after the existing `anyio_backend` fixture:

```python
import os

# ... existing code ...

@pytest.fixture(autouse=True)
def _sandbox_aware_sqlite(tmp_path, monkeypatch, sandbox_aware_sqlite_env):
    """Ensure SQLite tests use temp paths inside sandbox (OPENSANDBOX=1 only)."""
    if os.environ.get("OPENSANDBOX") == "1":
        monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
```

Also update `tests/unit/conftest.py::clean_env` to skip deleting `SQLITE_DB_PATH`
when `OPENSANDBOX=1`, so the path switch survives regardless of fixture order.
Only `SQLITE_DB_PATH` is set; there is no `sqlite_graph_path` Settings field, so
`SQLITE_GRAPH_PATH` would be a no-op and is intentionally omitted.

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
