# MCP Gateway 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 設計書 `docs/superpowers/specs/2026-04-30-mcp-gateway-design.md` に基づき、外部AIエージェントと既存 `src/context_store/` の間に位置する MCP ゲートウェイ (ZSP / IBAC / 出力フィルタ) を `src/mcp_gateway/` 新規パッケージとして実装する。

**Architecture:** FastAPI + MCP SSE トランスポート (`GET /sse` + `POST /messages?session_id=...`) を入口とし、`AgentAuthenticator` / `SessionRegistry` / `PolicyEngine` / `OutputFilter` / 上流 stdio MCP クライアントの責務分離プロトコル群で構成する。`src/context_store/` は **Python レベルで一切 import しない** (subprocess 経由のみ) ことで「無変更保証」を構造的に担保する。

**Tech Stack:** Python 3.12 / `uv` / FastAPI / `sse-starlette` / `mcp[cli]` SDK (stdio クライアント) / Pydantic v2 / pytest + pytest-asyncio / mypy strict / ruff。

**実行環境:** すべてのテスト・静的解析は **devcontainer 内で `uv run ...` 経由で実行する**。ローカルPython環境は使用しない。

---

## Git ワークフロー

- **Phase ブランチ**: `master` から派生。`feature/phase1_mcp_gateway_foundation__base` / `feature/phase2_mcp_gateway_authz__base` / `feature/phase3_mcp_gateway_integration__base`
- **Task ブランチ**: 命名 `feature/phase{N}-task{Y}_<slug>`。各 Task の派生元は本計画内の「派生元」欄に従う。
- **Draft PR**: 各 Task 完了時に **Phase Base ブランチをターゲットとした Draft PR** を作成。Phase 完了時に `master` をターゲットとした Draft PR を作成。
- 前の Phase が `master` にマージされるまで次の Phase の作業に進まない。

---

## Phase 0 (省略)

`.github/workflows/ci.yml` (master/main を含む push/PR トリガ、`ubuntu-latest` ランナー、`uv sync --all-extras --dev` → `ruff check` → `ruff format --check` → `mypy` → `pytest tests/unit -v --cov=...` の順) と `.devcontainer/{devcontainer.json,Dockerfile}` (Python 3.12 / `uv` 0.4.0 / `vscode` ユーザ) が既に整備済みのため、Phase 0 は実施しない。新規パッケージ `src/mcp_gateway/` のテストは既存 CI の `tests/unit -v` および `mypy src/` でそのまま対象になる。

---

## Phase 1: Foundation (基盤レイヤ)

**Phase Base:** `feature/phase1_mcp_gateway_foundation__base` (← `master` から派生)

依存関係を持たない最小単位の3タスク。すべて Phase Base から独立派生する。

### Task 1.1: パッケージ雛形・依存関係・エラー階層

**派生元:** `feature/phase1_mcp_gateway_foundation__base` (Base派生 / 単体完結)

**Branch:** `feature/phase1-task1_scaffold_and_deps`

**Files:**
- Create: `src/mcp_gateway/__init__.py`
- Create: `src/mcp_gateway/py.typed` (空ファイル)
- Create: `src/mcp_gateway/errors.py`
- Modify: `pyproject.toml` (依存追加・パッケージ登録・mypy override 追加)
- Test: `tests/unit/test_mcp_gateway.py` (新規・以降のタスクで追記)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master
git pull origin master
git checkout -b feature/phase1_mcp_gateway_foundation__base
git push -u origin feature/phase1_mcp_gateway_foundation__base
git checkout -b feature/phase1-task1_scaffold_and_deps
```

- [ ] **Step 2: パッケージマーカーと型情報ファイルを作成**

`src/mcp_gateway/__init__.py`:

```python
"""ChronosGraph MCP Gateway: ZSP / IBAC / output-filter proxy in front of context_store."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

`src/mcp_gateway/py.typed`: 空ファイル(PEP 561)。

```bash
touch src/mcp_gateway/py.typed
```

- [ ] **Step 3: 失敗するテスト(エラー階層)を書く**

`tests/unit/test_mcp_gateway.py`:

```python
"""Unit tests for src/mcp_gateway/."""

from __future__ import annotations

import pytest


class TestErrors:
    def test_gateway_error_is_exception(self) -> None:
        from mcp_gateway.errors import GatewayError

        assert issubclass(GatewayError, Exception)

    def test_auth_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import AuthError, GatewayError

        assert issubclass(AuthError, GatewayError)

    def test_policy_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, PolicyError

        assert issubclass(PolicyError, GatewayError)

    def test_session_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, SessionError

        assert issubclass(SessionError, GatewayError)

    def test_upstream_error_inherits_gateway_error(self) -> None:
        from mcp_gateway.errors import GatewayError, UpstreamError

        assert issubclass(UpstreamError, GatewayError)
```

- [ ] **Step 4: テストが「ImportError」で失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestErrors -v
```

期待: 全てのテストが ModuleNotFoundError(`mcp_gateway.errors`) で FAIL。

- [ ] **Step 5: エラー階層を実装**

`src/mcp_gateway/errors.py`:

```python
"""Gateway error hierarchy.

すべてのゲートウェイ起点エラーは GatewayError を共通基底とする。
HTTP 層では catch-all で 500 にフォールバックさせず、原因種別を出し分けるために細分化する。
"""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for all mcp_gateway errors."""


class AuthError(GatewayError):
    """API key validation failure (HTTP 401)."""


class PolicyError(GatewayError):
    """Intent / capabilities policy violation or invalid policy DSL (HTTP 403 or startup fail)."""


class SessionError(GatewayError):
    """Session lookup miss / TTL expiry / idle timeout (HTTP 404)."""


class UpstreamError(GatewayError):
    """Upstream context_store subprocess failure or protocol error."""
```

- [ ] **Step 6: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestErrors -v
```

期待: 5件すべて PASS。

- [ ] **Step 7: `pyproject.toml` を更新 (依存追加・パッケージ登録・mypy override)**

以下の3ヶ所を編集する。

(a) `[project] dependencies` の末尾に追加:

```toml
[project]
dependencies = [
    "mcp[cli]>=1.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
    "aiosqlite>=0.21.0",
    "sqlite-vec>=0.1.0",
    "tenacity>=8.0.0",
    "tiktoken>=0.6.0",
    "filelock>=3.13.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sse-starlette>=2.1.0",
    "pyyaml>=6.0",
]
```

注: `fastapi` / `uvicorn` は既存の `[project.optional-dependencies] dashboard` から複製される形になるが、`mcp_gateway` でも必須となるため通常依存に昇格させる(dashboard extras 配下の定義は冪等で残す)。

(b) `[project.scripts]` にエントリポイントを追加:

```toml
[project.scripts]
context-store = "context_store.__main__:main"
chronos-dashboard = "context_store.dashboard.api_server:main"
chronos-mcp-gateway = "mcp_gateway.__main__:main"
```

(c) wheel ターゲットに `src/mcp_gateway` を追加:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/context_store", "src/mcp_gateway"]
```

(d) mypy override (`yaml.*` / `sse_starlette.*`) を追加:

```toml
[[tool.mypy.overrides]]
module = "sse_starlette.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "yaml.*"
ignore_missing_imports = true
```

- [ ] **Step 8: `uv sync` で lock 更新と依存解決**

```bash
uv sync --all-extras --dev
```

期待: `fastapi` / `sse-starlette` / `pyyaml` などが解決され、エラーなく完了。

- [ ] **Step 9: 静的解析・テストの全体パスを確認**

```bash
uv run ruff check src/mcp_gateway/ tests/unit/test_mcp_gateway.py
uv run ruff format --check src/mcp_gateway/ tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/
uv run pytest tests/unit/test_mcp_gateway.py -v
```

期待: 全て警告ゼロ・PASS。

- [ ] **Step 10: コミット**

```bash
git add src/mcp_gateway/ tests/unit/test_mcp_gateway.py pyproject.toml uv.lock
git commit -m "feat(mcp_gateway): scaffold package, deps, error hierarchy"
```

- [ ] **Step 11: Draft PR を Phase Base に向けて作成**

```bash
git push -u origin feature/phase1-task1_scaffold_and_deps
gh pr create --draft --base feature/phase1_mcp_gateway_foundation__base \
  --title "feat(mcp_gateway): scaffold package, deps, error hierarchy" \
  --body "$(cat <<'EOF'
## Summary
- Add `src/mcp_gateway/` package skeleton (`__init__.py`, `py.typed`).
- Add error hierarchy `GatewayError` / `AuthError` / `PolicyError` / `SessionError` / `UpstreamError`.
- Update `pyproject.toml`: add `fastapi`, `sse-starlette`, `pyyaml` deps; register wheel target & `chronos-mcp-gateway` script; add mypy overrides.

## Test plan
- [x] `uv run pytest tests/unit/test_mcp_gateway.py::TestErrors -v` → 5 pass
- [x] `uv run ruff check src/mcp_gateway/` clean
- [x] `uv run mypy src/mcp_gateway/` clean
EOF
)"
```

---

### Task 1.2: 設定 (`config.py`)

**派生元:** `feature/phase1_mcp_gateway_foundation__base` (Base派生 / Task 1.1 のスキャフォールドはマージ前でも参照可だが、ロジックとしては独立)

**Branch:** `feature/phase1-task2_config`

**Files:**
- Create: `src/mcp_gateway/config.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestSettings` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_mcp_gateway_foundation__base
git pull origin feature/phase1_mcp_gateway_foundation__base
git checkout -b feature/phase1-task2_config
```

- [ ] **Step 2: 失敗するテストを追加**

`tests/unit/test_mcp_gateway.py` に追記:

```python
class TestSettings:
    def test_required_policy_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MCP_GATEWAY_POLICY_PATH", raising=False)
        from mcp_gateway.config import GatewaySettings

        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            GatewaySettings()

    def test_loads_from_env(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_HOST", "0.0.0.0")  # noqa: S104
        monkeypatch.setenv("MCP_GATEWAY_PORT", "9999")
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_xxx"}')

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()
        assert s.host == "0.0.0.0"  # noqa: S104
        assert s.port == 9999
        assert s.policy_path == policy
        assert s.session_ttl_seconds == 900
        assert s.session_idle_timeout_seconds == 300
        assert s.upstream_command == ["python", "-m", "context_store"]

    def test_api_keys_secret_not_in_repr(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_secret"}')

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()
        assert "ck_secret" not in repr(s)
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestSettings -v
```

期待: ImportError で FAIL。

- [ ] **Step 4: `config.py` を実装**

`src/mcp_gateway/config.py`:

```python
"""Pydantic Settings for the MCP gateway.

Environment variables are prefixed `MCP_GATEWAY_`.
`policy_path` is mandatory — refusing to start without a policy enforces Default Deny.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Runtime configuration for the MCP gateway."""

    model_config = SettingsConfigDict(
        env_prefix="MCP_GATEWAY_",
        env_file=".env",
        extra="ignore",
    )

    # ── HTTP server ─────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 9100

    # ── internal session ─────────────────────────────────────────
    session_ttl_seconds: int = 900
    session_idle_timeout_seconds: int = 300
    session_issuer: str = "chronos-mcp-gateway"

    # ── auth ─────────────────────────────────────────────────────
    # JSON-encoded mapping {"agent_id": "raw_api_key"}
    api_keys_json: SecretStr | None = None

    # ── policy ───────────────────────────────────────────────────
    policy_path: Path

    # ── upstream (context_store) ─────────────────────────────────
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY",
        "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED",
        "EMBEDDING_PROVIDER",
    ]

    # ── audit ────────────────────────────────────────────────────
    audit_log_level: Literal["INFO", "DEBUG"] = "INFO"
```

- [ ] **Step 5: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestSettings -v
```

期待: 3件 PASS。

- [ ] **Step 6: 静的解析を確認**

```bash
uv run ruff check src/mcp_gateway/config.py tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/
```

期待: クリーン。

- [ ] **Step 7: コミット & Draft PR**

```bash
git add src/mcp_gateway/config.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add GatewaySettings (Pydantic Settings)"
git push -u origin feature/phase1-task2_config
gh pr create --draft --base feature/phase1_mcp_gateway_foundation__base \
  --title "feat(mcp_gateway): add GatewaySettings" \
  --body "Pydantic Settings backed by MCP_GATEWAY_* env vars. policy_path is required (fail-fast)."
```

---

### Task 1.3: ポリシー DSL (`policy/models.py`, `policy/loader.py`)

**派生元:** `feature/phase1_mcp_gateway_foundation__base` (Base派生 / 単体完結)

**Branch:** `feature/phase1-task3_policy_models_loader`

**Files:**
- Create: `src/mcp_gateway/policy/__init__.py`
- Create: `src/mcp_gateway/policy/models.py`
- Create: `src/mcp_gateway/policy/loader.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestPolicyLoader` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase1_mcp_gateway_foundation__base
git pull origin feature/phase1_mcp_gateway_foundation__base
git checkout -b feature/phase1-task3_policy_models_loader
```

- [ ] **Step 2: 失敗するテストを追加**

`tests/unit/test_mcp_gateway.py` に追記:

```python
import textwrap


class TestPolicyLoader:
    def _write(self, tmp_path, body: str):
        p = tmp_path / "intents.yaml"
        p.write_text(textwrap.dedent(body).lstrip())
        return p

    def test_loads_minimal_policy(self, tmp_path):
        p = self._write(tmp_path, """
            version: 1
            output_filters:
              recall_safe:
                type: structural_allowlist
                schemas:
                  memory_search:
                    results: [id, content]
                    total_count: true
            intents:
              read_only_recall:
                description: "test"
                allowed_tools: [memory_search]
                output_filter: recall_safe
            agents:
              test-agent:
                allowed_intents: [read_only_recall]
        """)

        from mcp_gateway.policy.loader import load_policy

        pol = load_policy(p)
        assert pol.version == 1
        assert "read_only_recall" in pol.intents
        assert pol.intents["read_only_recall"].allowed_tools == ["memory_search"]
        assert pol.agents["test-agent"].allowed_intents == ["read_only_recall"]

    def test_unknown_output_filter_reference_fails_fast(self, tmp_path):
        p = self._write(tmp_path, """
            version: 1
            output_filters: {}
            intents:
              read_only_recall:
                description: "test"
                allowed_tools: [memory_search]
                output_filter: nonexistent
            agents: {}
        """)

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)

    def test_unknown_intent_reference_fails_fast(self, tmp_path):
        p = self._write(tmp_path, """
            version: 1
            output_filters:
              none_f:
                type: none
            intents:
              ok_intent:
                description: "x"
                allowed_tools: [memory_search]
                output_filter: none_f
            agents:
              bad-agent:
                allowed_intents: [ghost_intent]
        """)

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)

    def test_structural_allowlist_requires_schemas(self, tmp_path):
        p = self._write(tmp_path, """
            version: 1
            output_filters:
              broken:
                type: structural_allowlist
            intents: {}
            agents: {}
        """)

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)

    def test_schema_key_must_be_referenced_by_some_intent(self, tmp_path):
        # tools/list の typo を起動時に検知する
        p = self._write(tmp_path, """
            version: 1
            output_filters:
              rs:
                type: structural_allowlist
                schemas:
                  memory_searchhh:   # typo
                    results: [id]
            intents:
              i:
                description: "x"
                allowed_tools: [memory_search]
                output_filter: rs
            agents: {}
        """)

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.loader import load_policy

        with pytest.raises(PolicyError):
            load_policy(p)
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestPolicyLoader -v
```

期待: ImportError で全件 FAIL。

- [ ] **Step 4: `policy/__init__.py` を作成**

```python
"""Policy DSL: intents.yaml → in-memory typed model + IBAC engine."""
```

- [ ] **Step 5: `policy/models.py` を実装**

`src/mcp_gateway/policy/models.py`:

```python
"""Pydantic models for intents.yaml.

References are validated post-parse (`_verify_references`) so the gateway refuses
to start with a malformed policy (Fail-fast / Default Deny).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class StructuralAllowlistSchema(BaseModel):
    # フィールド名 = True | list[str] (ネストの allowlist)
    # 動的キーを許すため extra="allow"。タイポ検出は GatewayPolicy._verify_references で実施。
    model_config = ConfigDict(extra="allow")


class OutputFilterDef(BaseModel):
    type: Literal["none", "structural_allowlist"]
    schemas: dict[str, StructuralAllowlistSchema] | None = None


class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str]
    output_filter: str


class AgentPolicy(BaseModel):
    allowed_intents: list[str]


class GatewayPolicy(BaseModel):
    version: Literal[1]
    output_filters: dict[str, OutputFilterDef]
    intents: dict[str, IntentPolicy]
    agents: dict[str, AgentPolicy]

    @model_validator(mode="after")
    def _verify_references(self) -> Self:
        # 1. intent.output_filter は output_filters に存在
        for iname, intent in self.intents.items():
            if intent.output_filter not in self.output_filters:
                raise ValueError(
                    f"intent {iname!r} references unknown output_filter {intent.output_filter!r}"
                )
        # 2. agent.allowed_intents は intents に存在
        for aname, agent in self.agents.items():
            for iname in agent.allowed_intents:
                if iname not in self.intents:
                    raise ValueError(
                        f"agent {aname!r} references unknown intent {iname!r}"
                    )
        # 3. structural_allowlist は schemas 必須
        for fname, fdef in self.output_filters.items():
            if fdef.type == "structural_allowlist" and not fdef.schemas:
                raise ValueError(
                    f"output_filter {fname!r} type=structural_allowlist requires schemas"
                )
        # 4. structural_allowlist の schema キーは、いずれかの intent.allowed_tools に含まれる
        all_allowed_tools: set[str] = {
            t for intent in self.intents.values() for t in intent.allowed_tools
        }
        for fname, fdef in self.output_filters.items():
            if fdef.type != "structural_allowlist" or fdef.schemas is None:
                continue
            for tool_name in fdef.schemas:
                if tool_name not in all_allowed_tools:
                    raise ValueError(
                        f"output_filter {fname!r} schema key {tool_name!r} is not "
                        "referenced by any intent.allowed_tools (typo?)"
                    )
        return self
```

- [ ] **Step 6: `policy/loader.py` を実装**

`src/mcp_gateway/policy/loader.py`:

```python
"""YAML → GatewayPolicy loader. Errors are normalized to PolicyError."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy


def load_policy(path: Path) -> GatewayPolicy:
    """Read intents.yaml and return a validated GatewayPolicy.

    Any parse / schema / reference error is wrapped in PolicyError so that the
    server entrypoint can fail fast with a single exception type.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PolicyError(f"failed to read policy file {path}: {e}") from e

    try:
        data: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise PolicyError(f"failed to parse YAML at {path}: {e}") from e

    if not isinstance(data, dict):
        raise PolicyError(f"policy root must be a mapping, got {type(data).__name__}")

    try:
        return GatewayPolicy.model_validate(data)
    except ValidationError as e:
        raise PolicyError(f"invalid policy at {path}: {e}") from e
```

- [ ] **Step 7: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestPolicyLoader -v
```

期待: 5件 PASS。

- [ ] **Step 8: 静的解析を確認**

```bash
uv run ruff check src/mcp_gateway/policy/ tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/
```

期待: クリーン。

- [ ] **Step 9: コミット & Draft PR**

```bash
git add src/mcp_gateway/policy/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add policy DSL models and YAML loader"
git push -u origin feature/phase1-task3_policy_models_loader
gh pr create --draft --base feature/phase1_mcp_gateway_foundation__base \
  --title "feat(mcp_gateway): policy DSL models + YAML loader" \
  --body "GatewayPolicy/IntentPolicy/etc with strict reference validation (fail-fast on typos)."
```

---

### Phase 1 完了アクション

- [ ] Phase 1 全 Task の Draft PR をマージ準備状態 (Ready for review) に切り替え、レビュー後 `feature/phase1_mcp_gateway_foundation__base` へマージ
- [ ] `master` をターゲットとした Draft PR を作成

```bash
git checkout feature/phase1_mcp_gateway_foundation__base
git pull
gh pr create --draft --base master \
  --title "feat(mcp_gateway): Phase 1 - foundation (scaffold/config/policy)" \
  --body "Phase 1 deliverables: package skeleton, errors, GatewaySettings, policy DSL & loader."
```

---

## Phase 2: Authorization Core (認可コア)

**Phase Base:** `feature/phase2_mcp_gateway_authz__base` (← Phase 1 が `master` にマージされた後、`master` から派生)

認証・セッション・ポリシー判定・出力フィルタ・ツールレジストリ・監査ロガを実装する。各モジュールはモック越しに独立検証可能なため、すべて Phase Base から独立派生する。

---

### Task 2.1: API キー認証 (`auth/protocol.py`, `auth/api_key.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task1_api_key_auth`

**Files:**
- Create: `src/mcp_gateway/auth/__init__.py`
- Create: `src/mcp_gateway/auth/protocol.py`
- Create: `src/mcp_gateway/auth/api_key.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestApiKeyAuthenticator` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master
git pull origin master
git checkout -b feature/phase2_mcp_gateway_authz__base
git push -u origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task1_api_key_auth
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestApiKeyAuthenticator:
    def test_resolves_known_agent(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        assert a.authenticate("ck_xxx") == "summarizer-bot"

    def test_unknown_key_raises_auth_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.errors import AuthError

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        with pytest.raises(AuthError):
            a.authenticate("ck_wrong")

    def test_empty_key_raises_auth_error(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.errors import AuthError

        a = ApiKeyAuthenticator({"summarizer-bot": "ck_xxx"})
        with pytest.raises(AuthError):
            a.authenticate("")

    def test_constant_time_comparison(self):
        # ck_aaa == ck_aaa は True、ck_aaa != ck_aab は False。実装が hmac.compare_digest を使うこと
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator

        a = ApiKeyAuthenticator({"x": "ck_aaa"})
        assert a.authenticate("ck_aaa") == "x"
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestApiKeyAuthenticator -v
```

期待: ImportError で FAIL。

- [ ] **Step 4: `auth/__init__.py` と `auth/protocol.py` を作成**

`src/mcp_gateway/auth/__init__.py`:

```python
"""Auth & session: agent identity resolution and short-lived gateway-internal sessions."""
```

`src/mcp_gateway/auth/protocol.py`:

```python
"""AgentAuthenticator protocol — pluggable agent identity resolution.

The current implementation is api_key (pre-shared bearer token), but mTLS / OIDC
implementations may be added later by satisfying this protocol.
"""

from __future__ import annotations

from typing import Protocol


class AgentAuthenticator(Protocol):
    """Resolve a raw bearer credential → agent_id, raising AuthError on failure."""

    def authenticate(self, raw_credential: str) -> str: ...
```

- [ ] **Step 5: `auth/api_key.py` を実装**

`src/mcp_gateway/auth/api_key.py`:

```python
"""Pre-shared API key authenticator (constant-time compare)."""

from __future__ import annotations

import hmac

from mcp_gateway.errors import AuthError


class ApiKeyAuthenticator:
    """Resolve raw bearer keys against an in-memory {agent_id: key} map.

    Comparison uses hmac.compare_digest so that mismatched keys do not leak
    information through timing side-channels.
    """

    def __init__(self, agent_keys: dict[str, str]) -> None:
        self._agent_keys = dict(agent_keys)

    def authenticate(self, raw_credential: str) -> str:
        if not raw_credential:
            raise AuthError("empty credential")
        for agent_id, expected in self._agent_keys.items():
            if hmac.compare_digest(raw_credential, expected):
                return agent_id
        raise AuthError("unknown api key")
```

- [ ] **Step 6: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestApiKeyAuthenticator -v
```

期待: 4件 PASS。

- [ ] **Step 7: 静的解析・コミット・Draft PR**

```bash
uv run ruff check src/mcp_gateway/auth/ tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/auth/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add AgentAuthenticator protocol + ApiKeyAuthenticator"
git push -u origin feature/phase2-task1_api_key_auth
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): API key authenticator" \
  --body "AgentAuthenticator protocol + constant-time api_key implementation."
```

---

### Task 2.2: ヘッダパース (`auth/headers.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task2_header_parsing`

**Files:**
- Create: `src/mcp_gateway/auth/headers.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestHeaderParsing` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task2_header_parsing
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestHeaderParsing:
    def test_parse_bearer_token(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("Bearer ck_abc") == "ck_abc"

    def test_parse_bearer_case_insensitive_scheme(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer("bearer ck_abc") == "ck_abc"

    def test_parse_bearer_missing_returns_none(self):
        from mcp_gateway.auth.headers import parse_bearer

        assert parse_bearer(None) is None
        assert parse_bearer("") is None
        assert parse_bearer("Basic xxx") is None

    def test_parse_intent(self):
        from mcp_gateway.auth.headers import parse_intent

        assert parse_intent("read_only_recall") == "read_only_recall"
        assert parse_intent("  read_only_recall  ") == "read_only_recall"
        assert parse_intent("") is None
        assert parse_intent(None) is None

    def test_parse_requested_tools(self):
        from mcp_gateway.auth.headers import parse_requested_tools

        assert parse_requested_tools("memory_search,memory_save") == frozenset(
            {"memory_search", "memory_save"}
        )
        assert parse_requested_tools("memory_search , memory_save ") == frozenset(
            {"memory_search", "memory_save"}
        )
        assert parse_requested_tools("memory_search,memory_search") == frozenset(
            {"memory_search"}
        )
        assert parse_requested_tools("") is None
        assert parse_requested_tools(None) is None
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestHeaderParsing -v
```

- [ ] **Step 4: `auth/headers.py` を実装**

```python
"""HTTP header parsing for SSE handshake.

`Authorization: Bearer <key>`, `X-MCP-Intent: <intent>`,
`X-MCP-Requested-Tools: tool_a,tool_b` (optional) を扱う。
"""

from __future__ import annotations


def parse_bearer(header_value: str | None) -> str | None:
    """Return the raw token from `Bearer <token>`. Case-insensitive scheme."""
    if not header_value:
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def parse_intent(header_value: str | None) -> str | None:
    if header_value is None:
        return None
    v = header_value.strip()
    return v or None


def parse_requested_tools(header_value: str | None) -> frozenset[str] | None:
    if not header_value:
        return None
    parts = {p.strip() for p in header_value.split(",")}
    parts.discard("")
    if not parts:
        return None
    return frozenset(parts)
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestHeaderParsing -v
uv run ruff check src/mcp_gateway/auth/headers.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/auth/headers.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add SSE handshake header parsers"
git push -u origin feature/phase2-task2_header_parsing
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): SSE handshake header parsers" \
  --body "Authorization / X-MCP-Intent / X-MCP-Requested-Tools parsing helpers."
```

---

### Task 2.3: セッション (`auth/session.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task3_session`

**Files:**
- Create: `src/mcp_gateway/auth/session.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestSessionLifecycle` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task3_session
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestSessionLifecycle:
    def _make_registry(self, ttl: int = 60, idle: int = 30):
        from mcp_gateway.auth.session import InMemorySessionRegistry

        return InMemorySessionRegistry(ttl_seconds=ttl, idle_timeout_seconds=idle)

    def test_create_and_lookup(self):
        from mcp_gateway.auth.session import SessionRecord

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a",
            intent="read_only_recall",
            caps=frozenset({"memory_search"}),
            output_filter_profile="recall_safe",
        )
        assert isinstance(rec, SessionRecord)
        assert reg.lookup(rec.session_id) is rec

    def test_lookup_unknown_raises(self):
        from mcp_gateway.errors import SessionError

        reg = self._make_registry()
        with pytest.raises(SessionError):
            reg.lookup("nonexistent")

    def test_ttl_expiry(self, monkeypatch):
        from datetime import datetime, timedelta, UTC
        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=10)
        rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        future = rec.expires_at + timedelta(seconds=1)
        monkeypatch.setattr(sess, "_utcnow", lambda: future)
        from mcp_gateway.errors import SessionError

        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_idle_timeout(self, monkeypatch):
        from datetime import timedelta
        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=600, idle=5)
        rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        original = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=10))
        from mcp_gateway.errors import SessionError

        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_touch_resets_idle(self, monkeypatch):
        from datetime import timedelta
        import mcp_gateway.auth.session as sess

        reg = self._make_registry(ttl=600, idle=5)
        rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        original = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=3))
        reg.touch(rec.session_id)
        monkeypatch.setattr(sess, "_utcnow", lambda: original + timedelta(seconds=7))
        # 3秒時にtouch → 7秒時はtouchから4秒経過 → idle=5秒未満なので有効
        assert reg.lookup(rec.session_id).session_id == rec.session_id

    def test_remove(self):
        from mcp_gateway.errors import SessionError

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        reg.remove(rec.session_id)
        with pytest.raises(SessionError):
            reg.lookup(rec.session_id)

    def test_session_record_is_frozen(self):
        from dataclasses import FrozenInstanceError
        from mcp_gateway.auth.session import SessionRecord

        reg = self._make_registry()
        rec = reg.create(
            agent_id="a", intent="i", caps=frozenset(), output_filter_profile="none_f"
        )
        with pytest.raises(FrozenInstanceError):
            rec.agent_id = "other"  # type: ignore[misc]
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestSessionLifecycle -v
```

- [ ] **Step 4: `auth/session.py` を実装**

```python
"""Internal session record + in-memory registry.

The agent never sees this record; it only knows its session_id.
TTL / idle-timeout failures all surface as SessionError so the HTTP layer can
return a uniform 404 + close the SSE stream.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from mcp_gateway.errors import SessionError


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    agent_id: str
    intent: str
    caps: frozenset[str]
    output_filter_profile: str
    issued_at: datetime
    expires_at: datetime


class SessionRegistry(Protocol):
    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: frozenset[str],
        output_filter_profile: str,
    ) -> SessionRecord: ...

    def lookup(self, session_id: str) -> SessionRecord: ...

    def touch(self, session_id: str) -> None: ...

    def remove(self, session_id: str) -> None: ...


class InMemorySessionRegistry:
    """Process-local registry. Replaceable later with a Redis-backed implementation."""

    def __init__(self, ttl_seconds: int, idle_timeout_seconds: int) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._idle = timedelta(seconds=idle_timeout_seconds)
        self._records: dict[str, SessionRecord] = {}
        self._last_active: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        agent_id: str,
        intent: str,
        caps: frozenset[str],
        output_filter_profile: str,
    ) -> SessionRecord:
        now = _utcnow()
        sid = uuid.uuid4().hex
        rec = SessionRecord(
            session_id=sid,
            agent_id=agent_id,
            intent=intent,
            caps=caps,
            output_filter_profile=output_filter_profile,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._records[sid] = rec
            self._last_active[sid] = now
        return rec

    def lookup(self, session_id: str) -> SessionRecord:
        now = _utcnow()
        with self._lock:
            rec = self._records.get(session_id)
            if rec is None:
                raise SessionError(f"unknown session_id {session_id!r}")
            if now >= rec.expires_at:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                raise SessionError("session expired (ttl)")
            last = self._last_active.get(session_id, rec.issued_at)
            if now - last >= self._idle:
                self._records.pop(session_id, None)
                self._last_active.pop(session_id, None)
                raise SessionError("session expired (idle)")
        return rec

    def touch(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._records:
                self._last_active[session_id] = _utcnow()

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)
            self._last_active.pop(session_id, None)
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestSessionLifecycle -v
uv run ruff check src/mcp_gateway/auth/session.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/auth/session.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add SessionRecord and InMemorySessionRegistry"
git push -u origin feature/phase2-task3_session
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): in-memory session registry with TTL + idle timeout" \
  --body "Frozen SessionRecord, thread-safe InMemorySessionRegistry, SessionError on miss/expiry."
```

---

### Task 2.4: ポリシーエンジン (`policy/engine.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task4_policy_engine`

**Files:**
- Create: `src/mcp_gateway/policy/engine.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestPolicyEngine` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task4_policy_engine
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestPolicyEngine:
    def _policy(self):
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        return GatewayPolicy(
            version=1,
            output_filters={
                "rs": OutputFilterDef(type="none"),
            },
            intents={
                "read_only_recall": IntentPolicy(
                    description="x",
                    allowed_tools=["memory_search", "memory_stats"],
                    output_filter="rs",
                ),
            },
            agents={
                "agent-a": AgentPolicy(allowed_intents=["read_only_recall"]),
            },
        )

    def test_evaluate_grant_allows_subset(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        grant = eng.evaluate_grant(
            agent_id="agent-a",
            intent="read_only_recall",
            requested_tools=frozenset({"memory_search"}),
        )
        assert grant.caps == frozenset({"memory_search"})
        assert grant.output_filter_profile == "rs"

    def test_evaluate_grant_full_when_no_request(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        grant = eng.evaluate_grant(
            agent_id="agent-a", intent="read_only_recall", requested_tools=None
        )
        assert grant.caps == frozenset({"memory_search", "memory_stats"})

    def test_unknown_agent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(
                agent_id="ghost", intent="read_only_recall", requested_tools=None
            )

    def test_intent_not_allowed_for_agent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(
                agent_id="agent-a", intent="curate_memories", requested_tools=None
            )

    def test_requested_tools_outside_intent_denied(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.evaluate_grant(
                agent_id="agent-a",
                intent="read_only_recall",
                requested_tools=frozenset({"memory_save"}),
            )

    def test_check_call_allows_in_caps(self):
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        eng.check_call(caps=frozenset({"memory_search"}), tool_name="memory_search")

    def test_check_call_denies_outside_caps(self):
        from mcp_gateway.errors import PolicyError
        from mcp_gateway.policy.engine import PolicyEngine

        eng = PolicyEngine(self._policy())
        with pytest.raises(PolicyError):
            eng.check_call(
                caps=frozenset({"memory_search"}), tool_name="memory_save"
            )
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestPolicyEngine -v
```

- [ ] **Step 4: `policy/engine.py` を実装**

```python
"""IBAC engine: pure functions over a GatewayPolicy.

evaluate_grant() is invoked at SSE handshake time and computes the effective
capability set. check_call() is invoked at every tools/call before delegating
to the upstream subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy


@dataclass(frozen=True, slots=True)
class Grant:
    intent: str
    caps: frozenset[str]
    output_filter_profile: str


class PolicyEngine:
    def __init__(self, policy: GatewayPolicy) -> None:
        self._policy = policy

    def evaluate_grant(
        self,
        *,
        agent_id: str,
        intent: str,
        requested_tools: frozenset[str] | None,
    ) -> Grant:
        agent = self._policy.agents.get(agent_id)
        if agent is None:
            raise PolicyError(f"agent {agent_id!r} is not registered")
        if intent not in agent.allowed_intents:
            raise PolicyError(f"agent {agent_id!r} cannot use intent {intent!r}")
        intent_pol = self._policy.intents.get(intent)
        if intent_pol is None:
            raise PolicyError(f"unknown intent {intent!r}")
        allowed = frozenset(intent_pol.allowed_tools)
        if requested_tools is None:
            caps = allowed
        else:
            extra = requested_tools - allowed
            if extra:
                raise PolicyError(
                    f"requested tools {sorted(extra)!r} are outside intent {intent!r}"
                )
            caps = requested_tools
        return Grant(
            intent=intent, caps=caps, output_filter_profile=intent_pol.output_filter
        )

    def check_call(self, *, caps: frozenset[str], tool_name: str) -> None:
        if tool_name not in caps:
            raise PolicyError(f"tool {tool_name!r} is not in session capabilities")
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestPolicyEngine -v
uv run ruff check src/mcp_gateway/policy/engine.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/policy/engine.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add IBAC PolicyEngine (evaluate_grant / check_call)"
git push -u origin feature/phase2-task4_policy_engine
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): IBAC PolicyEngine" \
  --body "Pure-function evaluate_grant + check_call. Hybrid intent ∩ requested_tools narrowing."
```

---

### Task 2.5: 出力フィルタ (`filters/*`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task5_output_filters`

**Files:**
- Create: `src/mcp_gateway/filters/__init__.py`
- Create: `src/mcp_gateway/filters/protocol.py`
- Create: `src/mcp_gateway/filters/none_filter.py`
- Create: `src/mcp_gateway/filters/structural_allowlist.py`
- Create: `src/mcp_gateway/filters/factory.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestStructuralAllowlistFilter` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task5_output_filters
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestStructuralAllowlistFilter:
    def _filter(self):
        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter

        return StructuralAllowlistFilter(
            schemas={
                "memory_search": {
                    "results": ["id", "content"],
                    "total_count": True,
                },
            }
        )

    def test_strips_unlisted_top_level_fields(self):
        f = self._filter()
        out = f.apply(
            tool_name="memory_search",
            payload={"results": [], "total_count": 0, "secret": "x"},
        )
        assert out == {"results": [], "total_count": 0}

    def test_strips_unlisted_nested_fields(self):
        f = self._filter()
        out = f.apply(
            tool_name="memory_search",
            payload={
                "results": [
                    {
                        "id": "m1",
                        "content": "hello",
                        "embedding": [0.1, 0.2],
                        "internal_score": 0.9,
                    }
                ],
                "total_count": 1,
            },
        )
        assert out["results"][0] == {"id": "m1", "content": "hello"}
        assert out["total_count"] == 1

    def test_unknown_tool_returns_empty_payload(self):
        # スキーマがない=露出禁止
        f = self._filter()
        out = f.apply(tool_name="memory_save", payload={"x": 1})
        assert out == {}


class TestNoneFilter:
    def test_passthrough(self):
        from mcp_gateway.filters.none_filter import NoneFilter

        f = NoneFilter()
        payload = {"a": 1, "b": [{"c": 2}]}
        assert f.apply(tool_name="any", payload=payload) == payload


class TestFilterFactory:
    def test_factory_builds_none(self):
        from mcp_gateway.filters.factory import build_filter
        from mcp_gateway.policy.models import OutputFilterDef

        f = build_filter(OutputFilterDef(type="none"))
        assert f.apply(tool_name="x", payload={"a": 1}) == {"a": 1}

    def test_factory_builds_structural_allowlist(self):
        from mcp_gateway.filters.factory import build_filter
        from mcp_gateway.policy.models import OutputFilterDef

        f = build_filter(
            OutputFilterDef(
                type="structural_allowlist",
                schemas={"t": {"id": True}},  # type: ignore[arg-type]
            )
        )
        out = f.apply(tool_name="t", payload={"id": 1, "x": 2})
        assert out == {"id": 1}
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -k "Filter" -v
```

- [ ] **Step 4: `filters/__init__.py` と `filters/protocol.py` を作成**

`src/mcp_gateway/filters/__init__.py`:

```python
"""Output filters: pluggable, deterministic, structure-based payload sanitizers."""
```

`src/mcp_gateway/filters/protocol.py`:

```python
"""OutputFilter protocol — applied after the upstream returns a tool payload."""

from __future__ import annotations

from typing import Any, Protocol


class OutputFilter(Protocol):
    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]: ...
```

- [ ] **Step 5: `filters/none_filter.py` を実装**

```python
"""Null filter — passthrough. Used for trusted intents (e.g. curator)."""

from __future__ import annotations

from typing import Any


class NoneFilter:
    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return payload
```

- [ ] **Step 6: `filters/structural_allowlist.py` を実装**

```python
"""Structural allowlist filter.

Each tool gets a schema describing which fields are allowed at each level.
A schema entry can be:
  - True       → keep this scalar / list / dict as-is
  - list[str]  → for a nested dict (or list of dicts), keep only these subkeys
"""

from __future__ import annotations

from typing import Any


def _coerce_schema(schema_obj: Any) -> dict[str, Any]:
    if hasattr(schema_obj, "model_dump"):
        return schema_obj.model_dump()
    if isinstance(schema_obj, dict):
        return dict(schema_obj)
    return {}


def _filter_value(value: Any, allowed_subkeys: Any) -> Any:
    if allowed_subkeys is True:
        return value
    if isinstance(allowed_subkeys, list):
        keys = set(allowed_subkeys)
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k in keys}
        if isinstance(value, list):
            return [
                {k: v for k, v in item.items() if k in keys}
                if isinstance(item, dict)
                else item
                for item in value
            ]
    return value


class StructuralAllowlistFilter:
    def __init__(self, schemas: dict[str, Any]) -> None:
        self._schemas = {name: _coerce_schema(s) for name, s in schemas.items()}

    def apply(self, *, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = self._schemas.get(tool_name)
        if schema is None:
            return {}
        result: dict[str, Any] = {}
        for key, allowed in schema.items():
            if key not in payload:
                continue
            result[key] = _filter_value(payload[key], allowed)
        return result
```

- [ ] **Step 7: `filters/factory.py` を実装**

```python
"""Build an OutputFilter from a policy OutputFilterDef."""

from __future__ import annotations

from mcp_gateway.errors import PolicyError
from mcp_gateway.filters.none_filter import NoneFilter
from mcp_gateway.filters.protocol import OutputFilter
from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter
from mcp_gateway.policy.models import OutputFilterDef


def build_filter(definition: OutputFilterDef) -> OutputFilter:
    if definition.type == "none":
        return NoneFilter()
    if definition.type == "structural_allowlist":
        if definition.schemas is None:
            raise PolicyError("structural_allowlist requires schemas")
        return StructuralAllowlistFilter(schemas=dict(definition.schemas))
    raise PolicyError(f"unsupported output filter type: {definition.type!r}")
```

- [ ] **Step 8: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -k "Filter" -v
uv run ruff check src/mcp_gateway/filters/
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/filters/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add output filter framework (none + structural_allowlist)"
git push -u origin feature/phase2-task5_output_filters
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): output filter framework" \
  --body "OutputFilter protocol, NoneFilter, StructuralAllowlistFilter, factory."
```

---

### Task 2.6: ツールレジストリ (`tools/registry.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task6_tool_registry`

**Files:**
- Create: `src/mcp_gateway/tools/__init__.py`
- Create: `src/mcp_gateway/tools/registry.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestToolRegistry` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task6_tool_registry
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestToolRegistry:
    def test_filter_by_caps_default_deny(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(
            all_tools=[
                {"name": "memory_search", "description": "...", "inputSchema": {}},
                {"name": "memory_save", "description": "...", "inputSchema": {}},
                {"name": "memory_delete", "description": "...", "inputSchema": {}},
            ]
        )
        out = reg.filter_by_caps(caps=frozenset({"memory_search"}))
        names = [t["name"] for t in out]
        assert names == ["memory_search"]

    def test_filter_by_caps_empty_when_none_match(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(all_tools=[{"name": "memory_search"}])
        assert reg.filter_by_caps(caps=frozenset()) == []

    def test_filter_preserves_order(self):
        from mcp_gateway.tools.registry import ToolRegistry

        reg = ToolRegistry(
            all_tools=[
                {"name": "a"},
                {"name": "b"},
                {"name": "c"},
            ]
        )
        out = reg.filter_by_caps(caps=frozenset({"a", "c"}))
        assert [t["name"] for t in out] == ["a", "c"]
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestToolRegistry -v
```

- [ ] **Step 4: `tools/__init__.py` と `tools/registry.py` を実装**

`src/mcp_gateway/tools/__init__.py`:

```python
"""Tool registry + per-call proxy."""
```

`src/mcp_gateway/tools/registry.py`:

```python
"""ToolRegistry: cache the upstream's tools/list and apply Default Deny filtering."""

from __future__ import annotations

from typing import Any


class ToolRegistry:
    def __init__(self, all_tools: list[dict[str, Any]]) -> None:
        self._all = list(all_tools)

    @property
    def all_tools(self) -> list[dict[str, Any]]:
        return list(self._all)

    def filter_by_caps(self, *, caps: frozenset[str]) -> list[dict[str, Any]]:
        return [t for t in self._all if t.get("name") in caps]
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestToolRegistry -v
uv run ruff check src/mcp_gateway/tools/
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/tools/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add ToolRegistry with cap-based default-deny filter"
git push -u origin feature/phase2-task6_tool_registry
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): tool registry (default-deny filter)" \
  --body "Filter upstream tools/list by SessionRecord.caps."
```

---

### Task 2.7: 監査ロガ (`audit/logger.py`)

**派生元:** `feature/phase2_mcp_gateway_authz__base` (Base派生 / 単体完結)

**Branch:** `feature/phase2-task7_audit_logger`

**Files:**
- Create: `src/mcp_gateway/audit/__init__.py`
- Create: `src/mcp_gateway/audit/logger.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestAuditLogger` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull origin feature/phase2_mcp_gateway_authz__base
git checkout -b feature/phase2-task7_audit_logger
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestAuditLogger:
    def test_writes_jsonl_to_stderr(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        log.log(ev="handshake", agent="a", intent="i", decision="allow", sid="s1")
        captured = capsys.readouterr()
        # stdout は汚染しない
        assert captured.out == ""
        # stderr は1行 JSON
        line = captured.err.strip()
        import json
        rec = json.loads(line)
        assert rec["ev"] == "handshake"
        assert rec["agent"] == "a"
        assert rec["intent"] == "i"
        assert rec["decision"] == "allow"
        assert rec["sid"] == "s1"
        assert "ts" in rec

    def test_does_not_emit_secrets(self, capsys):
        from mcp_gateway.audit.logger import AuditLogger

        log = AuditLogger()
        # api_key 風のフィールドは渡されない設計なので、API として fields を制限する
        log.log(ev="call", agent="a", tool="memory_search", decision="allow")
        captured = capsys.readouterr()
        assert "ck_" not in captured.err
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestAuditLogger -v
```

- [ ] **Step 4: `audit/__init__.py` と `audit/logger.py` を実装**

`src/mcp_gateway/audit/__init__.py`:

```python
"""Structured audit logging (JSON Lines, stderr only)."""
```

`src/mcp_gateway/audit/logger.py`:

```python
"""Audit logger.

stdout は MCP プロトコル通信に使うため絶対に汚染しない。
監査ログは stderr に JSON Lines で書き出す。
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any


class AuditLogger:
    def log(self, *, ev: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ev": ev,
        }
        record.update(fields)
        sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestAuditLogger -v
uv run ruff check src/mcp_gateway/audit/
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/audit/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add structured audit logger (JSON Lines, stderr)"
git push -u origin feature/phase2-task7_audit_logger
gh pr create --draft --base feature/phase2_mcp_gateway_authz__base \
  --title "feat(mcp_gateway): audit logger" \
  --body "JSON Lines on stderr; stdout never polluted."
```

---

### Phase 2 完了アクション

- [ ] 全 Task の Draft PR を順次マージし、`feature/phase2_mcp_gateway_authz__base` を整える
- [ ] `master` をターゲットとした Draft PR を作成

```bash
git checkout feature/phase2_mcp_gateway_authz__base
git pull
gh pr create --draft --base master \
  --title "feat(mcp_gateway): Phase 2 - authorization core" \
  --body "Phase 2 deliverables: api-key auth, header parsing, session registry, policy engine, output filters, tool registry, audit logger."
```

---

## Phase 3: Integration (統合層)

**Phase Base:** `feature/phase3_mcp_gateway_integration__base` (← Phase 2 が `master` にマージされた後、`master` から派生)

上流 stdio クライアント・ツールプロキシ・ハンドシェイク・SSE/HTTP サーバ・エントリポイント・受け入れ基準を満たす E2E テストを実装する。

---

### Task 3.1: 上流 MCP クライアント (`upstream/context_store_client.py`)

**派生元:** `feature/phase3_mcp_gateway_integration__base` (Base派生 / 単体完結)

**Branch:** `feature/phase3-task1_upstream_client`

**Files:**
- Create: `src/mcp_gateway/upstream/__init__.py`
- Create: `src/mcp_gateway/upstream/context_store_client.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestUpstreamClient` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout master
git pull origin master
git checkout -b feature/phase3_mcp_gateway_integration__base
git push -u origin feature/phase3_mcp_gateway_integration__base
git checkout -b feature/phase3-task1_upstream_client
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestUpstreamClient:
    def test_build_env_passthrough_allowlist_only(self, monkeypatch):
        from mcp_gateway.upstream.context_store_client import build_upstream_env

        monkeypatch.setenv("OPENAI_API_KEY", "sk-allowed")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
        monkeypatch.setenv("CONTEXT_STORE_DB_PATH", "/tmp/x")  # noqa: S108

        env = build_upstream_env(
            passthrough=["OPENAI_API_KEY", "CONTEXT_STORE_DB_PATH"],
            base_env={
                "OPENAI_API_KEY": "sk-allowed",
                "AWS_SECRET_ACCESS_KEY": "should-not-leak",
                "CONTEXT_STORE_DB_PATH": "/tmp/x",  # noqa: S108
                "PATH": "/usr/bin",
            },
        )
        assert env.get("OPENAI_API_KEY") == "sk-allowed"
        assert env.get("CONTEXT_STORE_DB_PATH") == "/tmp/x"  # noqa: S108
        assert "AWS_SECRET_ACCESS_KEY" not in env
        # PATH は明示的に含める(allowlist と別軸でユーティリティで継承)
        assert "PATH" in env

    @pytest.mark.asyncio
    async def test_call_tool_delegates_to_session(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.upstream.context_store_client import UpstreamClient

        fake_session = AsyncMock()
        fake_session.list_tools.return_value = type(
            "R", (), {"tools": [type("T", (), {"model_dump": lambda self: {"name": "t"}})()]}
        )()
        fake_session.call_tool.return_value = type(
            "R", (), {"content": [{"type": "text", "text": '{"a":1}'}], "isError": False}
        )()
        client = UpstreamClient.__new__(UpstreamClient)  # type: ignore[call-arg]
        client._session = fake_session  # type: ignore[attr-defined]
        client._tools_cache = None  # type: ignore[attr-defined]

        tools = await client.list_tools()
        assert tools == [{"name": "t"}]

        payload = await client.call_tool("t", {"q": 1})
        assert payload == {"a": 1}
        fake_session.call_tool.assert_awaited_once_with("t", {"q": 1})
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestUpstreamClient -v
```

- [ ] **Step 4: `upstream/__init__.py` と `upstream/context_store_client.py` を実装**

`src/mcp_gateway/upstream/__init__.py`:

```python
"""Upstream context_store stdio MCP client."""
```

`src/mcp_gateway/upstream/context_store_client.py`:

```python
"""Stdio MCP client that owns the context_store subprocess.

We intentionally do NOT import anything from `src/context_store/`. The only
contract between the gateway and context_store is the MCP protocol over stdio.

`build_upstream_env` is a pure helper that selects which environment variables
are propagated into the subprocess (allowlist) so secrets cannot leak via
`os.environ` inheritance.
"""

from __future__ import annotations

import json
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_gateway.errors import UpstreamError

_BASE_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")


def build_upstream_env(
    *, passthrough: list[str], base_env: dict[str, str]
) -> dict[str, str]:
    """Return a fresh environ dict containing only allowlisted keys."""
    keys = set(passthrough) | set(_BASE_PASSTHROUGH)
    return {k: v for k, v in base_env.items() if k in keys}


class UpstreamClient:
    """Thin async wrapper around an mcp.ClientSession over stdio."""

    def __init__(self, command: list[str], env: dict[str, str]) -> None:
        self._command = command
        self._env = env
        self._session: ClientSession | None = None
        self._stdio_ctx: Any = None
        self._tools_cache: list[dict[str, Any]] | None = None

    async def start(self) -> None:
        params = StdioServerParameters(
            command=self._command[0], args=self._command[1:], env=self._env
        )
        self._stdio_ctx = stdio_client(params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()

    async def stop(self) -> None:
        if self._session is not None:
            await self._session.__aexit__(None, None, None)
            self._session = None
        if self._stdio_ctx is not None:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._tools_cache is not None:
            return list(self._tools_cache)
        if self._session is None:
            raise UpstreamError("upstream session not started")
        result = await self._session.list_tools()
        tools = [t.model_dump() if hasattr(t, "model_dump") else dict(t) for t in result.tools]
        self._tools_cache = tools
        return list(tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._session is None:
            raise UpstreamError("upstream session not started")
        result = await self._session.call_tool(name, arguments)
        if getattr(result, "isError", False):
            raise UpstreamError(f"upstream returned error for tool {name!r}")
        # MCP returns content list; unify to a JSON dict if the first content is JSON-text.
        content = getattr(result, "content", None) or []
        if content:
            first = content[0]
            text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"text": text}
        return {}
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestUpstreamClient -v
uv run ruff check src/mcp_gateway/upstream/
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/upstream/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add upstream stdio MCP client + env allowlist helper"
git push -u origin feature/phase3-task1_upstream_client
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "feat(mcp_gateway): upstream context_store stdio MCP client" \
  --body "Owns the subprocess; allowlists env passthrough; caches tools/list."
```

---

### Task 3.2: ツールプロキシ (`tools/proxy.py`)

**派生元:** `feature/phase3-task1_upstream_client` (**直前派生** / `UpstreamClient` を物理的に必要とする)

**Branch:** `feature/phase3-task2_tool_proxy`

**Files:**
- Create: `src/mcp_gateway/tools/proxy.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestToolProxy` クラス追加)

- [ ] **Step 1: ブランチ作成 (直前 Task の実装に依存するため、直前ブランチから派生)**

```bash
git checkout feature/phase3-task1_upstream_client
git pull origin feature/phase3-task1_upstream_client
git checkout -b feature/phase3-task2_tool_proxy
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestToolProxy:
    @pytest.mark.asyncio
    async def test_call_through_applies_filter(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.filters.structural_allowlist import StructuralAllowlistFilter
        from mcp_gateway.tools.proxy import ToolProxy

        upstream = AsyncMock()
        upstream.call_tool.return_value = {
            "results": [
                {"id": "m1", "content": "hello", "embedding": [0.1], "internal_score": 0.9}
            ],
            "total_count": 1,
        }
        filt = StructuralAllowlistFilter(
            schemas={"memory_search": {"results": ["id", "content"], "total_count": True}}
        )
        proxy = ToolProxy(upstream=upstream, filter_=filt)

        out = await proxy.call_through(
            tool_name="memory_search", arguments={"query": "hi"}
        )
        assert out["results"][0] == {"id": "m1", "content": "hello"}
        assert "embedding" not in out["results"][0]
        assert out["total_count"] == 1

    @pytest.mark.asyncio
    async def test_call_through_rejects_secret_like_arguments(self):
        from unittest.mock import AsyncMock

        from mcp_gateway.errors import PolicyError
        from mcp_gateway.filters.none_filter import NoneFilter
        from mcp_gateway.tools.proxy import ToolProxy

        proxy = ToolProxy(upstream=AsyncMock(), filter_=NoneFilter())
        with pytest.raises(PolicyError):
            await proxy.call_through(
                tool_name="t",
                arguments={"q": "use sk-1234567890abcdef as a key"},
            )
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestToolProxy -v
```

- [ ] **Step 4: `tools/proxy.py` を実装**

```python
"""ToolProxy: bridge a single tools/call to the upstream client + output filter."""

from __future__ import annotations

import re
from typing import Any, Protocol

from mcp_gateway.errors import PolicyError
from mcp_gateway.filters.protocol import OutputFilter

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bck_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class _UpstreamLike(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def _contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(p.search(value) for p in _SECRET_PATTERNS)
    if isinstance(value, dict):
        return any(_contains_secret(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_secret(v) for v in value)
    return False


class ToolProxy:
    def __init__(self, *, upstream: _UpstreamLike, filter_: OutputFilter) -> None:
        self._upstream = upstream
        self._filter = filter_

    async def call_through(
        self, *, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if _contains_secret(arguments):
            raise PolicyError("arguments contain secret-like content")
        payload = await self._upstream.call_tool(tool_name, arguments)
        return self._filter.apply(tool_name=tool_name, payload=payload)
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestToolProxy -v
uv run ruff check src/mcp_gateway/tools/proxy.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/tools/proxy.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add ToolProxy (secret sanitize + upstream + output filter)"
git push -u origin feature/phase3-task2_tool_proxy
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "feat(mcp_gateway): tool proxy (sanitize + filter)" \
  --body "Bridges tools/call to upstream after secret-like sanitize check; applies output filter."
```

---

### Task 3.3: ハンドシェイク (`auth/handshake.py`)

**派生元:** `feature/phase3_mcp_gateway_integration__base` (Base派生 / Phase 2 のコンポーネントを呼ぶだけで、Phase 3 の他 Task には依存しない)

**Branch:** `feature/phase3-task3_handshake`

**Files:**
- Create: `src/mcp_gateway/auth/handshake.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestHandshake` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase3_mcp_gateway_integration__base
git pull origin feature/phase3_mcp_gateway_integration__base
git checkout -b feature/phase3-task3_handshake
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestHandshake:
    def _stack(self):
        from mcp_gateway.auth.api_key import ApiKeyAuthenticator
        from mcp_gateway.auth.handshake import HandshakeService
        from mcp_gateway.auth.session import InMemorySessionRegistry
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"rs": OutputFilterDef(type="none")},
            intents={
                "ro": IntentPolicy(
                    description="x", allowed_tools=["memory_search"], output_filter="rs"
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=["ro"])},
        )
        return HandshakeService(
            authenticator=ApiKeyAuthenticator({"agent-a": "ck_x"}),
            policy_engine=PolicyEngine(policy),
            session_registry=InMemorySessionRegistry(ttl_seconds=60, idle_timeout_seconds=30),
        )

    def test_happy_path(self):
        svc = self._stack()
        rec = svc.handshake(
            authorization_header="Bearer ck_x",
            intent_header="ro",
            requested_tools_header=None,
        )
        assert rec.agent_id == "agent-a"
        assert rec.intent == "ro"
        assert rec.caps == frozenset({"memory_search"})
        assert rec.output_filter_profile == "rs"

    def test_missing_intent_denied(self):
        from mcp_gateway.errors import PolicyError

        svc = self._stack()
        with pytest.raises(PolicyError):
            svc.handshake(
                authorization_header="Bearer ck_x",
                intent_header=None,
                requested_tools_header=None,
            )

    def test_bad_token_denied(self):
        from mcp_gateway.errors import AuthError

        svc = self._stack()
        with pytest.raises(AuthError):
            svc.handshake(
                authorization_header="Bearer wrong",
                intent_header="ro",
                requested_tools_header=None,
            )

    def test_requested_tools_intersection(self):
        svc = self._stack()
        rec = svc.handshake(
            authorization_header="Bearer ck_x",
            intent_header="ro",
            requested_tools_header="memory_search",
        )
        assert rec.caps == frozenset({"memory_search"})
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestHandshake -v
```

- [ ] **Step 4: `auth/handshake.py` を実装**

```python
"""SSE handshake: validate headers → resolve agent → evaluate grant → create session."""

from __future__ import annotations

from mcp_gateway.auth.headers import parse_bearer, parse_intent, parse_requested_tools
from mcp_gateway.auth.protocol import AgentAuthenticator
from mcp_gateway.auth.session import SessionRecord, SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError
from mcp_gateway.policy.engine import PolicyEngine


class HandshakeService:
    def __init__(
        self,
        *,
        authenticator: AgentAuthenticator,
        policy_engine: PolicyEngine,
        session_registry: SessionRegistry,
    ) -> None:
        self._auth = authenticator
        self._engine = policy_engine
        self._sessions = session_registry

    def handshake(
        self,
        *,
        authorization_header: str | None,
        intent_header: str | None,
        requested_tools_header: str | None,
    ) -> SessionRecord:
        token = parse_bearer(authorization_header)
        if token is None:
            raise AuthError("missing or malformed Authorization header")
        agent_id = self._auth.authenticate(token)

        intent = parse_intent(intent_header)
        if intent is None:
            raise PolicyError("missing X-MCP-Intent header")

        requested = parse_requested_tools(requested_tools_header)
        grant = self._engine.evaluate_grant(
            agent_id=agent_id, intent=intent, requested_tools=requested
        )
        return self._sessions.create(
            agent_id=agent_id,
            intent=grant.intent,
            caps=grant.caps,
            output_filter_profile=grant.output_filter_profile,
        )
```

- [ ] **Step 5: テスト・静的解析・コミット・Draft PR**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestHandshake -v
uv run ruff check src/mcp_gateway/auth/handshake.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/auth/handshake.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add SSE HandshakeService"
git push -u origin feature/phase3-task3_handshake
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "feat(mcp_gateway): SSE handshake service" \
  --body "Composes auth + header parse + policy grant + session create."
```

---

### Task 3.4: HTTP/SSE サーバ (`server.py`, `app.py`)

**派生元:** `feature/phase3-task3_handshake` (**直前派生** / Handshake と ToolProxy を物理的に必要とする)

**Branch:** `feature/phase3-task4_server`

> **注:** Task 3.2 (tool_proxy) が並行ブランチに存在するため、ブランチ作成後 `git merge feature/phase3-task2_tool_proxy` を実施して結合する。

**Files:**
- Create: `src/mcp_gateway/server.py`
- Create: `src/mcp_gateway/app.py`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestSseHandshakeEndpoint`, `TestMcpMessagesEndpoint` クラス追加)

- [ ] **Step 1: ブランチ作成 (handshake から派生し、tool_proxy を取り込む)**

```bash
git checkout feature/phase3-task3_handshake
git pull origin feature/phase3-task3_handshake
git checkout -b feature/phase3-task4_server
git merge --no-edit feature/phase3-task2_tool_proxy
```

- [ ] **Step 2: 失敗するテストを追加**

```python
import json as _json
from typing import Any
from unittest.mock import AsyncMock


@pytest.fixture
def gateway_app(tmp_path, monkeypatch):
    """Boot the FastAPI app with a mocked upstream and a sample policy."""
    policy = tmp_path / "intents.yaml"
    policy.write_text(textwrap.dedent("""
        version: 1
        output_filters:
          rs:
            type: structural_allowlist
            schemas:
              memory_search:
                results: [id, content]
                total_count: true
        intents:
          ro:
            description: "x"
            allowed_tools: [memory_search]
            output_filter: rs
        agents:
          agent-a:
            allowed_intents: [ro]
    """).lstrip())
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
    monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_x"}')

    from mcp_gateway.app import build_app

    upstream = AsyncMock()
    upstream.list_tools.return_value = [
        {"name": "memory_search"},
        {"name": "memory_save"},
    ]
    upstream.call_tool.return_value = {
        "results": [
            {"id": "m1", "content": "hello", "embedding": [0.1], "internal_score": 0.9}
        ],
        "total_count": 1,
    }
    app = build_app(upstream_override=upstream)
    return app, upstream


@pytest.fixture
async def app_client(gateway_app):
    import httpx
    from httpx import ASGITransport

    app, _ = gateway_app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


class TestSseHandshakeEndpoint:
    @pytest.mark.asyncio
    async def test_missing_auth_returns_401(self, app_client):
        resp = await app_client.get("/sse")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_intent_returns_403(self, app_client):
        resp = await app_client.get("/sse", headers={"Authorization": "Bearer ck_x"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_handshake_emits_endpoint_event(self, app_client):
        async with app_client.stream(
            "GET",
            "/sse",
            headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": "ro"},
        ) as resp:
            assert resp.status_code == 200
            sid = None
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "session_id=" in line:
                    sid = line.split("session_id=", 1)[1].strip()
                    break
            assert sid is not None and len(sid) > 0


class TestMcpMessagesEndpoint:
    @pytest.mark.asyncio
    async def _open_session(self, app_client) -> str:
        async with app_client.stream(
            "GET",
            "/sse",
            headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": "ro"},
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "session_id=" in line:
                    return line.split("session_id=", 1)[1].strip()
        raise AssertionError("no session_id received")

    @pytest.mark.asyncio
    async def test_tools_list_filters_by_caps(self, app_client):
        sid = await self._open_session(app_client)
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        resp = await app_client.post(f"/messages?session_id={sid}", json=body)
        assert resp.status_code == 200
        envelope = resp.json()
        names = [t["name"] for t in envelope["result"]["tools"]]
        assert names == ["memory_search"]
        assert "memory_save" not in names

    @pytest.mark.asyncio
    async def test_unknown_session_id_returns_404(self, app_client):
        resp = await app_client.post(
            "/messages?session_id=nonexistent",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tools_call_filters_output(self, app_client):
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "hi"}},
            },
        )
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "embedding" not in result["results"][0]
        assert "internal_score" not in result["results"][0]
        assert result["results"][0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_tools_call_unauthorized_tool_denied(self, app_client):
        sid = await self._open_session(app_client)
        resp = await app_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "memory_save", "arguments": {}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "error" in body
        assert "not found" in body["error"]["message"].lower()
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -k "Sse or Mcp" -v
```

- [ ] **Step 4: `server.py` を実装**

```python
"""MCP SSE transport handlers.

Two endpoints make up the transport:
- GET /sse                   → SSE stream; the first event ("endpoint") publishes the session_id
- POST /messages?session_id  → JSON-RPC envelope (tools/list, tools/call) — responds inline (200)
                                with the JSON-RPC result. Real MCP clients also receive the result
                                via the SSE channel; for unit tests we keep both paths consistent.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError, SessionError, UpstreamError
from mcp_gateway.filters.factory import build_filter
from mcp_gateway.policy.models import GatewayPolicy
from mcp_gateway.tools.proxy import ToolProxy
from mcp_gateway.tools.registry import ToolRegistry


def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
) -> APIRouter:
    router = APIRouter()

    @router.get("/sse")
    async def sse(request: Request) -> Any:
        try:
            record = handshake.handshake(
                authorization_header=request.headers.get("authorization"),
                intent_header=request.headers.get("x-mcp-intent"),
                requested_tools_header=request.headers.get("x-mcp-requested-tools"),
            )
        except AuthError as e:
            audit.log(ev="handshake", decision="deny", reason="auth_failed", detail=str(e))
            raise HTTPException(status_code=401, detail="auth_failed") from e
        except PolicyError as e:
            audit.log(ev="handshake", decision="deny", reason="policy_violation", detail=str(e))
            raise HTTPException(status_code=403, detail="policy_violation") from e

        audit.log(
            ev="handshake",
            decision="allow",
            agent=record.agent_id,
            intent=record.intent,
            sid=record.session_id,
            caps=sorted(record.caps),
        )

        async def event_stream() -> Any:
            yield {
                "event": "endpoint",
                "data": f"/messages?session_id={record.session_id}",
            }
            try:
                while not await request.is_disconnected():
                    await asyncio.sleep(15)
                    yield {"event": "ping", "data": "keepalive"}
            finally:
                sessions.remove(record.session_id)

        return EventSourceResponse(event_stream())

    @router.post("/messages")
    async def messages(request: Request) -> Any:
        sid = request.query_params.get("session_id", "")
        try:
            record = sessions.lookup(sid)
        except SessionError as e:
            audit.log(ev="message", decision="deny", reason="session_invalid", sid=sid)
            raise HTTPException(status_code=404, detail="session_invalid") from e
        sessions.touch(sid)

        body = await request.json()
        method = body.get("method")
        rpc_id = body.get("id")

        if method == "tools/list":
            tools = tool_registry.filter_by_caps(caps=record.caps)
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}}
            )

        if method == "tools/call":
            params = body.get("params") or {}
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            if tool_name not in record.caps:
                audit.log(
                    ev="call",
                    decision="deny",
                    reason="tool_not_in_caps",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32601, "message": "tool not found"},
                    }
                )
            filt = build_filter(policy.output_filters[record.output_filter_profile])
            proxy = ToolProxy(upstream=upstream, filter_=filt)
            try:
                payload = await proxy.call_through(
                    tool_name=tool_name, arguments=arguments
                )
            except PolicyError as e:
                audit.log(
                    ev="call",
                    decision="deny",
                    reason="sanitize",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32602, "message": str(e)},
                    }
                )
            except UpstreamError:
                audit.log(
                    ev="call",
                    decision="upstream_error",
                    agent=record.agent_id,
                    sid=sid,
                    tool=tool_name,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {"code": -32000, "message": "upstream_error"},
                    }
                )
            audit.log(
                ev="call",
                decision="allow",
                agent=record.agent_id,
                sid=sid,
                tool=tool_name,
            )
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id, "result": payload}
            )

        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"unknown method {method!r}"},
            }
        )

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return router
```

- [ ] **Step 5: `app.py` を実装**

```python
"""FastAPI app factory.

`build_app` allows tests to inject a mock upstream so they don't actually spawn
the context_store subprocess.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI

from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.api_key import ApiKeyAuthenticator
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import InMemorySessionRegistry
from mcp_gateway.config import GatewaySettings
from mcp_gateway.policy.engine import PolicyEngine
from mcp_gateway.policy.loader import load_policy
from mcp_gateway.server import build_router
from mcp_gateway.tools.registry import ToolRegistry


def _decode_keys(settings: GatewaySettings) -> dict[str, str]:
    if settings.api_keys_json is None:
        return {}
    raw = settings.api_keys_json.get_secret_value()
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def build_app(*, upstream_override: Any | None = None) -> FastAPI:
    settings = GatewaySettings()  # type: ignore[call-arg]
    policy = load_policy(settings.policy_path)

    audit = AuditLogger()
    auth = ApiKeyAuthenticator(_decode_keys(settings))
    engine = PolicyEngine(policy)
    sessions = InMemorySessionRegistry(
        ttl_seconds=settings.session_ttl_seconds,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
    )
    handshake = HandshakeService(
        authenticator=auth, policy_engine=engine, session_registry=sessions
    )

    if upstream_override is not None:
        upstream = upstream_override
    else:
        from mcp_gateway.upstream.context_store_client import (
            UpstreamClient,
            build_upstream_env,
        )

        upstream = UpstreamClient(
            command=settings.upstream_command,
            env=build_upstream_env(
                passthrough=settings.upstream_env_passthrough,
                base_env=dict(os.environ),
            ),
        )

    app = FastAPI(title="ChronosGraph MCP Gateway")

    @app.on_event("startup")
    async def _on_startup() -> None:
        if upstream_override is None:
            await upstream.start()
        all_tools = (
            await upstream.list_tools()
            if hasattr(upstream, "list_tools")
            else []
        )
        registry = ToolRegistry(all_tools=all_tools)
        app.state.tool_registry = registry
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=registry,
                upstream=upstream,
                policy=policy,
                audit=audit,
            )
        )

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        if upstream_override is None and hasattr(upstream, "stop"):
            await upstream.stop()

    # Bootstrap synchronously for unit tests with mocked upstream
    if upstream_override is not None:
        # `list_tools` is async on the mock; resolve eagerly using a tiny event loop helper
        import asyncio

        all_tools = asyncio.get_event_loop().run_until_complete(upstream.list_tools())
        registry = ToolRegistry(all_tools=all_tools)
        app.state.tool_registry = registry
        app.include_router(
            build_router(
                handshake=handshake,
                sessions=sessions,
                tool_registry=registry,
                upstream=upstream,
                policy=policy,
                audit=audit,
            )
        )

    return app
```

- [ ] **Step 6: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py -k "Sse or Mcp" -v
```

- [ ] **Step 7: 静的解析・コミット・Draft PR**

```bash
uv run ruff check src/mcp_gateway/server.py src/mcp_gateway/app.py tests/unit/test_mcp_gateway.py
uv run ruff format --check src/mcp_gateway/ tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/server.py src/mcp_gateway/app.py tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add SSE handshake and JSON-RPC messages endpoints"
git push -u origin feature/phase3-task4_server
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "feat(mcp_gateway): SSE + /messages endpoints" \
  --body "GET /sse handshake (Bearer + X-MCP-Intent) and POST /messages?session_id (tools/list, tools/call) backed by HandshakeService + ToolProxy."
```

---

### Task 3.5: エントリポイント + サンプルポリシー (`__main__.py`, `policies/intents.example.yaml`)

**派生元:** `feature/phase3-task4_server` (**直前派生** / `app.py` を物理的に必要とする)

**Branch:** `feature/phase3-task5_entrypoint_and_sample`

**Files:**
- Create: `src/mcp_gateway/__main__.py`
- Create: `src/mcp_gateway/policies/intents.example.yaml`
- Modify: `tests/unit/test_mcp_gateway.py` (`TestEntrypoint` クラス追加)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase3-task4_server
git pull origin feature/phase3-task4_server
git checkout -b feature/phase3-task5_entrypoint_and_sample
```

- [ ] **Step 2: 失敗するテストを追加**

```python
class TestEntrypoint:
    def test_main_callable(self):
        # mcp_gateway.__main__.main() が import 可能で、
        # 引数 0 個で関数として呼べること(uvicorn.run はモックする)
        from unittest.mock import patch
        import mcp_gateway.__main__ as entry

        with patch("uvicorn.run") as run:
            entry.main()
        run.assert_called_once()


class TestSamplePolicy:
    def test_sample_policy_is_valid(self):
        from importlib.resources import files

        from mcp_gateway.policy.loader import load_policy

        path = files("mcp_gateway").joinpath("policies/intents.example.yaml")
        policy = load_policy(path)  # type: ignore[arg-type]
        assert policy.version == 1
        assert "read_only_recall" in policy.intents
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestEntrypoint tests/unit/test_mcp_gateway.py::TestSamplePolicy -v
```

- [ ] **Step 4: `__main__.py` を実装**

```python
"""`python -m mcp_gateway` entrypoint.

Boots uvicorn with the FastAPI app produced by `build_app`. Configuration is
sourced from MCP_GATEWAY_* environment variables — see `mcp_gateway.config`.
"""

from __future__ import annotations

import uvicorn

from mcp_gateway.app import build_app
from mcp_gateway.config import GatewaySettings


def main() -> None:
    settings = GatewaySettings()  # type: ignore[call-arg]
    app = build_app()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: `policies/intents.example.yaml` を作成**

`src/mcp_gateway/policies/intents.example.yaml`:

```yaml
version: 1

output_filters:
  recall_safe:
    type: structural_allowlist
    schemas:
      memory_search:
        results: [id, content, created_at]
        total_count: true
      memory_search_graph:
        nodes: [id, label, timestamp]
        edges: [source, target, relation]

  curator_full:
    type: none

  url_ingestion:
    type: structural_allowlist
    schemas:
      memory_save_url:
        memory_id: true
        title: true

intents:
  read_only_recall:
    description: "Search and summarize past memories. Cannot write or send out."
    allowed_tools: [memory_search, memory_search_graph, memory_stats]
    output_filter: recall_safe

  curate_memories:
    description: "Curate own working memory. Search/save/delete; no external URL."
    allowed_tools: [memory_search, memory_save, memory_delete, memory_prune]
    output_filter: curator_full

  ingest_external_url:
    description: "External URL ingestion only."
    allowed_tools: [memory_save_url]
    output_filter: url_ingestion

agents:
  summarizer-bot:
    allowed_intents: [read_only_recall]
  curator-bot:
    allowed_intents: [read_only_recall, curate_memories]
  ingestion-bot:
    allowed_intents: [ingest_external_url]
```

- [ ] **Step 6: パッケージリソースとして同梱されるよう `pyproject.toml` を確認**

`pyproject.toml` の `[tool.hatch.build.targets.wheel]` で `packages = ["src/context_store", "src/mcp_gateway"]` 指定済み。`policies/*.yaml` は `src/mcp_gateway/policies/` 配下に置かれるため、wheel に自動同梱される。`importlib.resources.files()` で読めることを Step 2 のテストで保証。

- [ ] **Step 7: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestEntrypoint tests/unit/test_mcp_gateway.py::TestSamplePolicy -v
```

- [ ] **Step 8: 静的解析・コミット・Draft PR**

```bash
uv run ruff check src/mcp_gateway/__main__.py
uv run mypy src/mcp_gateway/

git add src/mcp_gateway/__main__.py src/mcp_gateway/policies/ tests/unit/test_mcp_gateway.py
git commit -m "feat(mcp_gateway): add __main__ entrypoint and sample intents policy"
git push -u origin feature/phase3-task5_entrypoint_and_sample
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "feat(mcp_gateway): __main__ entrypoint + sample policy" \
  --body "Bootable via 'python -m mcp_gateway'; ships policies/intents.example.yaml."
```

---

### Task 3.6: 受け入れ基準テストと context_store 無変更検証

**派生元:** `feature/phase3-task5_entrypoint_and_sample` (**直前派生** / 既存の Phase 3 全実装に基づく統合テスト)

**Branch:** `feature/phase3-task6_acceptance`

**Files:**
- Modify: `tests/unit/test_mcp_gateway.py` (`TestSecretIsolation`, `TestContextStoreUntouched` クラス追加)
- Modify: なし(既存の `src/context_store/` は **無変更を検証** するためのテストのみ)

- [ ] **Step 1: ブランチ作成**

```bash
git checkout feature/phase3-task5_entrypoint_and_sample
git pull origin feature/phase3-task5_entrypoint_and_sample
git checkout -b feature/phase3-task6_acceptance
```

- [ ] **Step 2: 受け入れ基準テストを追加**

`tests/unit/test_mcp_gateway.py` の末尾に追記:

```python
class TestSecretIsolation:
    def test_upstream_env_filters_unlisted_keys(self):
        from mcp_gateway.upstream.context_store_client import build_upstream_env

        env = build_upstream_env(
            passthrough=["OPENAI_API_KEY"],
            base_env={
                "OPENAI_API_KEY": "sk-allowed",
                "AWS_SECRET_ACCESS_KEY": "should-not-leak",
                "GITHUB_TOKEN": "should-not-leak",
                "PATH": "/usr/bin",
            },
        )
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "GITHUB_TOKEN" not in env
        assert env["OPENAI_API_KEY"] == "sk-allowed"
        assert "PATH" in env

    def test_settings_repr_does_not_leak_api_keys(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text("version: 1\noutput_filters: {}\nintents: {}\nagents: {}\n")
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"a":"ck_super_secret"}')

        from mcp_gateway.config import GatewaySettings

        s = GatewaySettings()
        assert "ck_super_secret" not in repr(s)
        assert "ck_super_secret" not in str(s.model_dump())


class TestContextStoreUntouched:
    """Phase 3 acceptance: src/context_store/ must be diff-free vs master."""

    def test_no_imports_from_context_store_in_mcp_gateway(self):
        # mcp_gateway は context_store を import してはならない(構造的な無変更保証)
        import pkgutil
        from importlib import import_module

        import mcp_gateway

        bad: list[str] = []
        for mod_info in pkgutil.walk_packages(
            mcp_gateway.__path__, prefix="mcp_gateway."
        ):
            mod = import_module(mod_info.name)
            src = getattr(mod, "__file__", None)
            if src is None:
                continue
            with open(src, encoding="utf-8") as f:
                text = f.read()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if (
                    "from context_store" in stripped
                    or "import context_store" in stripped
                ):
                    bad.append(f"{mod_info.name}: {stripped}")
        assert bad == [], f"mcp_gateway imports context_store directly: {bad}"
```

- [ ] **Step 3: テストが PASS することを確認**

```bash
uv run pytest tests/unit/test_mcp_gateway.py::TestSecretIsolation tests/unit/test_mcp_gateway.py::TestContextStoreUntouched -v
```

- [ ] **Step 4: `src/context_store/` の diff が空であることを確認 (受け入れ基準 #5)**

```bash
git fetch origin master
git diff --name-only origin/master -- src/context_store/
```

期待: 出力が空(コンテキストストアに変更なし)。

- [ ] **Step 5: 受け入れ基準フル検証**

```bash
# (1) 全テストグリーン
uv run pytest tests/unit/test_mcp_gateway.py -v

# (2) ruff 警告ゼロ
uv run ruff check src/mcp_gateway/
uv run ruff format --check src/mcp_gateway/

# (3) mypy strict エラーゼロ
uv run mypy src/mcp_gateway/

# (4) 起動できることをスモーク確認 (mock upstream で Application インスタンス作成のみ検証)
uv run python -c "from unittest.mock import AsyncMock; \
  m = AsyncMock(); m.list_tools.return_value = []; \
  from mcp_gateway.app import build_app; build_app(upstream_override=m); print('ok')"
```

期待: 全項目 PASS。出力は最後の `ok`。

- [ ] **Step 6: コミット & Draft PR**

```bash
git add tests/unit/test_mcp_gateway.py
git commit -m "test(mcp_gateway): acceptance tests (secret isolation + context_store untouched)"
git push -u origin feature/phase3-task6_acceptance
gh pr create --draft --base feature/phase3_mcp_gateway_integration__base \
  --title "test(mcp_gateway): acceptance tests" \
  --body "Validates secret env isolation, secret repr masking, and zero imports from context_store."
```

---

### Phase 3 完了アクション

- [ ] 全 Task の Draft PR を順次マージし、`feature/phase3_mcp_gateway_integration__base` を整える
- [ ] `master` をターゲットとした Draft PR を作成

```bash
git checkout feature/phase3_mcp_gateway_integration__base
git pull
gh pr create --draft --base master \
  --title "feat(mcp_gateway): Phase 3 - HTTP/SSE integration" \
  --body "Phase 3 deliverables: upstream stdio client, tool proxy, handshake service, /sse + /messages endpoints, __main__ entrypoint, sample policy, acceptance tests."
```

---

## 受け入れ基準チェックリスト (設計書 §8 と対応)

- [ ] devcontainer 内で `uv run pytest tests/unit/test_mcp_gateway.py -v` が全グリーン (Phase 3 / Task 3.6 で検証)
- [ ] `uv run ruff check src/mcp_gateway/` が警告ゼロ (各 Task で検証)
- [ ] `uv run mypy src/mcp_gateway/` が strict エラーゼロ (各 Task で検証)
- [ ] `uv run python -m mcp_gateway` で起動でき、`GET /sse` (Bearer + `X-MCP-Intent`) → `POST /messages?session_id=...` (tools/list, tools/call) の主経路が通る (Phase 3 / Task 3.4 + Task 3.5)
- [ ] 既存 `src/context_store/` 配下のファイルが diff で 0 件 (Phase 3 / Task 3.6 / Step 4)
- [ ] `intents.yaml` の参照整合性違反で起動が失敗する (Phase 1 / Task 1.3 / `TestPolicyLoader`)
- [ ] 監査ログが stderr に JSON Lines で出力され、stdout は汚染されない (Phase 2 / Task 2.7 / `TestAuditLogger`)
