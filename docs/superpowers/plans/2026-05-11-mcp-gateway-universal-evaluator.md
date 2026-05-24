# MCP Gateway Universal Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChronosGraph MCP Gateway に AI エージェントの `PreToolUse` Hook 用 Universal Evaluator CLI (`evaluate` サブコマンド) を実装し、deterministic ガードレールと Anthropic Claude 4.x による意味的判定を二層構造で連結する。

**Architecture:** `__main__.py` の lazy router が `evaluate` サブコマンドを `cli.py` に振り分け、`CompositeEvaluator` が Tier 1 (既存 `PolicyEngine`) → Tier 2 (LLM + ChronosGraph 長期記憶) を直列実行する。`stdin` から JSON を読み、`stdout` にちょうど 1 行の `Decision` JSON を返し、ログは全て `stderr` に流す。

**Tech Stack:** Python 3.12 / uv / pydantic v2 / anthropic SDK (任意依存) / httpx (任意依存) / pytest / ruff (`T20` グローバル有効) / mypy strict / Devcontainer + GitHub Actions

**設計書:** `docs/superpowers/specs/2026-05-11-mcp-gateway-universal-evaluator-design.md`

**Git ワークフロー:**
- Phase Base ブランチは常に `master` から作成。命名: `feature/phaseN_<feature>__base`
- Task ブランチは原則 Phase Base から派生。直前 Task の未マージコードに依存する場合のみ直前 Task ブランチから派生 (派生元は各 Task に明記)
- 各 Task 完了時に Phase Base への Draft PR を作成、Phase 完了時に master への Draft PR を作成
- Phase Base への直接マージ・master への直接 push は行わない

**Devcontainer 強制実行:**
- 全テスト・静的解析は `.devcontainer/devcontainer.json` で構築された Devcontainer 内で実行
- ホスト側からは `code .` → "Reopen in Container" or `devcontainer up` を実施し、コンテナ内で `bash scripts/check_evaluator.sh` を叩く運用
- Phase 6 で導入する `scripts/check_evaluator.sh` は冒頭で `REMOTE_CONTAINERS` / `CODESPACES` / `DEVCONTAINER` のいずれも未設定なら `exit 1`

---

## Phase 一覧

| Phase | 目的 | Base ブランチ | Task 数 |
|-------|------|---------------|---------|
| 0 | CI/Devcontainer の設計要件適合化 | `feature/phase0_evaluator_env__base` | 2 |
| 1 | 共有データモデル / 機微情報マスキング / pyproject extras | `feature/phase1_evaluator_foundation__base` | 2 |
| 2 | chronos-dashboard セマンティック検索 API | `feature/phase2_dashboard_semantic_search__base` | 3 |
| 3 | MCP Gateway 側 LLM/Memory 部品 | `feature/phase3_gateway_memory_llm__base` | 3 |
| 4 | CompositeEvaluator (Tier 1+2 オーケストレーション) | `feature/phase4_composite_evaluator__base` | 1 |
| 5 | CLI エントリポイント / サブコマンド / subprocess E2E | `feature/phase5_evaluator_cli__base` | 3 |
| 6 | 運用統合 (Devcontainer 強制スクリプト / README) | `feature/phase6_evaluator_ops__base` | 2 |

---

## File Structure

| Phase | パス | 種別 | 責務 |
|-------|------|------|------|
| 0 | `.github/workflows/ci.yml` | 修正 | master トリガー追加・`ubuntu-slim` ランナー指定 |
| 0 | `.devcontainer/docker-compose.yml` | 修正 | `DEVCONTAINER=1` をコンテナ環境変数として設定 |
| 1 | `src/mcp_gateway/policy/models_evaluator.py` | 新規 | `ToolCallInput`, `Decision`, `MemoryItem`, masking ユーティリティ |
| 1 | `tests/unit/test_mcp_gateway_evaluator_models.py` | 新規 | models / マスキング 単体テスト |
| 1 | `pyproject.toml` | 修正 | `[project.optional-dependencies].evaluator` 追加・ruff `T20` グローバル有効化 |
| 2 | `src/context_store/retrieval/pipeline.py` | 修正 | `RetrievalPipeline.create_for_dashboard()` ファクトリ追加 (dashboard 用最小組み立て) |
| 2 | `src/context_store/dashboard/services.py` | 修正 | `DashboardService.__init__` に `retrieval_pipeline` 引数追加・`semantic_search()` メソッド追加 |
| 2 | `src/context_store/dashboard/schemas.py` | 修正 | `SemanticSearchRequest` 追加 |
| 2 | `src/context_store/dashboard/routes/memories.py` | 修正 | `POST /semantic-search` ルート追加 |
| 2 | `src/context_store/dashboard/api_server.py` | 修正 | lifespan で `RetrievalPipeline.create_for_dashboard()` を呼び `DashboardService` に注入 |
| 2 | `tests/unit/test_dashboard_semantic_search.py` | 新規 | service / route 単体テスト |
| 3 | `src/mcp_gateway/policy/memory_client.py` | 新規 | `MemoryClient` (dashboard 経由でセマンティック検索) |
| 3 | `src/mcp_gateway/policy/llm_evaluator.py` | 新規 | `_parse_decision` / `LlmEvaluator.judge` / `from_env` |
| 3 | `tests/unit/test_mcp_gateway_memory_client.py` | 新規 | httpx mock テスト |
| 3 | `tests/unit/test_mcp_gateway_llm_evaluator.py` | 新規 | プロンプト構築 / 応答パース / fallback |
| 4 | `src/mcp_gateway/policy/composite.py` | 新規 | `CompositeEvaluator` (Tier 1/2 + 構成ログ + fallback) |
| 4 | `tests/unit/test_mcp_gateway_composite.py` | 新規 | Tier 1/2 のフロー全網羅 |
| 5 | `src/mcp_gateway/cli.py` | 新規 | stderr ロガー / stdin JSON / stdout JSON / exit code |
| 5 | `src/mcp_gateway/__main__.py` | 修正 | `evaluate` サブコマンド振り分け (lazy import) |
| 5 | `tests/unit/test_mcp_gateway_cli.py` | 新規 | argv / stdin / stdout / exit code |
| 5 | `tests/integration/test_evaluator_cli_subprocess.py` | 新規 | `subprocess.run` で実プロセス E2E |
| 6 | `scripts/check_evaluator.sh` | 新規 | Devcontainer 強制チェック (ruff / mypy / pytest) |
| 6 | `README.md` | 修正 | Universal Evaluator セクション + 高リスクツール運用ノート + 環境変数表 |

---

## Phase 0: CI/Devcontainer 環境整備

**Phase Base ブランチ:** `feature/phase0_evaluator_env__base` (master から派生)

**目的:** CI が `master` へのプッシュ/PR で起動し `ubuntu-slim` ランナーで実行されるように修正し、Devcontainer 内で `DEVCONTAINER=1` が自動 export されるようにする。これらは Phase 6 で導入する `scripts/check_evaluator.sh` の前提条件。

### Task 0-1: CI ワークフローを master トリガー + ubuntu-slim に変更

**派生元:** `feature/phase0_evaluator_env__base` (独立タスク)

**ブランチ:** `feature/phase0-task1_ci_workflow`

**Files:**
- Modify: `.github/workflows/ci.yml`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase0_evaluator_env__base origin/master
git push -u origin feature/phase0_evaluator_env__base
git checkout -b feature/phase0-task1_ci_workflow
```

- [x] **Step 2: 既存 ci.yml を新仕様に書き換え**

`.github/workflows/ci.yml` の全文を以下に置き換える:

```yaml
name: CI

on:
  push:
    branches: ["master"]
  pull_request:
    branches: ["master"]

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

- [x] **Step 3: YAML をローカル parse して妥当性を確認 (Devcontainer 内)**

Run:

```bash
docker exec -it $(docker ps --filter "label=devcontainer.local_folder=$PWD" -q | head -1) \
  python -c 'import yaml,sys; yaml.safe_load(open(".github/workflows/ci.yml")); print("ok")'
```

ホストから Devcontainer を再オープン中で上記が動かない場合は VS Code "Reopen in Container" 後にコンテナ内ターミナルで:

```bash
python -c 'import yaml,sys; yaml.safe_load(open(".github/workflows/ci.yml")); print("ok")'
```

Expected: `ok`

- [x] **Step 4: コミット**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: target master only and run on ubuntu-slim"
git push -u origin feature/phase0-task1_ci_workflow
```

- [x] **Step 5: Phase Base 向け Draft PR 作成**

```bash
gh pr create --draft \
  --base feature/phase0_evaluator_env__base \
  --head feature/phase0-task1_ci_workflow \
  --title "ci: master トリガー + ubuntu-slim 化" \
  --body "$(cat <<'EOF'
## Summary
- `.github/workflows/ci.yml` の `push.branches` を `["master"]` に絞り込み、`runs-on` を `ubuntu-slim` に変更。
- Universal Evaluator 実装の前提となる CI 整備 (Phase 0 / Task 0-1)。

## Test plan
- [x] Devcontainer 内で YAML を `yaml.safe_load` し parse 成功を確認
- [ ] master への次回 push で workflow がトリガーされることを Phase 0 マージ後に確認
EOF
)"
```

### Task 0-2: Devcontainer に DEVCONTAINER=1 環境変数を設定

**派生元:** `feature/phase0_evaluator_env__base` (独立タスク・CI 修正とは無関係)

**ブランチ:** `feature/phase0-task2_devcontainer_env`

**Files:**
- Modify: `.devcontainer/docker-compose.yml`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin
git checkout feature/phase0_evaluator_env__base
git pull --ff-only origin feature/phase0_evaluator_env__base
git checkout -b feature/phase0-task2_devcontainer_env
```

- [x] **Step 2: docker-compose.yml を編集して `DEVCONTAINER=1` をコンテナ環境変数に設定する**

`.devcontainer/docker-compose.yml` の `app.environment` に以下を追加:

```yaml
environment:
  - UV_PROJECT_ENVIRONMENT=/home/vscode/.venv
  - DEVCONTAINER=1
```

- [x] **Step 3: Devcontainer 内で環境変数が設定されることを確認**

Run (Devcontainer 内):

```bash
echo "DEVCONTAINER=${DEVCONTAINER}"
```

Expected: `DEVCONTAINER=1`

- [x] **Step 4: 非対話 bash でも DEVCONTAINER=1 が引き継がれることを確認**

Run (Devcontainer 内):

```bash
bash -c 'echo DEVCONTAINER=$DEVCONTAINER'
```

Expected: `DEVCONTAINER=1`

- [x] **Step 5: docker compose 設定を検証**

Run (Devcontainer 内):

```bash
docker compose -f .devcontainer/docker-compose.yml config >/dev/null
```

Expected: exit code 0。

- [x] **Step 6: コミット**

```bash
git add .devcontainer/docker-compose.yml
git commit -m "chore(devcontainer): set DEVCONTAINER environment variable"
git push -u origin feature/phase0-task2_devcontainer_env
```

- [x] **Step 7: Phase Base 向け Draft PR 作成**

```bash
gh pr create --draft \
  --base feature/phase0_evaluator_env__base \
  --head feature/phase0-task2_devcontainer_env \
  --title "chore(devcontainer): DEVCONTAINER=1 をコンテナ環境変数に設定" \
  --body "$(cat <<'EOF'
## Summary
- `.devcontainer/docker-compose.yml` の `app.environment` に `DEVCONTAINER=1` を追加。
- Phase 6 の `scripts/check_evaluator.sh` が Devcontainer 検知に使用する変数を、非対話シェルにも継承されるコンテナ環境変数として設定 (設計書 §6.4)。

## Test plan
- [x] `docker compose -f .devcontainer/docker-compose.yml config >/dev/null`
- [x] Devcontainer 内の非対話 bash で `$DEVCONTAINER` が `1`
EOF
)"
```

### Phase 0 完了処理

- [x] **Step 1: Phase Base への Task PR をすべてマージ (squash 推奨)**

```bash
gh pr merge --squash feature/phase0-task1_ci_workflow
gh pr merge --squash feature/phase0-task2_devcontainer_env
```

- [x] **Step 2: Phase Base を最新に同期し master 向け Draft PR を作成**

```bash
git fetch origin
git checkout feature/phase0_evaluator_env__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase0_evaluator_env__base \
  --title "Phase 0: CI/Devcontainer 環境整備 (Universal Evaluator)" \
  --body "$(cat <<'EOF'
## Summary
- CI を master トリガー + ubuntu-slim 化
- Devcontainer 内で DEVCONTAINER=1 をコンテナ環境変数として設定

## Test plan
- [x] CI YAML が parse 可能
- [x] Devcontainer 内で `bash -c 'echo $DEVCONTAINER'` が `1` を返す
EOF
)"
```

---

## Phase 1: 共有データモデルとマスキングユーティリティ

**Phase Base ブランチ:** `feature/phase1_evaluator_foundation__base` (master から派生)

**目的:** Phase 2-5 全てが依存する共有データモデル (`ToolCallInput`, `Decision`, `MemoryItem`) とマスキング関数 (`_summarize_tool_input`, `_redact_tool_input_for_llm`) を 1 モジュールに集約する。`pyproject.toml` に `[project.optional-dependencies].evaluator` を追加し ruff `T20` をグローバル有効化する。

### Task 1-1: 評価器用モデル + マスキング + テスト

**派生元:** `feature/phase1_evaluator_foundation__base` (独立タスク)

**ブランチ:** `feature/phase1-task1_evaluator_models`

**Files:**
- Create: `src/mcp_gateway/policy/models_evaluator.py`
- Test: `tests/unit/test_mcp_gateway_evaluator_models.py`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase1_evaluator_foundation__base origin/master
git push -u origin feature/phase1_evaluator_foundation__base
git checkout -b feature/phase1-task1_evaluator_models
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_evaluator_models.py` を新規作成:

```python
"""Unit tests for evaluator models and redaction utilities."""

from __future__ import annotations

import pytest

from mcp_gateway.policy.models_evaluator import (
    MAX_VALUE_LENGTH,
    REDACTED_MARKER,
    Decision,
    MemoryItem,
    ToolCallInput,
    _redact_tool_input_for_llm,
    _summarize_tool_input,
)


class TestDecisionToDict:
    def test_allow_omits_optional_fields(self) -> None:
        d = Decision(decision="allow")
        assert d.to_dict() == {"decision": "allow"}

    def test_deny_serialises_reason(self) -> None:
        d = Decision(decision="deny", reason="violates rule X")
        assert d.to_dict() == {"decision": "deny", "reason": "violates rule X"}

    def test_ask_serialises_message(self) -> None:
        d = Decision(decision="ask", ask_message="confirm please")
        assert d.to_dict() == {"decision": "ask", "ask_message": "confirm please"}

    def test_ask_without_message_raises(self) -> None:
        with pytest.raises(ValueError, match="ask_message is required"):
            Decision(decision="ask")

    def test_deny_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="reason is required"):
            Decision(decision="deny")


class TestSummarizeToolInput:
    def test_redacts_sensitive_keys(self) -> None:
        out = _summarize_tool_input(
            {"password": "hunter2", "api_key": "sk-123", "command": "ls"}
        )
        assert f"password={REDACTED_MARKER}" in out
        assert f"api_key={REDACTED_MARKER}" in out
        assert "command=ls" in out

    def test_truncates_long_values(self) -> None:
        long = "a" * (MAX_VALUE_LENGTH + 50)
        out = _summarize_tool_input({"command": long})
        assert "...[truncated]" in out
        # Truncated content + marker should be shorter than original
        assert len(out) < len(long) + len("command=")

    def test_handles_int_value(self) -> None:
        out = _summarize_tool_input({"count": 42})
        assert out == "count=42"


class TestRedactToolInputForLLM:
    def test_preserves_nested_structure(self) -> None:
        out = _redact_tool_input_for_llm(
            {"opts": {"flag": True, "secret": "xxx"}, "command": "ls"}
        )
        assert out == {"opts": {"flag": True, "secret": REDACTED_MARKER}, "command": "ls"}

    def test_redacts_inside_list(self) -> None:
        out = _redact_tool_input_for_llm([{"api_key": "x"}, {"name": "ok"}])
        assert out == [{"api_key": REDACTED_MARKER}, {"name": "ok"}]

    def test_passthrough_primitives(self) -> None:
        assert _redact_tool_input_for_llm(42) == 42
        assert _redact_tool_input_for_llm(None) is None
        assert _redact_tool_input_for_llm(True) is True

    def test_truncates_long_string(self) -> None:
        long = "x" * (MAX_VALUE_LENGTH + 10)
        out = _redact_tool_input_for_llm({"v": long})
        assert isinstance(out["v"], str)
        assert "...[truncated]" in out["v"]


class TestToolCallInput:
    def test_default_context_empty(self) -> None:
        i = ToolCallInput(tool_name="bash", tool_input={"command": "ls"})
        assert i.context == {}


class TestMemoryItem:
    def test_immutable(self) -> None:
        m = MemoryItem(content="x", memory_type="semantic", importance=0.5)
        with pytest.raises(AttributeError):
            m.content = "y"  # type: ignore[misc]
```

- [x] **Step 3: テストが失敗することを確認 (Devcontainer 内)**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_evaluator_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'mcp_gateway.policy.models_evaluator'` で FAIL

- [x] **Step 4: 実装ファイルを作成**

`src/mcp_gateway/policy/models_evaluator.py`:

```python
"""Shared data models and redaction utilities for the Universal Evaluator.

This module is imported by composite.py, llm_evaluator.py, memory_client.py,
and cli.py. Importing it must not require any optional dependency (anthropic /
httpx); only stdlib + dataclasses is allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|bearer|credential)",
    re.IGNORECASE,
)
MAX_VALUE_LENGTH = 200
REDACTED_MARKER = "<REDACTED>"


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY_PATTERN.search(key))


def _truncate(value: str) -> str:
    if len(value) > MAX_VALUE_LENGTH:
        return value[:MAX_VALUE_LENGTH] + "...[truncated]"
    return value


def _summarize_tool_input(d: dict[str, Any]) -> str:
    """Build a flat key=value string for memory semantic-search queries.

    Sensitive keys (matching SENSITIVE_KEY_PATTERN) are replaced with REDACTED_MARKER.
    Each value is truncated to MAX_VALUE_LENGTH chars.
    """
    parts: list[str] = []
    for k, v in d.items():
        if _is_sensitive_key(k):
            parts.append(f"{k}={REDACTED_MARKER}")
            continue
        parts.append(f"{k}={_truncate(str(v))}")
    return " ".join(parts)


def _redact_tool_input_for_llm(obj: Any) -> Any:
    """Recursively redact sensitive keys while preserving the JSON structure."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED_MARKER if _is_sensitive_key(k) else _redact_tool_input_for_llm(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_tool_input_for_llm(v) for v in obj]
    if isinstance(obj, str):
        return _truncate(obj)
    return obj


@dataclass(frozen=True, slots=True)
class ToolCallInput:
    tool_name: str
    tool_input: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    content: str
    memory_type: str
    importance: float


@dataclass(frozen=True, slots=True)
class Decision:
    decision: Literal["allow", "deny", "ask"]
    reason: str | None = None
    ask_message: str | None = None

    def __post_init__(self) -> None:
        if self.decision == "deny" and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required and must be non-empty for decision=deny")
        if self.decision == "ask" and not (self.ask_message and self.ask_message.strip()):
            raise ValueError("ask_message is required and must be non-empty for decision=ask")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"decision": self.decision}
        if self.decision == "deny":
            out["reason"] = self.reason
        elif self.decision == "ask":
            out["ask_message"] = self.ask_message
        return out
```

- [x] **Step 5: テストが通ることを確認 (Devcontainer 内)**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_evaluator_models.py -v
```

Expected: 全テスト PASS

- [x] **Step 6: ruff / ruff format / mypy をローカル実行**

Run (Devcontainer 内):

```bash
uv run ruff check src/mcp_gateway/policy/models_evaluator.py tests/unit/test_mcp_gateway_evaluator_models.py
uv run ruff format --check src/mcp_gateway/policy/models_evaluator.py tests/unit/test_mcp_gateway_evaluator_models.py
uv run mypy src/mcp_gateway/policy/models_evaluator.py
```

Expected: いずれも exit 0

- [x] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/models_evaluator.py tests/unit/test_mcp_gateway_evaluator_models.py
git commit -m "feat(mcp_gateway): add evaluator models and redaction utilities"
git push -u origin feature/phase1-task1_evaluator_models
```

- [x] **Step 8: Phase Base 向け Draft PR 作成**

```bash
gh pr create --draft \
  --base feature/phase1_evaluator_foundation__base \
  --head feature/phase1-task1_evaluator_models \
  --title "feat(mcp_gateway): evaluator 用の共有モデルとマスキングを追加" \
  --body "$(cat <<'EOF'
## Summary
- `ToolCallInput`, `Decision`, `MemoryItem` (frozen dataclass) を追加
- 機微キーマスキングの 2 関数 (`_summarize_tool_input`, `_redact_tool_input_for_llm`) を追加
- Decision は `__post_init__` で `deny.reason` / `ask.ask_message` の非空を強制

## Test plan
- [x] `tests/unit/test_mcp_gateway_evaluator_models.py` 全通過 (Devcontainer 内)
- [x] ruff / ruff format / mypy 通過
EOF
)"
```

### Task 1-2: pyproject.toml に evaluator extras と ruff T20 を追加

**派生元:** `feature/phase1_evaluator_foundation__base` (独立タスク・Task 1-1 のコードを参照しないため)

**ブランチ:** `feature/phase1-task2_pyproject_extras`

**Files:**
- Modify: `pyproject.toml`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin
git checkout feature/phase1_evaluator_foundation__base
git pull --ff-only
git checkout -b feature/phase1-task2_pyproject_extras
```

- [x] **Step 2: `[project.optional-dependencies]` に `evaluator` を追加**

`pyproject.toml` の `embedding-litellm = [...]` の直下に挿入:

```toml
evaluator = [
    "anthropic>=0.40.0",
    "httpx>=0.27.0",
]
```

そして `all = [...]` を以下に置き換え:

```toml
all = [
    "context-store-mcp[storage-postgres,embedding-local,embedding-openai,embedding-litellm,dashboard,evaluator,dev]",
]
```

- [x] **Step 3: ruff lint 設定を更新**

`pyproject.toml` の `[tool.ruff.lint]` ブロックを以下に書き換え:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "S", "B"]
# T20 (flake8-print) をグローバルに有効化: cli/composite/llm/memory モジュールでの
# print() を ruff レベルで禁止し、stdout の純度を強制する。
extend-select = ["T20"]
```

`[tool.ruff.lint.per-file-ignores]` ブロックは `tests/**/*.py` のみ残し、`T201` を許可するエントリーを **追加しない** (設計書 §6.5)。

- [x] **Step 4: lock 更新**

Run (Devcontainer 内):

```bash
uv lock
```

Expected: `uv.lock` が更新される (新規依存追加は無いので変更が最小になる可能性)

- [x] **Step 5: ruff が T20 を認識することを確認**

`/tmp/_t20_probe.py` を作成:

```bash
echo 'print("hello")' > /tmp/_t20_probe.py
uv run ruff check --config pyproject.toml /tmp/_t20_probe.py
rm /tmp/_t20_probe.py
```

Expected: `T201 [*] \`print\` found` を含む lint エラー

- [x] **Step 6: 既存ソースが T20 違反していないことを確認**

Run:

```bash
uv run ruff check src/ tests/
```

Expected: exit 0 (もし違反があれば該当箇所を個別タスクで修正するが、設計書 §6.6 の通り既存 mcp_gateway は不変前提なので 0 想定)

- [x] **Step 7: コミット**

```bash
git add pyproject.toml uv.lock
git commit -m "build(pyproject): add evaluator extras and enable ruff T20 globally"
git push -u origin feature/phase1-task2_pyproject_extras
```

- [x] **Step 8: Phase Base 向け Draft PR 作成**

```bash
gh pr create --draft \
  --base feature/phase1_evaluator_foundation__base \
  --head feature/phase1-task2_pyproject_extras \
  --title "build(pyproject): evaluator extras + ruff T20 強制" \
  --body "$(cat <<'EOF'
## Summary
- `[project.optional-dependencies].evaluator` (anthropic + httpx) 追加
- ruff `T20` をグローバル `extend-select` で有効化し `per-file-ignores` で無効化しないことを設計書 §6.5 に従って固定

## Test plan
- [x] `ruff check` が `print()` を含む probe ファイルで T201 を検出
- [x] `ruff check src/ tests/` が exit 0
EOF
)"
```

### Phase 1 完了処理

- [x] **Step 1: Task PR を Phase Base にマージ**

```bash
gh pr merge --squash feature/phase1-task1_evaluator_models
gh pr merge --squash feature/phase1-task2_pyproject_extras
```

- [x] **Step 2: Phase Base 向け master Draft PR**

```bash
git fetch origin
git checkout feature/phase1_evaluator_foundation__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase1_evaluator_foundation__base \
  --title "Phase 1: Evaluator 共有モデルと pyproject extras" \
  --body "## Summary
- 評価器用 frozen dataclass 群
- 機微キーマスキング 2 関数
- evaluator extras + ruff T20 強制"
```

---

## Phase 2: chronos-dashboard セマンティック検索 API

**Phase Base ブランチ:** `feature/phase2_dashboard_semantic_search__base` (master から派生)

**目的:** `RetrievalPipeline` を dashboard 経由で公開する `POST /api/memories/semantic-search` を追加。`DashboardService.__init__` を破壊変更せず (`retrieval_pipeline` をデフォルト `None`) 互換性維持。dashboard は `Orchestrator` を起動しないため、**`RetrievalPipeline` は dashboard 側で単独に組み立てる** 方針 (設計書 §4.6.2 改訂版)。

> **方針変更メモ (2026-05-11):** 当初構想していた「`Orchestrator` に `retrieval_pipeline` を public property として公開し dashboard から再利用する」案 (旧 Task 2-1) は、dashboard が現状 `Orchestrator` を import しておらず new dependency を生むこと、および ingestion / lifecycle まで巻き込み dashboard 単独起動を重くすることを理由に **採用しない**。代わりに `RetrievalPipeline.create_for_dashboard()` ファクトリを新規追加し、dashboard の lifespan で直接組み立てる。これに伴い旧 Task 2-1 は削除し、Phase 2 は Task 2-1 (新: pipeline factory) → Task 2-2 → Task 2-3 の 3 タスク構成とする。

### Task 2-1: RetrievalPipeline.create_for_dashboard ファクトリ追加

**派生元:** `feature/phase2_dashboard_semantic_search__base` (独立タスク・他 Task 2-x のコードに依存しない)

**ブランチ:** `feature/phase2-task1_pipeline_factory`

**Files:**
- Modify: `src/context_store/retrieval/pipeline.py`
- Modify: `src/context_store/orchestrator.py`
- Test: `tests/unit/test_retrieval_pipeline_factory.py` (新規)

**目的:** `Orchestrator` を起動せずに dashboard 単独で `RetrievalPipeline` を組み立てる経路を確立する。`orchestrator.py:490-620` 周辺の retrieval セクション (query_analyzer / vector_search / keyword_search / graph_traversal / result_fusion / post_processor) を dashboard 用に切り出した classmethod を追加する。

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase2_dashboard_semantic_search__base origin/master
git push -u origin feature/phase2_dashboard_semantic_search__base
git checkout -b feature/phase2-task1_pipeline_factory
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_retrieval_pipeline_factory.py` を新規作成:

```python
"""Ensure RetrievalPipeline.create_for_dashboard wires the minimal stack."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_store.retrieval.pipeline import RetrievalPipeline


@pytest.mark.asyncio
async def test_create_for_dashboard_returns_pipeline_with_search() -> None:
    storage = MagicMock(name="StorageAdapter")
    graph = MagicMock(name="GraphAdapter")
    # settings はテスト用に属性を持つ MagicMock。
    # create_embedding_provider が参照する最低限の属性を揃える。
    settings = MagicMock(
        embedding_provider="openai",
        openai_api_key=MagicMock(get_secret_value=MagicMock(return_value="fake-key")),
        graph_max_logical_depth=2,
        graph_fanout_limit=10,
        graph_max_physical_hops=4,
    )
    # 実 I/O を伴う provider 生成を避けるため、関数自体はモック化を継続する
    with patch("context_store.embedding.create_embedding_provider") as mock_create:
        mock_create.return_value = MagicMock()
        pipeline = await RetrievalPipeline.create_for_dashboard(
            storage=storage, graph=graph, settings=settings
        )
    assert isinstance(pipeline, RetrievalPipeline)
    # search() を呼べる shape を持つこと (実 I/O は別テストで検証)
    assert hasattr(pipeline, "search")
```

- [x] **Step 3: テストが失敗することを確認**

```bash
uv run pytest tests/unit/test_retrieval_pipeline_factory.py -v
```

Expected: `AttributeError: type object 'RetrievalPipeline' has no attribute 'create_for_dashboard'` で FAIL

- [x] **Step 4: `create_for_dashboard` と共有ビルダーを追加し、Orchestrator をリファクタリング**

`src/context_store/retrieval/pipeline.py` に共有ビルダー `create_from_parts` と、そのラッパー `create_for_dashboard` を追加。その後、`src/context_store/orchestrator.py` の組み立てロジックをこの共有ビルダーを使うように書き換える。

```python
    @classmethod
    async def create_for_dashboard(
        cls,
        *,
        storage: "StorageAdapter",
        graph: "GraphAdapter | None",
        settings: "Settings",
    ) -> "RetrievalPipeline":
        """Build a RetrievalPipeline for the read-only dashboard."""
        from context_store.embedding import create_embedding_provider
        embedding_provider = create_embedding_provider(settings)
        return cls.create_from_parts(
            storage=storage,
            graph=graph,
            embedding_provider=embedding_provider,
            settings=settings,
        )

    @classmethod
    def create_from_parts(
        cls,
        *,
        storage: "StorageAdapter",
        graph: "GraphAdapter | None",
        embedding_provider: "EmbeddingProvider",
        settings: "Settings",
    ) -> "RetrievalPipeline":
        """Shared builder for RetrievalPipeline used by Orchestrator and Dashboard."""
        from context_store.retrieval.graph_traversal import GraphTraversal
        from context_store.retrieval.keyword_search import KeywordSearch
        from context_store.retrieval.post_processor import PostProcessor
        from context_store.retrieval.query_analyzer import QueryAnalyzer
        from context_store.retrieval.result_fusion import ResultFusion
        from context_store.retrieval.vector_search import VectorSearch

        return cls(
            query_analyzer=QueryAnalyzer(),
            vector_search=VectorSearch(
                embedding_provider=embedding_provider,
                storage_adapter=storage,
            ),
            keyword_search=KeywordSearch(storage_adapter=storage),
            # graph=None の場合、GraphTraversal は内部でガードされ空の結果を返す
            graph_traversal=GraphTraversal(
                graph_adapter=graph,
                default_depth=settings.graph_max_logical_depth,
                fanout_limit=settings.graph_fanout_limit,
                max_physical_hops=settings.graph_max_physical_hops,
            ),
            result_fusion=ResultFusion(),
            post_processor=PostProcessor(storage_adapter=storage),
            storage_adapter=storage,
        )
```

`src/context_store/orchestrator.py`:
`retrieval_pipeline = RetrievalPipeline(...)` の直接構築箇所を `RetrievalPipeline.create_from_parts(...)` 呼び出しに置き換え。


- [x] **Step 5: テスト通過確認**

```bash
uv run pytest tests/unit/test_retrieval_pipeline_factory.py -v
```

Expected: PASS

- [x] **Step 6: 既存テストへの回帰確認**

```bash
uv run pytest tests/unit/test_orchestrator.py tests/unit -k "retrieval or pipeline" -v
```

Expected: 既存テストが全て PASS (新規 classmethod 追加のみで既存挙動に変更なし)

- [x] **Step 7: ruff / mypy**

```bash
uv run ruff check src/context_store/retrieval/pipeline.py src/context_store/orchestrator.py tests/unit/test_retrieval_pipeline_factory.py
uv run mypy src/context_store/retrieval/pipeline.py src/context_store/orchestrator.py
```

Expected: exit 0

- [x] **Step 8: コミット**

```bash
git add src/context_store/retrieval/pipeline.py src/context_store/orchestrator.py tests/unit/test_retrieval_pipeline_factory.py
git commit -m "feat(retrieval): add RetrievalPipeline.create_for_dashboard factory and refactor orchestrator"
git push -u origin feature/phase2-task1_pipeline_factory
```

- [x] **Step 9: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase2_dashboard_semantic_search__base \
  --head feature/phase2-task1_pipeline_factory \
  --title "feat(retrieval): RetrievalPipeline.create_for_dashboard ファクトリ追加" \
  --body "dashboard が Orchestrator を起動せずに RetrievalPipeline を構築できる経路を追加 (設計書 §4.6.2 改訂版)。"
```

### Task 2-2: DashboardService.semantic_search() + SemanticSearchRequest schema

**派生元:** `feature/phase2_dashboard_semantic_search__base` (独立タスク・Task 2-1 のコードを直接呼ばないため独立可能)

**ブランチ:** `feature/phase2-task2_dashboard_service`

**Files:**
- Modify: `src/context_store/dashboard/services.py`
- Modify: `src/context_store/dashboard/schemas.py`
- Test: `tests/unit/test_dashboard_semantic_search.py` (新規)

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin
git checkout feature/phase2_dashboard_semantic_search__base
git pull --ff-only
git checkout -b feature/phase2-task2_dashboard_service
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_dashboard_semantic_search.py`:

```python
"""Tests for DashboardService.semantic_search and SemanticSearchRequest schema."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_store.dashboard.schemas import SemanticSearchRequest
from context_store.dashboard.services import DashboardService


@pytest.mark.asyncio
async def test_semantic_search_delegates_to_retrieval_pipeline() -> None:
    fake_memory = SimpleNamespace(
        id="m-1",
        content="hello",
        memory_type="semantic",
        importance_score=0.8,
        project="demo",
        access_count=3,
        created_at=datetime(2026, 5, 11),
    )
    response = SimpleNamespace(memories=[fake_memory])
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=response)

    service = DashboardService(
        storage=MagicMock(),
        graph=None,
        retrieval_pipeline=pipeline,
    )

    out = await service.semantic_search(query="tool:bash command=ls", project="demo", top_k=5)

    pipeline.search.assert_awaited_once_with(query="tool:bash command=ls", project="demo", top_k=5)
    assert out == [fake_memory]


@pytest.mark.asyncio
async def test_semantic_search_raises_when_pipeline_not_configured() -> None:
    service = DashboardService(storage=MagicMock(), graph=None)
    with pytest.raises(RuntimeError, match="retrieval_pipeline"):
        await service.semantic_search(query="anything")


def test_semantic_search_request_defaults() -> None:
    req = SemanticSearchRequest(query="x")
    assert req.project is None
    assert req.top_k == 5


def test_semantic_search_request_top_k_validation() -> None:
    with pytest.raises(ValueError):
        SemanticSearchRequest(query="x", top_k=0)
```

- [x] **Step 3: テストが失敗することを確認**

Run:

```bash
uv run pytest tests/unit/test_dashboard_semantic_search.py -v
```

Expected: `ImportError: cannot import name 'SemanticSearchRequest'` 等で FAIL

- [x] **Step 4: schemas.py に SemanticSearchRequest を追加**

`src/context_store/dashboard/schemas.py` の末尾に追記:

```python
from pydantic import Field


class SemanticSearchRequest(DashboardBaseModel):
    query: str = Field(..., min_length=1)
    project: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
```

`from pydantic import BaseModel, ConfigDict` の行を `from pydantic import BaseModel, ConfigDict, Field` に変更すれば末尾の import 行は不要。

- [x] **Step 5: services.py を修正**

`src/context_store/dashboard/services.py` の `DashboardService.__init__` を以下に置き換え:

```python
    def __init__(
        self,
        storage: StorageAdapter,
        graph: GraphAdapter | None,
        retrieval_pipeline: "RetrievalPipeline | None" = None,
    ) -> None:
        self._storage = storage
        self._graph = graph
        self._retrieval = retrieval_pipeline
```

末尾に `semantic_search` メソッドを追加:

```python
    async def semantic_search(
        self,
        query: str,
        project: str | None = None,
        top_k: int = 5,
    ) -> list[Memory]:
        """Vector similarity semantic search.

        Raises RuntimeError when the retrieval pipeline was not injected into the
        dashboard (e.g. older startup configuration). The route layer should map
        this to HTTP 503.
        """
        if self._retrieval is None:
            raise RuntimeError("retrieval_pipeline not configured for this dashboard")
        resp = await self._retrieval.search(query=query, project=project, top_k=top_k)
        return list(resp.memories)
```

ファイル先頭の import に以下を追加 (TYPE_CHECKING 経由で循環参照を避ける):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_store.retrieval.pipeline import RetrievalPipeline
```

- [x] **Step 6: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_dashboard_semantic_search.py -v
```

Expected: 4 テスト PASS

- [x] **Step 7: 既存 dashboard テストへの回帰確認**

Run:

```bash
uv run pytest tests/unit/test_dashboard_service.py tests/unit/test_api_server.py -v
```

Expected: 既存テスト PASS (DashboardService への新規 keyword 引数はデフォルト `None` のため互換性維持)

- [x] **Step 8: ruff / mypy**

Run:

```bash
uv run ruff check src/context_store/dashboard/services.py src/context_store/dashboard/schemas.py tests/unit/test_dashboard_semantic_search.py
uv run mypy src/context_store/dashboard/services.py src/context_store/dashboard/schemas.py
```

Expected: exit 0

- [x] **Step 9: コミット**

```bash
git add src/context_store/dashboard/services.py src/context_store/dashboard/schemas.py tests/unit/test_dashboard_semantic_search.py
git commit -m "feat(dashboard): add DashboardService.semantic_search and SemanticSearchRequest"
git push -u origin feature/phase2-task2_dashboard_service
```

- [x] **Step 10: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase2_dashboard_semantic_search__base \
  --head feature/phase2-task2_dashboard_service \
  --title "feat(dashboard): semantic_search サービスメソッドと schema" \
  --body "DashboardService に retrieval_pipeline 注入経路と semantic_search() を追加。既存 __init__ シグネチャはデフォルト None で互換維持 (設計書 §4.6.1)。"
```

### Task 2-3: /memories/semantic-search ルート + api_server で retrieval_pipeline 注入

**派生元:** `feature/phase2-task2_dashboard_service` + `feature/phase2-task1_pipeline_factory` (Task 2-2 の `DashboardService.semantic_search` と Task 2-1 の `RetrievalPipeline.create_for_dashboard` を両方必要とする)

**ブランチ:** `feature/phase2-task3_memories_route`

**Files:**
- Modify: `src/context_store/dashboard/routes/memories.py`
- Modify: `src/context_store/dashboard/api_server.py`
- Test: `tests/unit/test_dashboard_semantic_search.py` (Task 2-2 で作成・拡張)

- [x] **Step 1: ブランチ作成 (Task 2-1 と 2-2 を統合)**

```bash
git fetch origin
git checkout feature/phase2-task2_dashboard_service
git pull --ff-only
git checkout -b feature/phase2-task3_memories_route
git merge origin/feature/phase2-task1_pipeline_factory
```

- [x] **Step 2: route の失敗テストを追加**

`tests/unit/test_dashboard_semantic_search.py` の末尾に追記:

```python
import pytest
from fastapi.testclient import TestClient

from context_store.dashboard.api_server import create_app


@pytest.fixture
def app_with_pipeline():
    fake_memory = SimpleNamespace(
        id="m-1",
        content="hello",
        memory_type="semantic",
        importance_score=0.8,
        project="demo",
        access_count=3,
        created_at=datetime(2026, 5, 11),
    )
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=SimpleNamespace(memories=[fake_memory]))

    service = DashboardService(storage=MagicMock(), graph=None, retrieval_pipeline=pipeline)
    app = create_app(service_override=service)
    return app, pipeline


def test_semantic_search_endpoint_returns_memories(app_with_pipeline) -> None:
    app, pipeline = app_with_pipeline
    with TestClient(app) as client:
        r = client.post(
            "/api/memories/semantic-search",
            json={"query": "tool:bash command=ls", "project": "demo", "top_k": 3},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["content"] == "hello"
    pipeline.search.assert_awaited_once()


def test_semantic_search_endpoint_returns_503_when_pipeline_missing() -> None:
    service = DashboardService(storage=MagicMock(), graph=None)
    app = create_app(service_override=service)
    with TestClient(app) as client:
        r = client.post("/api/memories/semantic-search", json={"query": "x"})
    assert r.status_code == 503
```

- [x] **Step 3: テストが失敗することを確認**

Run:

```bash
uv run pytest tests/unit/test_dashboard_semantic_search.py::test_semantic_search_endpoint_returns_memories -v
```

Expected: `404 Not Found` で FAIL (ルート未登録)

- [x] **Step 4: routes/memories.py にエンドポイントを追加**

`src/context_store/dashboard/routes/memories.py` の末尾に追加:

```python
from context_store.dashboard.schemas import SemanticSearchRequest


@router.post("/semantic-search", response_model=list[MemoryResponse])
async def semantic_search_memories(
    req: SemanticSearchRequest, request: Request
) -> list[MemoryResponse]:
    """Vector similarity semantic search over memories.

    Delegates to DashboardService.semantic_search() → RetrievalPipeline.search().
    Returns 503 if the dashboard was started without a retrieval pipeline.
    """
    from context_store.dashboard.services import DashboardService

    service: DashboardService = request.app.state.service
    try:
        memories = await service.semantic_search(
            query=req.query, project=req.project, top_k=req.top_k
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return [
        MemoryResponse(
            id=str(m.id),
            content=m.content,
            memory_type=m.memory_type,
            importance=m.importance_score,
            project=m.project,
            access_count=m.access_count,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in memories
    ]
```

- [x] **Step 5: api_server.py の lifespan で RetrievalPipeline.create_for_dashboard を呼び出し注入**

`src/context_store/dashboard/api_server.py:50` 周辺の `app.state.service = DashboardService(storage=storage, graph=graph)` を以下に置き換え:

```python
        # NOTE: dashboard は read-only adapter のみを使うため、Orchestrator は通常
        # 起動しない。retrieval_pipeline は別途 lazy 構築する。
        retrieval_pipeline = None
        try:
            from context_store.retrieval.pipeline import RetrievalPipeline

            retrieval_pipeline = await RetrievalPipeline.create_for_dashboard(
                storage=storage,
                graph=graph,
                settings=settings,
            )
        except Exception as exc:
            logger.warning(
                "RetrievalPipeline could not be initialized for dashboard "
                "(semantic-search endpoint will return 503): %s",
                exc,
                exc_info=True,
            )

        app.state.service = DashboardService(
            storage=storage,
            graph=graph,
            retrieval_pipeline=retrieval_pipeline,
        )
```

> **NOTE:** `RetrievalPipeline.create_for_dashboard` は Task 2-1 で追加したメソッドを利用する。初期化に失敗した場合は `retrieval_pipeline=None` で dashboard を起動し、エンドポイントから 503 を返すようにする。

- [x] **Step 6: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_dashboard_semantic_search.py -v
```

Expected: 全テスト PASS

- [x] **Step 7: 既存 dashboard ルートテストの回帰確認**

Run:

```bash
uv run pytest tests/unit/test_api_server.py tests/unit/test_dashboard_service.py tests/unit/test_api_logs.py -v
```

Expected: 全 PASS

- [x] **Step 8: ruff / mypy**

Run:

```bash
uv run ruff check src/context_store/dashboard/routes/memories.py src/context_store/dashboard/api_server.py
uv run mypy src/context_store/dashboard/
```

Expected: exit 0

- [x] **Step 9: コミット**

```bash
git add src/context_store/dashboard/routes/memories.py src/context_store/dashboard/api_server.py tests/unit/test_dashboard_semantic_search.py
git commit -m "feat(dashboard): add POST /api/memories/semantic-search endpoint"
git push -u origin feature/phase2-task3_memories_route
```

- [x] **Step 10: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase2_dashboard_semantic_search__base \
  --head feature/phase2-task3_memories_route \
  --title "feat(dashboard): POST /api/memories/semantic-search 追加" \
  --body "RetrievalPipeline を経由したベクトル類似度検索を HTTP で公開。pipeline 未構成時は 503 (設計書 §4.6.3)。"
```

### Phase 2 完了処理

- [x] **Step 1: Task PR を順序通りに Phase Base へマージ**

```bash
gh pr merge --squash feature/phase2-task1_pipeline_factory
gh pr merge --squash feature/phase2-task2_dashboard_service
gh pr merge --squash feature/phase2-task3_memories_route
```

- [x] **Step 2: master 向け Phase Draft PR**

```bash
git fetch origin
git checkout feature/phase2_dashboard_semantic_search__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase2_dashboard_semantic_search__base \
  --title "Phase 2: Dashboard セマンティック検索 API" \
  --body "## Summary
- RetrievalPipeline.create_for_dashboard() ファクトリ追加
- DashboardService.semantic_search() + SemanticSearchRequest schema
- POST /api/memories/semantic-search エンドポイント"
```

---

## Phase 3: MCP Gateway 側 LLM / Memory 部品

**Phase Base ブランチ:** `feature/phase3_gateway_memory_llm__base` (master から派生)

**前提:** Phase 1 (models_evaluator.py) と Phase 2 (`/api/memories/semantic-search`) が master にマージ済み。

### Task 3-1: MemoryClient 実装 + httpx mock テスト

**派生元:** `feature/phase3_gateway_memory_llm__base` (独立タスク)

**ブランチ:** `feature/phase3-task1_memory_client`

**Files:**
- Create: `src/mcp_gateway/policy/memory_client.py`
- Test: `tests/unit/test_mcp_gateway_memory_client.py`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase3_gateway_memory_llm__base origin/master
git push -u origin feature/phase3_gateway_memory_llm__base
git checkout -b feature/phase3-task1_memory_client
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_memory_client.py`:

```python
"""Tests for MemoryClient (HTTP client over chronos-dashboard)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from mcp_gateway.policy.memory_client import (
    MemoryClient,
    MemoryFetchError,
)
from mcp_gateway.policy.models_evaluator import MemoryItem


@pytest.mark.asyncio
async def test_retrieve_returns_memory_items() -> None:
    client = MemoryClient(dashboard_url="http://dashboard.local:9000", top_k=3)
    payload = [
        {"id": "1", "content": "x", "memoryType": "semantic", "importance": 0.7,
         "project": "demo", "accessCount": 2, "createdAt": None}
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        # Verify the POST body (httpx sends JSON in body, not URL params)
        assert request.method == "POST"
        assert request.url.path == "/api/memories/semantic-search"
        body = json.loads(request.content)
        assert body == {"query": "tool:bash command=ls", "project": "demo", "top_k": 3}
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    with patch.object(MemoryClient, "_build_transport", return_value=transport):
        out = await client.retrieve(query="tool:bash command=ls", project="demo")

    assert out == [MemoryItem(content="x", memory_type="semantic", importance=0.7)]


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_http_error() -> None:
    client = MemoryClient(dashboard_url="http://dashboard.local:9000")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="pipeline missing")

    transport = httpx.MockTransport(handler)
    with patch.object(MemoryClient, "_build_transport", return_value=transport):
        with pytest.raises(MemoryFetchError):
            await client.retrieve(query="x")


@pytest.mark.asyncio
async def test_retrieve_raises_memory_fetch_error_on_timeout() -> None:
    client = MemoryClient(dashboard_url="http://dashboard.local:9000", timeout_seconds=0.001)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    transport = httpx.MockTransport(handler)
    with patch.object(MemoryClient, "_build_transport", return_value=transport):
        with pytest.raises(MemoryFetchError):
            await client.retrieve(query="x")


def test_from_env_returns_none_when_url_missing(monkeypatch) -> None:
    monkeypatch.delenv("CHRONOS_DASHBOARD_URL", raising=False)
    assert MemoryClient.from_env() is None


def test_from_env_picks_up_url_and_api_key(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOS_DASHBOARD_URL", "http://x:9000")
    monkeypatch.setenv("CHRONOS_DASHBOARD_API_KEY", "abc")
    c = MemoryClient.from_env()
    assert c is not None
    assert c.dashboard_url == "http://x:9000"
    assert c._api_key == "abc"
```

- [x] **Step 3: テストが失敗することを確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_memory_client.py -v
```

Expected: `ModuleNotFoundError` で FAIL

- [x] **Step 4: 実装ファイル作成**

`src/mcp_gateway/policy/memory_client.py`:

```python
"""HTTP client that fetches semantically related memories from chronos-dashboard."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from mcp_gateway.policy.models_evaluator import MemoryItem

logger = logging.getLogger("chronos_evaluator.memory")


class MemoryFetchError(Exception):
    """Raised when the dashboard semantic-search request fails or times out."""


@dataclass
class MemoryClient:
    dashboard_url: str
    timeout_seconds: float = 3.0
    top_k: int = 5
    # repr=False: APIキーが __repr__ / assertion diff / 例外トレースに平文で漏れないようにする
    _api_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "MemoryClient | None":
        url = os.getenv("CHRONOS_DASHBOARD_URL")
        if not url:
            return None
        return cls(
            dashboard_url=url.rstrip("/"),
            timeout_seconds=float(os.getenv("CHRONOS_DASHBOARD_TIMEOUT_SECONDS", "3.0")),
            top_k=int(os.getenv("CHRONOS_DASHBOARD_TOP_K", "5")),
            _api_key=os.getenv("CHRONOS_DASHBOARD_API_KEY"),
        )

    def _build_transport(self) -> "Any":  # overridden in tests
        return None

    async def retrieve(self, query: str, project: str | None = None) -> list[MemoryItem]:
        # Lazy import: httpx is an optional dependency.
        import httpx

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        transport = self._build_transport()
        client_kwargs: dict[str, Any] = {"timeout": httpx.Timeout(self.timeout_seconds)}
        if transport is not None:
            client_kwargs["transport"] = transport

        try:
            async with httpx.AsyncClient(**client_kwargs) as http:
                resp = await http.post(
                    f"{self.dashboard_url}/api/memories/semantic-search",
                    json={"query": query, "project": project, "top_k": self.top_k},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise MemoryFetchError(f"dashboard request failed: {exc}") from exc

        if resp.status_code != 200:
            raise MemoryFetchError(
                f"dashboard returned {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise MemoryFetchError(f"invalid JSON from dashboard: {exc}") from exc

        if not isinstance(data, list):
            raise MemoryFetchError(f"expected list, got {type(data).__name__}")

        out: list[MemoryItem] = []
        for item in data:
            try:
                out.append(
                    MemoryItem(
                        content=str(item["content"]),
                        memory_type=str(item.get("memoryType") or item.get("memory_type") or ""),
                        importance=float(item.get("importance") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("skipping malformed memory item: %s", exc)
        return out
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_memory_client.py -v
```

Expected: 全 PASS

- [x] **Step 6: ruff / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/policy/memory_client.py tests/unit/test_mcp_gateway_memory_client.py
uv run ruff format --check src/mcp_gateway/policy/memory_client.py tests/unit/test_mcp_gateway_memory_client.py
uv run mypy src/mcp_gateway/policy/memory_client.py
```

Expected: exit 0

- [x] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/memory_client.py tests/unit/test_mcp_gateway_memory_client.py
git commit -m "feat(mcp_gateway): add MemoryClient for chronos-dashboard semantic search"
git push -u origin feature/phase3-task1_memory_client
```

- [x] **Step 8: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase3_gateway_memory_llm__base \
  --head feature/phase3-task1_memory_client \
  --title "feat(mcp_gateway): MemoryClient (dashboard HTTP)" \
  --body "Lazy import httpx で chronos-dashboard の /api/memories/semantic-search を叩く軽量クライアント。失敗時は MemoryFetchError (設計書 §4.5)。"
```

### Task 3-2: LLM 応答パーサ (`_parse_decision`)

**派生元:** `feature/phase3_gateway_memory_llm__base` (独立タスク・純粋関数で他の Task に依存しない)

**ブランチ:** `feature/phase3-task2_llm_parse_decision`

**Files:**
- Create: `src/mcp_gateway/policy/llm_evaluator.py` (まずは `_parse_decision` のみ + 例外クラス)
- Test: `tests/unit/test_mcp_gateway_llm_evaluator.py`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin
git checkout feature/phase3_gateway_memory_llm__base
git pull --ff-only
git checkout -b feature/phase3-task2_llm_parse_decision
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_llm_evaluator.py`:

```python
"""Tests for LLM response parser (_parse_decision)."""

from __future__ import annotations

import pytest

from mcp_gateway.policy.llm_evaluator import (
    ResponseParseError,
    _parse_decision,
)
from mcp_gateway.policy.models_evaluator import Decision


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"decision":"allow"}', Decision(decision="allow")),
        ('  {"decision": "allow"}  ', Decision(decision="allow")),
    ],
)
def test_parse_allow(text: str, expected: Decision) -> None:
    assert _parse_decision(text) == expected


def test_parse_deny_with_reason() -> None:
    out = _parse_decision('{"decision":"deny","reason":"forbidden command"}')
    assert out == Decision(decision="deny", reason="forbidden command")


def test_parse_ask_with_message() -> None:
    out = _parse_decision('{"decision":"ask","ask_message":"please confirm"}')
    assert out == Decision(decision="ask", ask_message="please confirm")


def test_parse_truncates_long_reason() -> None:
    long = "x" * 500
    out = _parse_decision(f'{{"decision":"deny","reason":"{long}"}}')
    assert out.reason is not None
    assert len(out.reason) <= 200


def test_parse_truncates_long_ask_message() -> None:
    long = "x" * 500
    out = _parse_decision(f'{{"decision":"ask","ask_message":"{long}"}}')
    assert out.ask_message is not None
    assert len(out.ask_message) <= 300


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"decision":"maybe"}',
        '{"decision":"deny"}',  # missing reason
        '{"decision":"deny","reason":"   "}',  # whitespace only
        '{"decision":"ask"}',  # missing ask_message
    ],
)
def test_parse_rejects_invalid(text: str) -> None:
    with pytest.raises(ResponseParseError):
        _parse_decision(text)
```

- [x] **Step 3: テストが失敗することを確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_llm_evaluator.py -v
```

Expected: `ModuleNotFoundError` で FAIL

- [x] **Step 4: llm_evaluator.py に `_parse_decision` を実装**

`src/mcp_gateway/policy/llm_evaluator.py`:

```python
"""Anthropic-backed LLM evaluator for Tier 2 of the Universal Evaluator.

This module performs lazy import of `anthropic` inside `from_env()` / `judge()`
so that the wider evaluator runs even when anthropic is not installed.
"""

from __future__ import annotations

import json
import logging

from mcp_gateway.policy.models_evaluator import Decision

logger = logging.getLogger("chronos_evaluator.llm")


class LlmUnavailableError(Exception):
    """anthropic SDK missing or API key not configured."""


class ResponseParseError(Exception):
    """LLM response could not be parsed into a Decision."""


_REASON_MAX = 200
_ASK_MSG_MAX = 300


def _parse_decision(text: str) -> Decision:
    text = text.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ResponseParseError(f"non-JSON response: {text[:80]!r}")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResponseParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ResponseParseError(f"top-level must be object, got {type(obj).__name__}")

    decision = obj.get("decision")
    if decision == "allow":
        return Decision(decision="allow")
    if decision == "deny":
        reason = obj.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ResponseParseError("deny requires non-empty 'reason'")
        return Decision(decision="deny", reason=reason[:_REASON_MAX])
    if decision == "ask":
        msg = obj.get("ask_message")
        if not isinstance(msg, str) or not msg.strip():
            raise ResponseParseError("ask requires non-empty 'ask_message'")
        return Decision(decision="ask", ask_message=msg[:_ASK_MSG_MAX])
    raise ResponseParseError(f"unknown decision: {decision!r}")
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_llm_evaluator.py -v
```

Expected: 全 PASS

- [x] **Step 6: ruff / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
uv run ruff format --check src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
uv run mypy src/mcp_gateway/policy/llm_evaluator.py
```

Expected: exit 0

- [x] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
git commit -m "feat(mcp_gateway): add LLM response parser (_parse_decision)"
git push -u origin feature/phase3-task2_llm_parse_decision
```

- [x] **Step 8: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase3_gateway_memory_llm__base \
  --head feature/phase3-task2_llm_parse_decision \
  --title "feat(mcp_gateway): LLM 応答 parse 関数" \
  --body "_parse_decision: JSON-only / decision Literal 検証 / reason・ask_message 必須性検証 (設計書 §5.5)。"
```

### Task 3-3: LlmEvaluator.judge + from_env + プロンプト構築

**派生元:** `feature/phase3-task2_llm_parse_decision` (依存タスク・Task 3-2 の `_parse_decision` / `ResponseParseError` を物理的に必要とする)

**ブランチ:** `feature/phase3-task3_llm_evaluator_judge`

**Files:**
- Modify: `src/mcp_gateway/policy/llm_evaluator.py`
- Test: `tests/unit/test_mcp_gateway_llm_evaluator.py` (Task 3-2 で作成・拡張)

- [x] **Step 1: ブランチ作成 (Task 3-2 から派生)**

```bash
git fetch origin
git checkout feature/phase3-task2_llm_parse_decision
git pull --ff-only
git checkout -b feature/phase3-task3_llm_evaluator_judge
```

- [x] **Step 2: 失敗するテストを書く (test_mcp_gateway_llm_evaluator.py に追記)**

```python
import os
from unittest.mock import MagicMock, patch

from mcp_gateway.policy.llm_evaluator import (
    LlmEvaluator,
    LlmUnavailableError,
    _build_user_prompt,
    SYSTEM_PROMPT,
)
from mcp_gateway.policy.models_evaluator import MemoryItem, ToolCallInput


def test_from_env_returns_none_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert LlmEvaluator.from_env() is None


def test_from_env_returns_none_when_anthropic_missing(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch.dict("sys.modules", {"anthropic": None}):
        # The lazy import inside from_env should ImportError → None.
        # We simulate by patching builtins.__import__ to raise ImportError for anthropic.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            assert LlmEvaluator.from_env() is None


def test_build_user_prompt_redacts_sensitive_keys() -> None:
    input_ = ToolCallInput(
        tool_name="bash",
        tool_input={"command": "echo hi", "password": "hunter2"},
        context={"cwd": "/tmp", "agent_id": "claude-code"},
    )
    rules = "- bash: no rm -rf /\n"
    memories = [MemoryItem(content="prefer dry-run", memory_type="semantic", importance=0.8)]
    out = _build_user_prompt(input_=input_, rules=rules, memories=memories, intent_name="default")
    assert "<tool_intent>" in out
    assert "<rules" in out
    assert "<memory" in out
    assert "<REDACTED>" in out
    assert "hunter2" not in out
    assert "prefer dry-run" in out


def test_build_user_prompt_handles_empty_memories() -> None:
    input_ = ToolCallInput(tool_name="bash", tool_input={"command": "ls"})
    out = _build_user_prompt(input_=input_, rules="-", memories=[], intent_name="default")
    assert "<memory" in out
    assert "</memory>" in out


@pytest.mark.asyncio
async def test_judge_returns_allow_on_valid_response(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    evaluator = LlmEvaluator(api_key="x", model="claude-haiku-4-5-20251001")
    fake_response = MagicMock()
    fake_response.content = [MagicMock(type="text", text='{"decision":"allow"}')]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_response)

    with patch.object(evaluator, "_get_client", return_value=fake_client):
        out = await evaluator.judge(
            input_=ToolCallInput(tool_name="bash", tool_input={"command": "ls"}),
            rules="-",
            memories=[],
        )
    assert out == Decision(decision="allow")


@pytest.mark.asyncio
async def test_judge_raises_on_non_text_response() -> None:
    evaluator = LlmEvaluator(api_key="x")
    fake_response = MagicMock()
    fake_response.content = []  # no text block
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_response)

    with patch.object(evaluator, "_get_client", return_value=fake_client):
        with pytest.raises(ResponseParseError):
            await evaluator.judge(
                input_=ToolCallInput(tool_name="bash", tool_input={}),
                rules="",
                memories=[],
            )


def test_system_prompt_contains_role_and_output_format() -> None:
    assert "<role>" in SYSTEM_PROMPT
    assert "<output_format>" in SYSTEM_PROMPT
    assert "allow" in SYSTEM_PROMPT and "deny" in SYSTEM_PROMPT and "ask" in SYSTEM_PROMPT
```

- [x] **Step 3: テストが失敗することを確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_llm_evaluator.py -v
```

Expected: 新規テスト群で `ImportError` or `AttributeError` により FAIL

- [x] **Step 4: llm_evaluator.py を拡張**

`src/mcp_gateway/policy/llm_evaluator.py` の末尾に追加 (`_parse_decision` の下):

```python
import asyncio
import json as _json_for_prompt
import os
from collections.abc import Sequence
from typing import Any

from mcp_gateway.policy.models_evaluator import (
    MemoryItem,
    ToolCallInput,
    _redact_tool_input_for_llm,
)


SYSTEM_PROMPT = """<role>
You are the ChronosGraph Universal Evaluator — a security-and-intent gate
that judges whether a proposed local tool call is safe and aligned with the
project's policy and the user's accumulated preferences.
</role>

<task>
Given a tool invocation (already passing deterministic guardrails), inspect:
  1. The tool intent (<tool_intent>): what the agent wants to do
  2. The project's hard rules (<rules>): immutable constraints
  3. Long-term memory (<memory>): user preferences and past decisions

Decide one of:
  - "allow": clearly safe and aligned. Proceed without bothering the user.
  - "deny":  clearly unsafe, destructive, or violates a hard rule.
  - "ask":   ambiguous, unusual, or contradicts recalled preference.
             Default to "ask" when in doubt — false-allow is the worst outcome.
</task>

<output_format>
Respond with EXACTLY one JSON object. No prose, no markdown fences, no
preamble. Schema:
  {"decision": "allow"}
  {"decision": "deny",  "reason":       "<=200 chars, why blocked>"}
  {"decision": "ask",   "ask_message":  "<=300 chars, what to confirm>"}
Any other output will be treated as a parse failure and downgraded to "ask".
</output_format>

<priorities>
1. Hard rules in <rules> are absolute. Violation -> "deny".
2. Explicit user preferences in <memory> override defaults.
3. When <memory> is empty or irrelevant, judge on tool semantics alone.
4. Never invent facts not present in the provided context.
</priorities>"""


def _build_user_prompt(
    *,
    input_: ToolCallInput,
    rules: str,
    memories: Sequence[MemoryItem],
    intent_name: str,
) -> str:
    redacted = _redact_tool_input_for_llm(input_.tool_input)
    tool_input_json = _json_for_prompt.dumps(redacted, ensure_ascii=False)
    cwd = str(input_.context.get("cwd") or "unknown")
    agent_id = str(input_.context.get("agent_id") or "unknown")

    memory_blocks = "\n".join(
        f'  <item type="{m.memory_type}" importance="{m.importance:.2f}">'
        f"\n    {m.content}\n  </item>"
        for m in memories
    )

    return f"""<tool_intent>
  <tool_name>{input_.tool_name}</tool_name>
  <tool_input>{tool_input_json}</tool_input>
  <cwd>{cwd}</cwd>
  <agent_id>{agent_id}</agent_id>
</tool_intent>

<rules source="intents.yaml" intent="{intent_name}">
{rules}
</rules>

<memory source="chronos-graph" top_k="{len(memories)}">
{memory_blocks}
</memory>

Decide now. Output JSON only."""


class LlmEvaluator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout_seconds: float = 10.0,
        thinking_budget: int = 1024,
        max_tokens: int = 1536,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._thinking_budget = thinking_budget
        self._max_tokens = max_tokens
        self._client: Any | None = None

    @classmethod
    def from_env(cls) -> "LlmEvaluator | None":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            import anthropic  # noqa: F401
        except ImportError:
            logger.warning("anthropic SDK not installed; LLM evaluator disabled")
            return None
        return cls(
            api_key=api_key,
            model=os.getenv("CHRONOS_EVALUATOR_MODEL", "claude-haiku-4-5-20251001"),
            timeout_seconds=float(os.getenv("CHRONOS_EVALUATOR_TIMEOUT_SECONDS", "10.0")),
            thinking_budget=int(os.getenv("CHRONOS_EVALUATOR_THINKING_BUDGET", "1024")),
        )

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic
            import httpx

            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=httpx.Timeout(self._timeout_seconds, connect=2.0),
            )
        return self._client

    async def judge(
        self,
        *,
        input_: ToolCallInput,
        rules: str,
        memories: Sequence[MemoryItem],
        intent_name: str = "default",
    ) -> Decision:
        user_prompt = _build_user_prompt(
            input_=input_, rules=rules, memories=memories, intent_name=intent_name
        )
        try:
            response = await asyncio.to_thread(
                self._invoke_sdk,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as exc:  # noqa: BLE001 - SDK raises a wide variety
            raise LlmUnavailableError(f"LLM call failed: {exc}") from exc

        text_blocks = [b for b in getattr(response, "content", []) if getattr(b, "type", None) == "text"]
        if not text_blocks:
            raise ResponseParseError("LLM returned no text block")
        return _parse_decision(text_blocks[0].text)

    def _invoke_sdk(self, *, system_prompt: str, user_prompt: str) -> Any:
        client = self._get_client()
        return client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
            thinking={"type": "enabled", "budget_tokens": self._thinking_budget},
        )
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_llm_evaluator.py -v
```

Expected: 全 PASS

- [x] **Step 6: ruff / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
uv run ruff format --check src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
uv run mypy src/mcp_gateway/policy/llm_evaluator.py
```

Expected: exit 0

- [x] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/llm_evaluator.py tests/unit/test_mcp_gateway_llm_evaluator.py
git commit -m "feat(mcp_gateway): add LlmEvaluator with prompt caching and adaptive thinking"
git push -u origin feature/phase3-task3_llm_evaluator_judge
```

- [x] **Step 8: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase3_gateway_memory_llm__base \
  --head feature/phase3-task3_llm_evaluator_judge \
  --title "feat(mcp_gateway): LlmEvaluator (Anthropic SDK + thinking)" \
  --body "system prompt は cache_control=ephemeral、adaptive thinking 有効、ImportError/欠落キーで from_env→None (設計書 §3, §4.4)。"
```

### Phase 3 完了処理

- [ ] **Step 1: Task PR を Phase Base にマージ**

```bash
gh pr merge --squash feature/phase3-task1_memory_client
gh pr merge --squash feature/phase3-task2_llm_parse_decision
gh pr merge --squash feature/phase3-task3_llm_evaluator_judge
```

- [ ] **Step 2: master 向け Phase Draft PR**

```bash
git fetch origin
git checkout feature/phase3_gateway_memory_llm__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase3_gateway_memory_llm__base \
  --title "Phase 3: MCP Gateway Memory + LLM 部品" \
  --body "## Summary
- MemoryClient (dashboard 経由のセマンティック検索)
- LLM 応答パーサ
- LlmEvaluator (Anthropic SDK + thinking)"
```

---

## Phase 4: CompositeEvaluator (Tier 1+2 オーケストレーション)

**Phase Base ブランチ:** `feature/phase4_composite_evaluator__base` (master から派生・Phase 1-3 マージ後)

### Task 4-1: CompositeEvaluator 実装 + Tier 1/2 フローテスト

**派生元:** `feature/phase4_composite_evaluator__base` (Phase 単独 task)

**ブランチ:** `feature/phase4-task1_composite_evaluator`

**Files:**
- Create: `src/mcp_gateway/policy/composite.py`
- Test: `tests/unit/test_mcp_gateway_composite.py`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase4_composite_evaluator__base origin/master
git push -u origin feature/phase4_composite_evaluator__base
git checkout -b feature/phase4-task1_composite_evaluator
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_composite.py`:

```python
"""Tests for CompositeEvaluator Tier 1/2 flow."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.composite import CompositeEvaluator
from mcp_gateway.policy.engine import EvaluationResult, Grant, PolicyEngine
from mcp_gateway.policy.llm_evaluator import LlmUnavailableError, ResponseParseError
from mcp_gateway.policy.memory_client import MemoryFetchError
from mcp_gateway.policy.models_evaluator import (
    Decision,
    MemoryItem,
    ToolCallInput,
)


def _make_policy_engine_mock(result: EvaluationResult) -> MagicMock:
    eng = MagicMock(spec=PolicyEngine)
    eng.evaluate_grant.return_value = Grant(
        intent="default",
        caps=frozenset(["bash"]),
        output_filter_profile="none",
        guardrails=MappingProxyType({}),
    )
    eng.evaluate_call.return_value = result
    return eng


def _make_evaluator(
    *,
    tier1_result: EvaluationResult,
    llm: MagicMock | None,
    memory: MagicMock | None,
    fallback: str = "allow",
) -> CompositeEvaluator:
    engine = _make_policy_engine_mock(tier1_result)
    return CompositeEvaluator(
        engine=engine,
        memory_client=memory,
        llm_evaluator=llm,
        default_intent="default",
        default_agent_id="claude-code",
        fallback_when_llm_not_configured=fallback,
    )


@pytest.mark.asyncio
async def test_tier1_deny_short_circuits() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock()
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="DENY", reason="forbidden"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "rm -rf /"}))
    assert out == Decision(decision="deny", reason="forbidden")
    llm.judge.assert_not_called()


@pytest.mark.asyncio
async def test_tier1_requires_approval_returns_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock()
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="REQUIRES_APPROVAL", reason="approval"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={}))
    assert out.decision == "ask"
    assert "manual approval" in (out.ask_message or "")
    llm.judge.assert_not_called()


@pytest.mark.asyncio
async def test_allow_with_no_llm_returns_allow_default_fallback() -> None:
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=None,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")


@pytest.mark.asyncio
async def test_allow_with_no_llm_returns_ask_when_fallback_is_ask() -> None:
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=None,
        memory=None,
        fallback="ask",
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_llm_allow_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="allow"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")
    llm.judge.assert_awaited_once()
    # Memories should default to [] when memory_client is None.
    kwargs = llm.judge.await_args.kwargs
    assert list(kwargs["memories"]) == []


@pytest.mark.asyncio
async def test_llm_deny_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="deny", reason="dangerous"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "deny"


@pytest.mark.asyncio
async def test_llm_ask_passes_through() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="ask", ask_message="confirm?"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_memory_fetch_failure_does_not_block_llm() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(return_value=Decision(decision="allow"))
    memory = MagicMock()
    memory.retrieve = AsyncMock(side_effect=MemoryFetchError("boom"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=memory,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out == Decision(decision="allow")
    # memory failure is swallowed: memories=[] is passed to LLM
    kwargs = llm.judge.await_args.kwargs
    assert list(kwargs["memories"]) == []


@pytest.mark.asyncio
async def test_llm_unavailable_falls_back_to_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(side_effect=LlmUnavailableError("timeout"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"
    assert "System evaluation failed" in (out.ask_message or "")


@pytest.mark.asyncio
async def test_llm_parse_error_falls_back_to_ask() -> None:
    llm = MagicMock()
    llm.judge = AsyncMock(side_effect=ResponseParseError("bad json"))
    ev = _make_evaluator(
        tier1_result=EvaluationResult(status="ALLOW"),
        llm=llm,
        memory=None,
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={"command": "ls"}))
    assert out.decision == "ask"


@pytest.mark.asyncio
async def test_policy_error_on_grant_returns_deny() -> None:
    engine = MagicMock(spec=PolicyEngine)
    engine.evaluate_grant.side_effect = PolicyError("unknown intent", reason="unknown_intent")
    ev = CompositeEvaluator(
        engine=engine,
        memory_client=None,
        llm_evaluator=None,
        default_intent="default",
        default_agent_id="claude-code",
    )
    out = await ev.evaluate(ToolCallInput(tool_name="bash", tool_input={}))
    assert out.decision == "deny"
    assert "unknown_intent" in (out.reason or "")


def test_startup_log_emits_warning(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="chronos_evaluator"):
        _make_evaluator(
            tier1_result=EvaluationResult(status="ALLOW"),
            llm=None,
            memory=None,
        )
    assert any("evaluator config" in r.message for r in caplog.records)
```

- [x] **Step 3: テスト失敗確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_composite.py -v
```

Expected: `ModuleNotFoundError` で FAIL

- [x] **Step 4: composite.py を実装**

`src/mcp_gateway/policy/composite.py`:

**設計要約**

- **クラス**: `CompositeEvaluator`
- **責務**:
  - Tier 1: 決定論的評価 (`PolicyEngine.evaluate_grant` → `evaluate_call`)
  - Tier 2: LLM 評価 (`LlmEvaluator.judge`)
  - メモリ取得: 失敗しても LLM 評価をブロックしない (`_fetch_memories_safely`)
- **決定フロー**:
  1. `evaluate_grant` で許可範囲を取得。例外時は `deny`
  2. `evaluate_call` でガードレール評価。`DENY` → `deny`、`REQUIRES_APPROVAL` → `ask`
  3. `ALLOW` の場合:
     - LLM 未設定 (`llm=None`) → `fallback_when_llm_not_configured` (\"allow\" または \"ask\") に従う
     - LLM 設定済み → `LlmEvaluator.judge` を呼び出し
     - `LlmUnavailableError` / `ResponseParseError` → ハードコードで `"ask"` にフォールバック

```python
class CompositeEvaluator:
    async def evaluate(self, input_: ToolCallInput) -> Decision: ...
    async def _fetch_memories_safely(self, input_: ToolCallInput) -> list[MemoryItem]: ...
    @staticmethod
    def _render_rules_for_prompt(grant: Grant, tool_name: str) -> str: ...
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_composite.py -v
```

Expected: 全 PASS

- [x] **Step 6: 既存 mcp_gateway テストへの回帰確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway.py tests/unit/test_param_constraint.py -v
```

Expected: 既存テスト PASS

- [x] **Step 7: ruff / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/policy/composite.py tests/unit/test_mcp_gateway_composite.py
uv run ruff format --check src/mcp_gateway/policy/composite.py tests/unit/test_mcp_gateway_composite.py
uv run mypy src/mcp_gateway/policy/composite.py
```

Expected: exit 0

- [x] **Step 8: コミット**

```bash
git add src/mcp_gateway/policy/composite.py tests/unit/test_mcp_gateway_composite.py
git commit -m "feat(mcp_gateway): add CompositeEvaluator (Tier1 deterministic + Tier2 LLM)"
git push -u origin feature/phase4-task1_composite_evaluator
```

- [x] **Step 9: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase4_composite_evaluator__base \
  --head feature/phase4-task1_composite_evaluator \
  --title "feat(mcp_gateway): CompositeEvaluator (Tier1+Tier2)" \
  --body "deterministic PolicyEngine の ALLOW 結果のみを LLM judge に委譲。memory 取得失敗は握りつぶし、LLM 失敗時は ask フォールバック (設計書 §4.3)。"
```

### Phase 4 完了処理

- [ ] **Step 1: Task PR を Phase Base にマージ**

```bash
gh pr merge --squash feature/phase4-task1_composite_evaluator
```

- [ ] **Step 2: master 向け Phase Draft PR**

```bash
git fetch origin
git checkout feature/phase4_composite_evaluator__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase4_composite_evaluator__base \
  --title "Phase 4: CompositeEvaluator" \
  --body "Tier1 deterministic + Tier2 LLM のオーケストレーション。fallback 経路と起動ログ含む。"
```

---

## Phase 5: CLI エントリポイント + サブコマンド振り分け + subprocess E2E

**Phase Base ブランチ:** `feature/phase5_evaluator_cli__base` (master から派生)

### Task 5-1: cli.py 実装 (stderr ロガー / stdin / stdout / exit code)

**派生元:** `feature/phase5_evaluator_cli__base` (Phase 単独 task の最初・CompositeEvaluator を使う)

**ブランチ:** `feature/phase5-task1_cli_main`

**Files:**
- Create: `src/mcp_gateway/cli.py`
- Test: `tests/unit/test_mcp_gateway_cli.py`

- [x] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase5_evaluator_cli__base origin/master
git push -u origin feature/phase5_evaluator_cli__base
git checkout -b feature/phase5-task1_cli_main
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_cli.py`:

```python
"""Tests for mcp_gateway.cli (stdin / stdout / exit codes)."""

from __future__ import annotations

import io
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.cli import main
from mcp_gateway.policy.models_evaluator import Decision


def _run_cli_with_input(payload: str, argv: list[str] | None = None) -> tuple[int, str, str]:
    """Run cli.main with patched stdin/stdout/stderr; return (code, stdout, stderr)."""
    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = main(argv or ["--json-io"])
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture(autouse=True)
def _patch_composite():
    """Patch CompositeEvaluator.from_env to return a mock by default."""
    fake = MagicMock()
    fake.evaluate = AsyncMock(return_value=Decision(decision="allow"))
    with patch("mcp_gateway.cli._build_composite_evaluator", return_value=fake) as m:
        yield m, fake


def test_allow_path_writes_single_line_json_and_exit_0(_patch_composite) -> None:
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    code, out, err = _run_cli_with_input(payload)
    assert code == 0
    assert out.count("\n") == 1
    assert json.loads(out.strip()) == {"decision": "allow"}


def test_deny_path_includes_reason(_patch_composite) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(return_value=Decision(decision="deny", reason="bad"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "rm"}})
    code, out, _ = _run_cli_with_input(payload)
    assert code == 0
    assert json.loads(out.strip()) == {"decision": "deny", "reason": "bad"}


def test_ask_path_includes_message(_patch_composite) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(return_value=Decision(decision="ask", ask_message="confirm"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {}})
    code, out, _ = _run_cli_with_input(payload)
    assert code == 0
    assert json.loads(out.strip()) == {"decision": "ask", "ask_message": "confirm"}


def test_empty_stdin_emits_fallback_ask_and_exit_2() -> None:
    code, out, _ = _run_cli_with_input("")
    assert code == 2
    body = json.loads(out.strip())
    assert body["decision"] == "ask"
    assert "System evaluation failed" in body["ask_message"]


def test_invalid_json_emits_fallback_ask_and_exit_2() -> None:
    code, out, _ = _run_cli_with_input("not-json")
    assert code == 2
    body = json.loads(out.strip())
    assert body["decision"] == "ask"


def test_unexpected_exception_emits_fallback_ask_and_exit_2(_patch_composite) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(side_effect=RuntimeError("boom"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    code, out, err = _run_cli_with_input(payload)
    assert code == 2
    body = json.loads(out.strip())
    assert body["decision"] == "ask"
    # traceback must go to stderr, never stdout
    assert "Traceback" in err
    assert "Traceback" not in out


def test_logger_output_goes_to_stderr_only(_patch_composite) -> None:
    # Configure a noisy logger before main(); main() must reroute it to stderr.
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    code, out, err = _run_cli_with_input(payload)
    # Single JSON line on stdout
    assert out.count("\n") == 1
    # No raw log lines on stdout
    assert "evaluator config" not in out


def test_main_returns_int_not_calls_sys_exit(_patch_composite) -> None:
    """main() should *return* the exit code; the __main__ shim invokes sys.exit."""
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = main(["--json-io"])
    assert isinstance(code, int)
```

- [x] **Step 3: テスト失敗確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_cli.py -v
```

Expected: `ModuleNotFoundError` で FAIL

- [x] **Step 4: cli.py を実装**

`src/mcp_gateway/cli.py`:

```python
"""Universal Evaluator CLI: `python -m mcp_gateway evaluate --json-io`.

stdin から JSON を読み、CompositeEvaluator で評価し、stdout にちょうど 1 行の
Decision JSON を書く。例外時も stdout には fallback ask JSON を必ず吐く。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import IO, Any

from mcp_gateway.policy.composite import CompositeEvaluator
from mcp_gateway.policy.engine import PolicyEngine
from mcp_gateway.policy.llm_evaluator import LlmEvaluator
from mcp_gateway.policy.loader import load_policy
from mcp_gateway.policy.memory_client import MemoryClient
from mcp_gateway.policy.models_evaluator import Decision, ToolCallInput

logger = logging.getLogger("chronos_evaluator.cli")

_FALLBACK_ASK = Decision(
    decision="ask",
    ask_message="System evaluation failed. Human confirmation required.",
)


def _configure_stderr_logging(level: str = "WARNING") -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
    for name in ("httpx", "httpcore", "anthropic", "asyncio"):
        logging.getLogger(name).setLevel("WARNING")


def _read_input(stream: IO[str]) -> ToolCallInput:
    raw = stream.read()
    if not raw or not raw.strip():
        raise ValueError("empty stdin")
    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"top-level must be object, got {type(data).__name__}")
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    context = data.get("context", {})
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name is required")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input must be object")
    if not isinstance(context, dict):
        raise ValueError("context must be object")
    return ToolCallInput(tool_name=tool_name, tool_input=tool_input, context=context)


def _write_decision(decision: Decision, stream: IO[str]) -> None:
    json.dump(decision.to_dict(), stream, ensure_ascii=False)
    stream.write("\n")
    stream.flush()


def _emit_fallback_ask(stream: IO[str]) -> None:
    _write_decision(_FALLBACK_ASK, stream)


def _build_composite_evaluator(policy_path: Path) -> CompositeEvaluator:
    policy = load_policy(policy_path)
    engine = PolicyEngine(policy)
    fallback = os.getenv("CHRONOS_EVALUATOR_FALLBACK", "allow")
    if fallback not in ("allow", "ask"):
        fallback = "allow"
    return CompositeEvaluator(
        engine=engine,
        memory_client=MemoryClient.from_env(),
        llm_evaluator=LlmEvaluator.from_env(),
        default_intent=os.getenv("CHRONOS_EVALUATOR_DEFAULT_INTENT", "default"),
        default_agent_id=os.getenv("CHRONOS_EVALUATOR_DEFAULT_AGENT_ID", "claude-code"),
        fallback_when_llm_not_configured=fallback,  # type: ignore[arg-type]
    )


def main(argv: list[str] | None = None) -> int:
    _configure_stderr_logging(os.getenv("CHRONOS_EVALUATOR_LOG_LEVEL", "WARNING"))

    parser = argparse.ArgumentParser(prog="mcp_gateway evaluate")
    # 設計書 §4.1 で CLI 契約として明示されている `--json-io` を required にして
    # 呼び出し側が明示的に JSON I/O モードを宣言することを強制する。値自体は
    # 参照しない (将来モード追加時の forward-compatible なマーカー)。
    parser.add_argument(
        "--json-io",
        action="store_true",
        required=True,
        help="enable JSON I/O mode (currently the only supported mode; required for forward compatibility)",
    )
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=Path(os.getenv("CHRONOS_EVALUATOR_POLICY_PATH", "intents.yaml")),
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        input_ = _read_input(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("stdin parse failed: %s", exc)
        _emit_fallback_ask(sys.stdout)
        return 2
    except Exception:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        _emit_fallback_ask(sys.stdout)
        return 2

    try:
        evaluator = _build_composite_evaluator(args.policy_path)
        decision = asyncio.run(evaluator.evaluate(input_))
        _write_decision(decision, sys.stdout)
        return 0
    except Exception:  # noqa: BLE001 - last-resort guard
        traceback.print_exc(file=sys.stderr)
        _emit_fallback_ask(sys.stdout)
        return 2
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_cli.py -v
```

Expected: 全 PASS

- [x] **Step 6: ruff (T20 check) / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/cli.py tests/unit/test_mcp_gateway_cli.py
uv run ruff format --check src/mcp_gateway/cli.py tests/unit/test_mcp_gateway_cli.py
uv run mypy src/mcp_gateway/cli.py
```

Expected: exit 0 (特に `print()` が含まれていれば T201 で fail するため、それを検出して修正)

- [x] **Step 7: コミット**

```bash
git add src/mcp_gateway/cli.py tests/unit/test_mcp_gateway_cli.py
git commit -m "feat(mcp_gateway): add evaluate CLI with stdout-purity guarantees"
git push -u origin feature/phase5-task1_cli_main
```

- [x] **Step 8: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase5_evaluator_cli__base \
  --head feature/phase5-task1_cli_main \
  --title "feat(mcp_gateway): evaluate CLI" \
  --body "stdin→JSON→CompositeEvaluator→stdout JSON 1行。例外時も fallback ask JSON + exit 2 (設計書 §4.1 / §5.2)。"
```

### Task 5-2: __main__.py のサブコマンド振り分け

**派生元:** `feature/phase5-task1_cli_main` (依存タスク・Task 5-1 の `cli.main` を呼ぶ)

**ブランチ:** `feature/phase5-task2_main_router`

**Files:**
- Modify: `src/mcp_gateway/__main__.py`

- [x] **Step 1: ブランチ作成 (Task 5-1 から派生)**

```bash
git fetch origin
git checkout feature/phase5-task1_cli_main
git pull --ff-only
git checkout -b feature/phase5-task2_main_router
```

- [x] **Step 2: 失敗するテストを書く**

`tests/unit/test_mcp_gateway_cli.py` の末尾に追記:

```python
from unittest.mock import patch


def test_main_routes_evaluate_to_cli(monkeypatch) -> None:
    from mcp_gateway import __main__ as gateway_main

    called = {}

    def fake_cli_main(argv: list[str]) -> int:
        called["argv"] = argv
        return 0

    monkeypatch.setattr("mcp_gateway.cli.main", fake_cli_main)
    monkeypatch.setattr("sys.argv", ["mcp_gateway", "evaluate", "--json-io"])
    with pytest.raises(SystemExit) as exc:
        gateway_main.main()
    assert exc.value.code == 0
    assert called["argv"] == ["--json-io"]


def test_main_defaults_to_serve_when_no_subcommand(monkeypatch) -> None:
    from mcp_gateway import __main__ as gateway_main

    called = {"serve": 0}

    def fake_serve() -> None:
        called["serve"] += 1

    monkeypatch.setattr(gateway_main, "_serve", fake_serve)
    monkeypatch.setattr("sys.argv", ["mcp_gateway"])
    gateway_main.main()
    assert called["serve"] == 1
```

- [x] **Step 3: 失敗確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_cli.py::test_main_routes_evaluate_to_cli -v
```

Expected: `AttributeError` で FAIL

- [x] **Step 4: __main__.py を書き換え**

`src/mcp_gateway/__main__.py` 全文:

```python
"""`python -m mcp_gateway [evaluate|<serve>]` entrypoint with lazy routing."""

from __future__ import annotations

import os
import sys
import traceback


def _serve() -> None:
    """Default behaviour: run uvicorn HTTP server (legacy mode)."""
    import uvicorn

    from mcp_gateway.audit.logger import AuditLogger

    try:
        host = os.getenv("MCP_GATEWAY_HOST", "127.0.0.1")
        port = int(os.getenv("MCP_GATEWAY_PORT", "9100"))
        uvicorn.run(
            "mcp_gateway.app:build_app",
            factory=True,
            host=host,
            port=port,
            log_level="info",
        )
    except Exception as e:  # noqa: BLE001
        AuditLogger().log(
            ev="startup_failure",
            level="ERROR",
            error=str(e),
            error_type=type(e).__name__,
            stacktrace=traceback.format_exc(),
        )
        sys.exit(1)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "evaluate":
        from mcp_gateway.cli import main as cli_main

        sys.exit(cli_main(sys.argv[2:]))
    _serve()


if __name__ == "__main__":
    main()
```

- [x] **Step 5: テスト通過確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway_cli.py -v
```

Expected: 新規 2 テスト含め全 PASS

- [x] **Step 6: ruff / mypy / format**

Run:

```bash
uv run ruff check src/mcp_gateway/__main__.py tests/unit/test_mcp_gateway_cli.py
uv run ruff format --check src/mcp_gateway/__main__.py tests/unit/test_mcp_gateway_cli.py
uv run mypy src/mcp_gateway/__main__.py
```

Expected: exit 0

- [x] **Step 7: 既存 mcp_gateway テストへの回帰確認**

Run:

```bash
uv run pytest tests/unit/test_mcp_gateway.py tests/unit/test_param_constraint.py -v
```

Expected: PASS

- [x] **Step 8: コミット**

```bash
git add src/mcp_gateway/__main__.py tests/unit/test_mcp_gateway_cli.py
git commit -m "feat(mcp_gateway): route 'evaluate' subcommand to cli.main"
git push -u origin feature/phase5-task2_main_router
```

- [x] **Step 9: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase5_evaluator_cli__base \
  --head feature/phase5-task2_main_router \
  --title "feat(mcp_gateway): __main__ で evaluate サブコマンドを振り分け" \
  --body "evaluate 経路では uvicorn / fastapi を一切 import せず、`cli.main` に委譲 (設計書 §2.1, §4.2)。"
```

### Task 5-3: subprocess E2E テスト

**派生元:** `feature/phase5-task2_main_router` (依存タスク・Task 5-1, 5-2 の両方を起動するプロセス E2E)

**ブランチ:** `feature/phase5-task3_subprocess_e2e`

**Files:**
- Create: `tests/integration/test_evaluator_cli_subprocess.py`
- Test fixture: 既存 `tests/data/policy_*.yaml` があれば再利用、なければ最小ポリシーを fixture でテンポラリ作成

- [x] **Step 1: ブランチ作成 (Task 5-2 から派生)**

```bash
git fetch origin
git checkout feature/phase5-task2_main_router
git pull --ff-only
git checkout -b feature/phase5-task3_subprocess_e2e
```

- [x] **Step 2: 既存 policy fixture を確認**

Run:

```bash
ls tests/unit/data/ 2>/dev/null
find tests -name '*intents*.yaml' -o -name 'policy*.yaml' 2>/dev/null
```

該当 fixture が無い場合はテスト内で `tmp_path` に最小 YAML を書き出す。以下のテストは tmp_path 方式を採用する。

- [x] **Step 3: 失敗するテストを書く**

`tests/integration/test_evaluator_cli_subprocess.py`:

```python
"""End-to-end subprocess tests for `python -m mcp_gateway evaluate`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

MINIMAL_POLICY = textwrap.dedent(
    """
    version: 1
    output_filters:
      none:
        type: none
    intents:
      default:
        description: default intent
        allowed_tools: ["bash"]
        output_filter: none
        guardrails:
          bash:
            params:
              command:
                type: string
                max_length: 4000
                pattern: "^(?!rm -rf /).*$"
    agents:
      claude-code:
        allowed_intents: ["default"]
    approvers: []
    """
)


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text(MINIMAL_POLICY)
    return p


def _run_cli(policy: Path, payload: dict, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "CHRONOS_DASHBOARD_URL": ""}
    env.update(env_overrides or {})
    env["CHRONOS_EVALUATOR_POLICY_PATH"] = str(policy)
    return subprocess.run(
        [sys.executable, "-m", "mcp_gateway", "evaluate", "--json-io",
         "--policy-path", str(policy)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def test_cli_evaluate_allow_path(policy_path: Path) -> None:
    result = _run_cli(policy_path, {"tool_name": "bash", "tool_input": {"command": "ls"}})
    assert result.returncode == 0
    assert result.stdout.count("\n") == 1
    body = json.loads(result.stdout.strip())
    assert body == {"decision": "allow"}


def test_cli_evaluate_deny_path(policy_path: Path) -> None:
    result = _run_cli(policy_path, {"tool_name": "bash", "tool_input": {"command": "rm -rf /"}})
    assert result.returncode == 0
    body = json.loads(result.stdout.strip())
    assert body["decision"] == "deny"


def test_cli_evaluate_invalid_stdin(policy_path: Path) -> None:
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "CHRONOS_DASHBOARD_URL": ""}
    env["CHRONOS_EVALUATOR_POLICY_PATH"] = str(policy_path)
    result = subprocess.run(
        [sys.executable, "-m", "mcp_gateway", "evaluate", "--json-io",
         "--policy-path", str(policy_path)],
        input="not-json",
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    assert result.returncode == 2
    body = json.loads(result.stdout.strip())
    assert body["decision"] == "ask"


def test_cli_evaluate_stdout_is_single_json_line(policy_path: Path) -> None:
    """Critical fail-safe invariant: stdout must always be exactly 1 JSON line."""
    result = _run_cli(policy_path, {"tool_name": "bash", "tool_input": {"command": "ls"}})
    # stdout: exactly 1 line ending with \n
    assert result.stdout.count("\n") == 1
    # That line must parse as JSON
    json.loads(result.stdout.strip())
    # stderr may contain logger output, but stdout must NOT
    assert "evaluator config" not in result.stdout
```

- [x] **Step 4: テスト失敗確認 (Devcontainer 内)**

Run:

```bash
uv run pytest tests/integration/test_evaluator_cli_subprocess.py -v
```

Expected: 既に Phase 5 Task 1, 2 がブランチ内に存在するので PASS が期待されるが、もし fixture や ENV の問題で FAIL したら原因を分析して修正。

- [x] **Step 5: ruff / format**

Run:

```bash
uv run ruff check tests/integration/test_evaluator_cli_subprocess.py
uv run ruff format --check tests/integration/test_evaluator_cli_subprocess.py
```

Expected: exit 0

- [x] **Step 6: コミット**

```bash
git add tests/integration/test_evaluator_cli_subprocess.py
git commit -m "test(integration): subprocess E2E for evaluate CLI"
git push -u origin feature/phase5-task3_subprocess_e2e
```

- [ ] **Step 7: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase5_evaluator_cli__base \
  --head feature/phase5-task3_subprocess_e2e \
  --title "test(integration): subprocess E2E for evaluate CLI" \
  --body "ANTHROPIC_API_KEY='' / CHRONOS_DASHBOARD_URL='' で LLM 未構成パスを CI で安定検証可能 (設計書 §6.3)。"
```

### Phase 5 完了処理

- [ ] **Step 1: Task PR を順序通りに Phase Base へマージ**

```bash
gh pr merge --squash feature/phase5-task1_cli_main
gh pr merge --squash feature/phase5-task2_main_router
gh pr merge --squash feature/phase5-task3_subprocess_e2e
```

- [ ] **Step 2: master 向け Phase Draft PR**

```bash
git fetch origin
git checkout feature/phase5_evaluator_cli__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase5_evaluator_cli__base \
  --title "Phase 5: Evaluator CLI + subprocess E2E" \
  --body "## Summary
- cli.py (stdin / stdout / stderr / exit code 厳格制御)
- __main__.py の lazy サブコマンド振り分け
- subprocess E2E テスト (CI 安定)"
```

---

## Phase 6: 運用統合 (Devcontainer 強制スクリプト + README)

**Phase Base ブランチ:** `feature/phase6_evaluator_ops__base` (master から派生・Phase 5 マージ後)

### Task 6-1: scripts/check_evaluator.sh の追加

**派生元:** `feature/phase6_evaluator_ops__base` (Phase 全ての成果物の検証スクリプトであり、Phase 5 までの master マージが前提)

**ブランチ:** `feature/phase6-task1_check_script`

**Files:**
- Create: `scripts/check_evaluator.sh`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin master
git checkout -b feature/phase6_evaluator_ops__base origin/master
git push -u origin feature/phase6_evaluator_ops__base
git checkout -b feature/phase6-task1_check_script
```

- [ ] **Step 2: スクリプト作成**

`scripts/check_evaluator.sh`:

```bash
#!/usr/bin/env bash
# Run all static analysis and tests for the Universal Evaluator inside the
# project's Devcontainer. Refuses to run on the host.
set -euo pipefail

# Devcontainer detection: explicit env vars only. Do NOT rely on /.dockerenv
# because that would pass for any container (e.g. `docker run python:3.12 ...`),
# silently running tests in an environment that may not have project deps.
if [ -z "${REMOTE_CONTAINERS:-}${CODESPACES:-}${DEVCONTAINER:-}" ]; then
    echo "ERROR: must run inside the project Devcontainer." >&2
    echo "       REMOTE_CONTAINERS / CODESPACES / DEVCONTAINER are all unset." >&2
    echo "" >&2
    echo "  How to fix:" >&2
    echo "    [VS Code]          choose 'Reopen in Container'" >&2
    echo "    [Codespaces]       CODESPACES=true is set automatically" >&2
    echo "    [devcontainer CLI] export DEVCONTAINER=1 (or rely on .devcontainer/setup.sh)" >&2
    exit 1
fi

echo "==> ruff check"
uv run ruff check \
    src/mcp_gateway/cli.py \
    src/mcp_gateway/policy/composite.py \
    src/mcp_gateway/policy/llm_evaluator.py \
    src/mcp_gateway/policy/memory_client.py \
    src/mcp_gateway/policy/models_evaluator.py \
    tests/unit/test_mcp_gateway_cli.py \
    tests/unit/test_mcp_gateway_composite.py \
    tests/unit/test_mcp_gateway_llm_evaluator.py \
    tests/unit/test_mcp_gateway_memory_client.py \
    tests/unit/test_mcp_gateway_evaluator_models.py \
    tests/integration/test_evaluator_cli_subprocess.py

echo "==> ruff format --check"
uv run ruff format --check \
    src/mcp_gateway \
    tests/unit/test_mcp_gateway_cli.py \
    tests/unit/test_mcp_gateway_composite.py \
    tests/unit/test_mcp_gateway_llm_evaluator.py \
    tests/unit/test_mcp_gateway_memory_client.py \
    tests/unit/test_mcp_gateway_evaluator_models.py \
    tests/integration/test_evaluator_cli_subprocess.py

echo "==> mypy"
uv run mypy src/mcp_gateway

echo "==> pytest (unit)"
uv run pytest \
    tests/unit/test_mcp_gateway_cli.py \
    tests/unit/test_mcp_gateway_composite.py \
    tests/unit/test_mcp_gateway_llm_evaluator.py \
    tests/unit/test_mcp_gateway_memory_client.py \
    tests/unit/test_mcp_gateway_evaluator_models.py \
    -v

echo "==> pytest (integration, subprocess E2E)"
uv run pytest tests/integration/test_evaluator_cli_subprocess.py -v

echo "==> all checks passed"
```

- [ ] **Step 3: 実行権限を付与**

```bash
chmod +x scripts/check_evaluator.sh
```

- [ ] **Step 4: ホストで実行を試み、拒否されることを確認**

Run (Devcontainer 外、つまりホストシェル):

```bash
unset REMOTE_CONTAINERS CODESPACES DEVCONTAINER 2>/dev/null
bash scripts/check_evaluator.sh
```

Expected: exit 1 + stderr に "must run inside the project Devcontainer."

- [ ] **Step 5: Devcontainer 内で実行し全チェックが通ることを確認**

Run (Devcontainer 内):

```bash
bash scripts/check_evaluator.sh
```

Expected: exit 0、"all checks passed" が表示される

- [ ] **Step 6: shellcheck**

Run (Devcontainer 内):

```bash
shellcheck scripts/check_evaluator.sh
```

Expected: exit 0 (shellcheck 未導入なら skip)

- [ ] **Step 7: コミット**

```bash
git add scripts/check_evaluator.sh
git commit -m "chore: add scripts/check_evaluator.sh (devcontainer-gated)"
git push -u origin feature/phase6-task1_check_script
```

- [ ] **Step 8: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase6_evaluator_ops__base \
  --head feature/phase6-task1_check_script \
  --title "chore: scripts/check_evaluator.sh (Devcontainer 強制)" \
  --body "REMOTE_CONTAINERS / CODESPACES / DEVCONTAINER のいずれも未設定なら exit 1。Devcontainer 内で ruff / format / mypy / pytest を一括実行 (設計書 §6.4)。"
```

### Task 6-2: README 運用ノート追加

**派生元:** `feature/phase6_evaluator_ops__base` (独立タスク・Task 6-1 のスクリプトを参照するが script 内容には依存せず文章のみ)

**ブランチ:** `feature/phase6-task2_readme`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: ブランチ作成**

```bash
git fetch origin
git checkout feature/phase6_evaluator_ops__base
git pull --ff-only
git checkout -b feature/phase6-task2_readme
```

- [ ] **Step 2: README に Universal Evaluator セクションを追加**

`README.md` の適切な箇所 (例: "## Components" の直後または末尾の "## Development" の直前) に以下を挿入:

```markdown
## Universal Evaluator (MCP Gateway)

`PreToolUse` Hook から呼び出され、AI エージェントの提案するツール呼び出しを
deterministic + LLM の二層で判定する CLI。設計書: `docs/superpowers/specs/2026-05-11-mcp-gateway-universal-evaluator-design.md`。

### 起動例

```bash
echo '{"tool_name":"bash","tool_input":{"command":"ls"}}' \
  | uv run python -m mcp_gateway evaluate --json-io \
    --policy-path /etc/chronos/intents.yaml
```

### 環境変数 (推奨値含む)

| 環境変数 | デフォルト | 本番推奨値 | 用途 |
|---------|----------|----------|------|
| `ANTHROPIC_API_KEY` | 未設定 | **設定必須** | 未設定なら LLM 評価をスキップ |
| `CHRONOS_EVALUATOR_MODEL` | `claude-haiku-4-5-20251001` | デフォルト可 | LLM モデル切替 |
| `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` | `10.0` | デフォルト可 | LLM タイムアウト |
| `CHRONOS_EVALUATOR_THINKING_BUDGET` | `1024` | デフォルト可 | thinking 上限 |
| `CHRONOS_DASHBOARD_URL` | 未設定 | **設定必須** | 未設定なら memory 取得をスキップ |
| `CHRONOS_DASHBOARD_API_KEY` | 未設定 | **--auth 起動時必須** | dashboard 認証 |
| `CHRONOS_EVALUATOR_FALLBACK` | `allow` | **`ask` を強く推奨** | LLM 未構成時の挙動 |
| `CHRONOS_EVALUATOR_POLICY_PATH` | (必須) | **設定必須** | intents.yaml のパス |
| `CHRONOS_EVALUATOR_DEFAULT_INTENT` | `default` | 環境次第 | intent 未指定時の既定 |
| `CHRONOS_EVALUATOR_DEFAULT_AGENT_ID` | `claude-code` | 環境次第 | agent_id 未指定時の既定 |
| `CHRONOS_EVALUATOR_LOG_LEVEL` | `WARNING` | デフォルト可 | stderr ログレベル |

### 起動ログの読み方

`CompositeEvaluator` は起動時に以下を stderr に WARNING で 1 行出力する:

```
evaluator config: llm=enabled memory=enabled fallback_when_llm_not_configured=ask
```

`llm=DISABLED` のときは LLM 評価が完全に無効化されている。`CHRONOS_EVALUATOR_FALLBACK=ask` 設定下では Tier 1 ALLOW でも常に `ask` 判定が返るため、運用者は必ず確認すること。

### 高リスクツール群の hook 構成 (推奨)

機微情報マスキングはキー名ベースのため、`bash` / `curl` / `Write` / `Edit` 等で **値の内部に埋め込まれた秘密** は検出できない。以下のいずれかを必ず適用する:

1. **hook 対象から除外**: クライアント側 `matcher` で対象外にする
2. **前段マスキング hook**: AST 解析 / URL parse / 正規表現スキャンで先にサニタイズ
3. **ツール側で秘密検出**: `truffleHog` / `gitleaks` 等で実行前に拒否

詳細は設計書 §5.4 を参照。

### Devcontainer 内チェック

```bash
# (ホスト) Devcontainer を開く
$ code .       # 「Reopen in Container」を選択
# (Devcontainer 内)
$ bash scripts/check_evaluator.sh
```

devcontainer CLI 利用時は以下のいずれか:

- `.devcontainer/docker-compose.yml` が設定する `DEVCONTAINER=1` を利用
- もしくは手動で `export DEVCONTAINER=1`
```

- [ ] **Step 3: markdownlint で検証**

Run (Devcontainer 内):

```bash
markdownlint-cli2 README.md || true
```

Expected: ホストで markdownlint-cli2 がインストールされていれば exit 0。なければ skip。

- [ ] **Step 4: README のリンク・コードブロック妥当性確認**

Run:

```bash
python -c 'open("README.md").read(); print("ok")'
```

Expected: `ok`

- [ ] **Step 5: コミット**

```bash
git add README.md
git commit -m "docs(readme): add Universal Evaluator usage and ops notes"
git push -u origin feature/phase6-task2_readme
```

- [ ] **Step 6: Phase Base 向け Draft PR**

```bash
gh pr create --draft \
  --base feature/phase6_evaluator_ops__base \
  --head feature/phase6-task2_readme \
  --title "docs(readme): Universal Evaluator 運用ノート" \
  --body "本番推奨環境変数表 / 起動ログの読み方 / 高リスクツール構成 / Devcontainer 利用手順 (設計書 §5.3, §5.4, §6.4)。"
```

### Phase 6 完了処理

- [ ] **Step 1: Task PR を Phase Base にマージ**

```bash
gh pr merge --squash feature/phase6-task1_check_script
gh pr merge --squash feature/phase6-task2_readme
```

- [ ] **Step 2: 最終 master 向け Phase Draft PR**

```bash
git fetch origin
git checkout feature/phase6_evaluator_ops__base
git pull --ff-only
gh pr create --draft \
  --base master \
  --head feature/phase6_evaluator_ops__base \
  --title "Phase 6: Evaluator 運用統合 (script + README)" \
  --body "## Summary
- scripts/check_evaluator.sh (Devcontainer 強制)
- README に運用ノート (環境変数 / 起動ログ / 高リスクツール / Devcontainer 手順)"
```

---

## Self-Review

### 1. Spec coverage

| 設計書セクション | 実装する Task |
|------------------|---------------|
| §0 サマリー (二層構造) | Phase 4 Task 4-1 |
| §1.1 二層構造採択 | Phase 4 Task 4-1 |
| §1.2 dashboard HTTP 経由 | Phase 2 Task 2-3 + Phase 3 Task 3-1 |
| §1.3 LLM オプション依存 | Phase 1 Task 1-2 (extras) + Phase 3 Task 3-3 (lazy import) |
| §1.4 モジュラー分離 | Phase 1, 3, 4, 5 のファイル分離 |
| §2 全体図 / §2.1 lazy import 境界 | Phase 5 Task 5-1, 5-2 |
| §2.2 stdout 純度 | Phase 5 Task 5-1 (_configure_stderr_logging) |
| §3 LLM プロンプト (system / user / cache_control) | Phase 3 Task 3-3 |
| §4.1 cli.py 仕様 | Phase 5 Task 5-1 |
| §4.2 __main__.py | Phase 5 Task 5-2 |
| §4.3 composite.py | Phase 4 Task 4-1 |
| §4.4 llm_evaluator.py | Phase 3 Task 3-2 + 3-3 |
| §4.5 memory_client.py | Phase 3 Task 3-1 |
| §4.6 dashboard 拡張 | Phase 2 Task 2-1, 2-2, 2-3 |
| §5.1 stdout 三重保証 + print() 禁止 | Phase 1 Task 1-2 (T20) + Phase 5 Task 5-1 |
| §5.2 fallback 状態遷移表 | Phase 4 Task 4-1 + Phase 5 Task 5-1 のテストで全網羅 |
| §5.3 環境変数 | Phase 5 Task 5-1 + Phase 6 Task 6-2 |
| §5.4 機微情報マスキング | Phase 1 Task 1-1 |
| §5.5 LLM 応答パース厳格化 | Phase 3 Task 3-2 |
| §6.1-6.4 テスト戦略 / Devcontainer 強制 | Phase 5 (テスト) + Phase 6 Task 6-1 |
| §6.5 pyproject.toml | Phase 1 Task 1-2 |
| §7 変更ファイル一覧 | 全 Phase で網羅 |
| §8 次ステップ (README 更新) | Phase 6 Task 6-2 |

### 2. Placeholder scan

- "TBD" / "TODO" / "implement later" / "適切に" / "Similar to" の使用なし
- 全 Task に完全な code block と exact command を記載
- ※ Task 2-3 Step 5 の `RetrievalPipeline.create_for_dashboard` は Task 2-1 で実装済み前提である。

### 3. Type consistency

- `Decision` / `ToolCallInput` / `MemoryItem` のシグネチャは Phase 1 Task 1-1 で確定し、Phase 3, 4, 5 全てで同じ field 名を使用
- `LlmEvaluator.judge` は keyword-only 引数 (`input_=`, `rules=`, `memories=`, `intent_name=`) として Phase 3 Task 3-3 / Phase 4 Task 4-1 で一貫
- `MemoryClient.retrieve` のシグネチャ (`query=`, `project=`) も Phase 3 Task 3-1 / Phase 4 Task 4-1 で一貫
- `_summarize_tool_input` / `_redact_tool_input_for_llm` は Phase 1 Task 1-1 で確定し、Phase 3 Task 3-3 / Phase 4 Task 4-1 で使用

### 4. Execution checklist 整合

- ✅ Phase 0 に CI/CD (master トリガー + ubuntu-slim) + Devcontainer (`DEVCONTAINER=1` export) を含む
- ✅ テスト・静的解析は全て Devcontainer 内実行 (各 Step で明示)
- ✅ Task は 50-200 行程度の改修に収まりレビュー可能
- ✅ 各 Task の派生元 (Base or 直前 Task) を本文に明記
- ✅ 各 Task の末尾で Phase Base 向け Draft PR 作成、Phase 完了時に master 向け Draft PR 作成

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-11-mcp-gateway-universal-evaluator.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
