# IBAC Guardrails & HITL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP Gateway の IBAC にパラメータ制約（Semantic Guardrails）と HITL 承認フロー（`REQUIRES_APPROVAL`）を追加し、ツール呼び出し時の引数を意味的に検証できるようにする。

**Architecture:** `PolicyEngine` に `evaluate_call()` メソッドを追加し、既存の `check_call()` を置き換える形で `server.py` に統合する。データモデルレイヤー（`models.py`）→ 承認通知レイヤー（`approval/notifier.py`）→ エンジンレイヤー（`engine.py`）→ サーバーレイヤー（`server.py` / `app.py`）の順序で段階的にマージする。既存の `ToolProxy` と `check_call()` は変更しない（後方互換維持）。

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest-asyncio, httpx（テスト用）, uv（パッケージ管理）

---

## ファイル構成

| ファイル | 種別 | 変更内容 |
|----------|------|---------|
| `src/mcp_gateway/policy/models.py` | 変更 | `ParamConstraint`, `ToolGuardrail` 追加、`IntentPolicy.guardrails` フィールド追加、`_verify_references` にバリデーション追加 |
| `src/mcp_gateway/policy/engine.py` | 変更 | `CallDecision` dataclass 追加、`evaluate_call()` メソッド追加 |
| `src/mcp_gateway/approval/__init__.py` | 新規 | パッケージ初期化 |
| `src/mcp_gateway/approval/notifier.py` | 新規 | `ApprovalRequest`, `ApprovalNotifier`, `LogOnlyApprovalNotifier` |
| `src/mcp_gateway/server.py` | 変更 | `build_router()` シグネチャ変更、`evaluate_call()` 統合 |
| `src/mcp_gateway/app.py` | 変更 | `engine` / `approval_notifier` DI 追加 |
| `src/mcp_gateway/policies/intents.example.yaml` | 変更 | `guardrails` サンプル追加 |
| `tests/unit/test_mcp_gateway.py` | 変更 | `TestIBACModels`, `TestApprovalNotifier`, `TestParamConstraint`, `TestEvaluateCall`, `TestServerRequiresApproval` 追加 |

---

## Git ブランチ戦略

```
master
├── feature/phase1_ibac-models__base
│   ├── feature/phase1-task1_model-tests       (base から派生)
│   └── feature/phase1-task2_model-impl        (task1 から派生)
├── feature/phase2_approval-notifier__base     (phase1 master マージ後)
│   ├── feature/phase2-task1_notifier-tests    (base から派生)
│   └── feature/phase2-task2_notifier-impl     (task1 から派生)
├── feature/phase3_evaluate-call__base         (phase2 master マージ後)
│   ├── feature/phase3-task1_engine-tests      (base から派生)
│   └── feature/phase3-task2_engine-impl       (task1 から派生)
└── feature/phase4_server-integration__base   (phase3 master マージ後)
    ├── feature/phase4-task1_yaml-update        (base から派生、独立)
    ├── feature/phase4-task2_server-tests       (base から派生、独立)
    ├── feature/phase4-task3_server-impl        (task2 から派生)
    └── feature/phase4-task4_app-di             (task3 から派生)
```

---

## Phase 1: データモデル拡張

**Phase ブランチ:** `feature/phase1_ibac-models__base`（`master` から作成）

Phase 1 では `models.py` に `ParamConstraint` / `ToolGuardrail` を追加し、`IntentPolicy` に `guardrails` フィールドを追加する。`GatewayPolicy._verify_references` では ReDoS 対策バリデーションも実装する。

```bash
git checkout master
git pull
git checkout -b feature/phase1_ibac-models__base
git push -u origin feature/phase1_ibac-models__base
```

---

### Task 1.1: TestIBACModels テスト作成

**ブランチ派生元:** `feature/phase1_ibac-models__base`（単体で完結する独立タスク）

**Files:**
- Modify: `tests/unit/test_mcp_gateway.py`

```bash
git checkout feature/phase1_ibac-models__base
git checkout -b feature/phase1-task1_model-tests
```

- [ ] **Step 1: テストクラスを追加する**

`tests/unit/test_mcp_gateway.py` の末尾（既存クラスの後）に以下を追記する。

```python
class TestIBACModels:
    """ParamConstraint / ToolGuardrail / IntentPolicy.guardrails の単体テスト。"""

    def test_param_constraint_defaults(self):
        from mcp_gateway.policy.models import ParamConstraint

        c = ParamConstraint()
        assert c.type is None
        assert c.max_length is None
        assert c.pattern is None
        assert c.allowed_values is None
        assert c.forbidden is False

    def test_param_constraint_accepts_all_fields(self):
        from mcp_gateway.policy.models import ParamConstraint

        c = ParamConstraint(
            type="string", max_length=100, pattern="^[a-z]+$", allowed_values=["foo"]
        )
        assert c.type == "string"
        assert c.max_length == 100
        assert c.pattern == "^[a-z]+$"
        assert c.allowed_values == ["foo"]

    def test_tool_guardrail_defaults(self):
        from mcp_gateway.policy.models import ToolGuardrail

        g = ToolGuardrail()
        assert g.params == {}
        assert g.requires_approval is False

    def test_intent_policy_accepts_guardrails(self):
        from mcp_gateway.policy.models import IntentPolicy, ParamConstraint, ToolGuardrail

        p = IntentPolicy(
            description="test",
            allowed_tools=["tool_a"],
            output_filter="f",
            guardrails={
                "tool_a": ToolGuardrail(
                    params={"q": ParamConstraint(max_length=512)},
                    requires_approval=False,
                )
            },
        )
        assert "tool_a" in p.guardrails
        assert p.guardrails["tool_a"].params["q"].max_length == 512

    def test_verify_references_guardrail_key_not_in_allowed_tools(self):
        from pydantic import ValidationError

        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError, match="guardrail"):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {"unlisted_tool": {}},
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_pattern_without_max_length_raises(self):
        from pydantic import ValidationError

        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {
                                "tool_a": {
                                    "params": {"query": {"pattern": "^[a-z]+$"}}
                                }
                            },
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_pattern_too_long_raises(self):
        from pydantic import ValidationError

        from mcp_gateway.policy.models import GatewayPolicy

        with pytest.raises(ValidationError):
            GatewayPolicy.model_validate(
                {
                    "version": 1,
                    "output_filters": {"f": {"type": "none"}},
                    "intents": {
                        "intent_a": {
                            "description": "x",
                            "allowed_tools": ["tool_a"],
                            "output_filter": "f",
                            "guardrails": {
                                "tool_a": {
                                    "params": {
                                        "query": {
                                            "pattern": "a" * 201,
                                            "max_length": 512,
                                        }
                                    }
                                }
                            },
                        }
                    },
                    "agents": {},
                }
            )

    def test_verify_references_valid_guardrail_passes(self):
        from mcp_gateway.policy.models import GatewayPolicy

        policy = GatewayPolicy.model_validate(
            {
                "version": 1,
                "output_filters": {"f": {"type": "none"}},
                "intents": {
                    "intent_a": {
                        "description": "x",
                        "allowed_tools": ["tool_a"],
                        "output_filter": "f",
                        "guardrails": {
                            "tool_a": {
                                "params": {
                                    "query": {
                                        "type": "string",
                                        "max_length": 512,
                                        "pattern": "^[^<>]+$",
                                    }
                                },
                                "requires_approval": False,
                            }
                        },
                    }
                },
                "agents": {},
            }
        )
        assert "tool_a" in policy.intents["intent_a"].guardrails
```

- [ ] **Step 2: テストが失敗することを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestIBACModels -v
```

期待出力: `ImportError` または `AttributeError`（`ParamConstraint` が未定義のため）

- [ ] **Step 3: コミット**

```bash
git add tests/unit/test_mcp_gateway.py
git commit -m "test(mcp-gateway): add TestIBACModels for ParamConstraint/ToolGuardrail"
git push -u origin feature/phase1-task1_model-tests
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase1_ibac-models__base \
  --head feature/phase1-task1_model-tests \
  --title "test: add TestIBACModels" \
  --draft \
  --body "Phase 1 / Task 1.1: ParamConstraint・ToolGuardrail・guardrails バリデーションのテストを追加する。"
```

---

### Task 1.2: ParamConstraint + ToolGuardrail + IntentPolicy.guardrails 実装

**ブランチ派生元:** `feature/phase1-task1_model-tests`（Task 1.1 のテストコードが前提）

**Files:**
- Modify: `src/mcp_gateway/policy/models.py`

```bash
git checkout feature/phase1-task1_model-tests
git checkout -b feature/phase1-task2_model-impl
```

- [ ] **Step 1: `models.py` に `ParamConstraint` と `ToolGuardrail` を追加する**

`from __future__ import annotations` の下の import 行に `Any` を追加し、`OutputFilterDef` の直後に以下を挿入する。

```python
# models.py の import を変更
from typing import Any, Literal, Self
```

`OutputFilterDef` クラスの直後（`IntentPolicy` の直前）に以下を追加する。

```python
class ParamConstraint(BaseModel):
    type: Literal["string", "integer", "number", "boolean"] | None = None
    max_length: int | None = None
    pattern: str | None = None
    allowed_values: list[str] | None = None
    forbidden: bool = False


class ToolGuardrail(BaseModel):
    params: dict[str, ParamConstraint] = {}
    requires_approval: bool = False
```

- [ ] **Step 2: `IntentPolicy` に `guardrails` フィールドを追加する**

```python
class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str] = Field(..., min_length=1)
    output_filter: str
    guardrails: dict[str, ToolGuardrail] = {}
```

- [ ] **Step 3: `GatewayPolicy._verify_references` にバリデーションを追加する**

既存の `return self` の直前（コメント `# 4. structural_allowlist の...` ブロックの後）に以下を追加する。

```python
        # 5. guardrails のキーは allowed_tools に含まれる必要がある（ReDoS 対策バリデーションも含む）
        for iname, intent in self.intents.items():
            allowed_set = set(intent.allowed_tools)
            for tool_name, guardrail in intent.guardrails.items():
                if tool_name not in allowed_set:
                    raise ValueError(
                        f"intent {iname!r} guardrail references unknown tool {tool_name!r}"
                    )
                for param_name, constraint in guardrail.params.items():
                    if constraint.pattern is not None:
                        if len(constraint.pattern) > 200:
                            raise ValueError(
                                f"intent {iname!r} tool {tool_name!r} param {param_name!r}: "
                                f"pattern exceeds 200 chars (ReDoS mitigation)"
                            )
                        if constraint.max_length is None:
                            raise ValueError(
                                f"intent {iname!r} tool {tool_name!r} param {param_name!r}: "
                                f"pattern requires max_length to be set (ReDoS mitigation)"
                            )
```

- [ ] **Step 4: テストが通ることを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestIBACModels -v
```

期待出力: 全テスト `PASSED`

- [ ] **Step 5: 型チェックとリントを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
uv run mypy src/mcp_gateway/policy/models.py
uv run ruff check src/mcp_gateway/policy/models.py
```

期待出力: エラーなし

- [ ] **Step 6: 既存テストへのリグレッションがないことを確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py -v -x
```

期待出力: 全テスト `PASSED`

- [ ] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/models.py
git commit -m "feat(mcp-gateway): add ParamConstraint, ToolGuardrail, and IntentPolicy.guardrails"
git push -u origin feature/phase1-task2_model-impl
```

- [ ] **Step 8: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase1_ibac-models__base \
  --head feature/phase1-task2_model-impl \
  --title "feat: add ParamConstraint, ToolGuardrail, IntentPolicy.guardrails" \
  --draft \
  --body "Phase 1 / Task 1.2: models.py に Semantic Guardrails 用のデータモデルを追加する。"
```

---

### Phase 1 完了: Phase Base の Draft PR を作成する

Task PR を Phase Base ブランチにマージ後、以下の Phase Draft PR を作成する。

```bash
gh pr create \
  --base master \
  --head feature/phase1_ibac-models__base \
  --title "feat(phase1): IBAC Guardrails data model extension" \
  --draft \
  --body "Phase 1: ParamConstraint / ToolGuardrail / IntentPolicy.guardrails を models.py に追加し、ReDoS 対策バリデーションを実装する。"
```

> **次 Phase の開始条件:** Phase 1 の PR が `master` にマージされるまで Phase 2 の作業を開始しない。

---

## Phase 2: Approval Notifier（独立）

**Phase ブランチ:** `feature/phase2_approval-notifier__base`（`master` から作成）

Phase 2 は Phase 1 に依存せず独立している。`approval/` パッケージを新設し、HITL 承認通知の抽象基底クラスと Log-only スタブを実装する。

```bash
git checkout master
git pull
git checkout -b feature/phase2_approval-notifier__base
git push -u origin feature/phase2_approval-notifier__base
```

---

### Task 2.1: TestApprovalNotifier テスト作成

**ブランチ派生元:** `feature/phase2_approval-notifier__base`（単体で完結する独立タスク）

**Files:**
- Modify: `tests/unit/test_mcp_gateway.py`

```bash
git checkout feature/phase2_approval-notifier__base
git checkout -b feature/phase2-task1_notifier-tests
```

- [ ] **Step 1: テストクラスを追加する**

`tests/unit/test_mcp_gateway.py` の末尾に以下を追記する。

```python
class TestApprovalNotifier:
    """LogOnlyApprovalNotifier の単体テスト。"""

    @pytest.mark.asyncio
    async def test_request_approval_does_not_raise(self):
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest, LogOnlyApprovalNotifier

        notifier = LogOnlyApprovalNotifier()
        req = ApprovalRequest(
            session_id="sid-001",
            agent_id="agent-a",
            intent="curate_memories",
            tool_name="memory_delete",
            arguments={"id": "m-xyz"},
            requested_at=datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC),
        )
        await notifier.request_approval(req)  # 例外が発生しないことを確認

    def test_approval_request_is_immutable(self):
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest

        req = ApprovalRequest(
            session_id="s",
            agent_id="a",
            intent="i",
            tool_name="t",
            arguments={},
            requested_at=datetime.now(UTC),
        )
        with pytest.raises((AttributeError, TypeError)):
            req.session_id = "mutated"  # type: ignore[misc]

    def test_approval_notifier_is_abstract(self):
        from mcp_gateway.approval.notifier import ApprovalNotifier

        with pytest.raises(TypeError):
            ApprovalNotifier()  # type: ignore[abstract]

    @pytest.mark.asyncio
    async def test_request_approval_logs(self, caplog):
        import logging
        from datetime import UTC, datetime

        from mcp_gateway.approval.notifier import ApprovalRequest, LogOnlyApprovalNotifier

        notifier = LogOnlyApprovalNotifier()
        req = ApprovalRequest(
            session_id="sid-log",
            agent_id="agent-b",
            intent="curate_memories",
            tool_name="memory_delete",
            arguments={"id": "m-abc"},
            requested_at=datetime.now(UTC),
        )
        with caplog.at_level(logging.INFO, logger="mcp_gateway.approval.notifier"):
            await notifier.request_approval(req)
        assert any("approval_required" in r.message for r in caplog.records)
```

- [ ] **Step 2: テストが失敗することを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestApprovalNotifier -v
```

期待出力: `ModuleNotFoundError: No module named 'mcp_gateway.approval'`

- [ ] **Step 3: コミット**

```bash
git add tests/unit/test_mcp_gateway.py
git commit -m "test(mcp-gateway): add TestApprovalNotifier"
git push -u origin feature/phase2-task1_notifier-tests
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase2_approval-notifier__base \
  --head feature/phase2-task1_notifier-tests \
  --title "test: add TestApprovalNotifier" \
  --draft \
  --body "Phase 2 / Task 2.1: ApprovalNotifier のテストを追加する。"
```

---

### Task 2.2: approval/ パッケージ実装

**ブランチ派生元:** `feature/phase2-task1_notifier-tests`（Task 2.1 のテストコードが前提）

**Files:**
- Create: `src/mcp_gateway/approval/__init__.py`
- Create: `src/mcp_gateway/approval/notifier.py`

```bash
git checkout feature/phase2-task1_notifier-tests
git checkout -b feature/phase2-task2_notifier-impl
```

- [ ] **Step 1: `approval/__init__.py` を作成する**

```python
```

（空ファイル）

- [ ] **Step 2: `approval/notifier.py` を作成する**

```python
"""HITL approval notifier: abstract base + log-only stub implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    session_id: str
    agent_id: str
    intent: str
    tool_name: str
    arguments: dict[str, Any]
    requested_at: datetime


class ApprovalNotifier(ABC):
    @abstractmethod
    async def request_approval(self, req: ApprovalRequest) -> None: ...


class LogOnlyApprovalNotifier(ApprovalNotifier):
    async def request_approval(self, req: ApprovalRequest) -> None:
        # TODO: Slack Webhook / CIBA event queue への送信に差し替える
        logging.getLogger(__name__).info(
            "approval_required sid=%s agent=%s intent=%s tool=%s args=%r requested_at=%s",
            req.session_id,
            req.agent_id,
            req.intent,
            req.tool_name,
            req.arguments,
            req.requested_at.isoformat(),
        )
```

- [ ] **Step 3: テストが通ることを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestApprovalNotifier -v
```

期待出力: 全テスト `PASSED`

- [ ] **Step 4: 型チェックとリントを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
uv run mypy src/mcp_gateway/approval/
uv run ruff check src/mcp_gateway/approval/
```

期待出力: エラーなし

- [ ] **Step 5: コミット**

```bash
git add src/mcp_gateway/approval/
git commit -m "feat(mcp-gateway): add ApprovalRequest, ApprovalNotifier, LogOnlyApprovalNotifier"
git push -u origin feature/phase2-task2_notifier-impl
```

- [ ] **Step 6: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase2_approval-notifier__base \
  --head feature/phase2-task2_notifier-impl \
  --title "feat: add approval package with LogOnlyApprovalNotifier" \
  --draft \
  --body "Phase 2 / Task 2.2: approval/ パッケージを新設し HITL 承認スタブを実装する。"
```

---

### Phase 2 完了: Phase Base の Draft PR を作成する

```bash
gh pr create \
  --base master \
  --head feature/phase2_approval-notifier__base \
  --title "feat(phase2): HITL ApprovalNotifier stub" \
  --draft \
  --body "Phase 2: approval/ パッケージに ApprovalRequest / ApprovalNotifier 抽象基底 / LogOnlyApprovalNotifier を実装する。"
```

> **次 Phase の開始条件:** Phase 2 の PR が `master` にマージされるまで Phase 3 の作業を開始しない。

---

## Phase 3: PolicyEngine 拡張（evaluate_call）

**Phase ブランチ:** `feature/phase3_evaluate-call__base`（`master` から作成、Phase 1 マージ済みが前提）

Phase 3 では `engine.py` に `CallDecision` dataclass と `evaluate_call()` メソッドを追加する。Phase 1 の `ParamConstraint` / `ToolGuardrail` が `master` に存在することが前提。

```bash
git checkout master
git pull  # Phase 1 がマージ済みであることを確認
git checkout -b feature/phase3_evaluate-call__base
git push -u origin feature/phase3_evaluate-call__base
```

---

### Task 3.1: TestParamConstraint + TestEvaluateCall テスト作成

**ブランチ派生元:** `feature/phase3_evaluate-call__base`（単体で完結する独立タスク）

**Files:**
- Modify: `tests/unit/test_mcp_gateway.py`

```bash
git checkout feature/phase3_evaluate-call__base
git checkout -b feature/phase3-task1_engine-tests
```

- [ ] **Step 1: `TestParamConstraint` クラスを追加する**

`tests/unit/test_mcp_gateway.py` の末尾に以下を追記する。

```python
class TestParamConstraint:
    """evaluate_call() を通じたパラメータ制約の動作テスト。"""

    def _make_engine_and_caps(
        self,
        tool_name: str,
        params: dict,
        *,
        requires_approval: bool = False,
        intent: str = "test_intent",
    ):
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                intent: IntentPolicy(
                    description="test",
                    allowed_tools=[tool_name],
                    output_filter="f",
                    guardrails={
                        tool_name: {
                            "params": params,
                            "requires_approval": requires_approval,
                        }
                    },
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=[intent])},
        )
        return PolicyEngine(policy), frozenset([tool_name])

    def _call(self, engine, caps, tool_name, arguments, intent="test_intent"):
        return engine.evaluate_call(
            caps=caps,
            tool_name=tool_name,
            arguments=arguments,
            intent=intent,
        )

    # --- max_length ---

    def test_max_length_boundary_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 512}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "a" * 512})
        assert result.status == "ALLOW"

    def test_max_length_exceeded_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 512}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "a" * 513})
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"

    def test_max_length_empty_string_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 512}}
        )
        result = self._call(engine, caps, "memory_search", {"query": ""})
        assert result.status == "ALLOW"

    # --- pattern ---

    def test_pattern_full_match_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[a-z_]+$"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "hello_world"})
        assert result.status == "ALLOW"

    def test_pattern_partial_match_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[a-z_]+$"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "hello world!"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_script_injection_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[^<>{};]*$"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "<script>alert(1)</script>"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    def test_pattern_unicode_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 100, "pattern": "^[a-z_]+$"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "こんにちは"})
        assert result.status == "DENY"
        assert result.reason == "param_pattern_mismatch:query"

    # --- allowed_values ---

    def test_allowed_values_in_list_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"mode": {"allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, caps, "memory_search", {"mode": "read"})
        assert result.status == "ALLOW"

    def test_allowed_values_not_in_list_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"mode": {"allowed_values": ["read", "write"]}}
        )
        result = self._call(engine, caps, "memory_search", {"mode": "admin"})
        assert result.status == "DENY"
        assert result.reason == "param_not_in_allowed_values:mode"

    # --- forbidden ---

    def test_forbidden_param_present_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"secret": {"forbidden": True}}
        )
        result = self._call(engine, caps, "memory_search", {"secret": "x"})
        assert result.status == "DENY"
        assert result.reason == "forbidden_param:secret"

    def test_forbidden_param_absent_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"secret": {"forbidden": True}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "hi"})
        assert result.status == "ALLOW"

    # --- missing param (absent params are not checked) ---

    def test_missing_constrained_param_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 512}}
        )
        result = self._call(engine, caps, "memory_search", {})
        assert result.status == "ALLOW"

    # --- type checks ---

    def test_type_mismatch_int_for_string_constraint_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"max_length": 512, "pattern": "^[a-z]+$"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_string_explicit_int_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"type": "string"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": 12345})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:query"

    def test_type_integer_bool_excluded_deny(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"count": {"type": "integer"}}
        )
        result = self._call(engine, caps, "memory_search", {"count": True})
        assert result.status == "DENY"
        assert result.reason == "param_type_mismatch:count"

    def test_type_string_correct_allow(self):
        engine, caps = self._make_engine_and_caps(
            "memory_search", {"query": {"type": "string"}}
        )
        result = self._call(engine, caps, "memory_search", {"query": "safe"})
        assert result.status == "ALLOW"
```

- [ ] **Step 2: `TestEvaluateCall` クラスを追加する**

```python
class TestEvaluateCall:
    """evaluate_call() 分岐全網羅テスト。"""

    def _policy(self):
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
            ParamConstraint,
            ToolGuardrail,
        )

        return GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                "read_only_recall": IntentPolicy(
                    description="x",
                    allowed_tools=["memory_search", "memory_stats"],
                    output_filter="f",
                    guardrails={
                        "memory_search": ToolGuardrail(
                            params={"query": ParamConstraint(max_length=512, pattern="^[^<>]*$")},
                            requires_approval=False,
                        )
                    },
                ),
                "curate_memories": IntentPolicy(
                    description="y",
                    allowed_tools=["memory_delete"],
                    output_filter="f",
                    guardrails={
                        "memory_delete": ToolGuardrail(requires_approval=True)
                    },
                ),
            },
            agents={
                "agent-a": AgentPolicy(
                    allowed_intents=["read_only_recall", "curate_memories"]
                )
            },
        )

    def _engine(self):
        from mcp_gateway.policy.engine import PolicyEngine

        return PolicyEngine(self._policy())

    def test_tool_not_in_caps_deny(self):
        eng = self._engine()
        result = eng.evaluate_call(
            caps=frozenset(["memory_search"]),
            tool_name="memory_delete",
            arguments={},
            intent="curate_memories",
        )
        assert result.status == "DENY"
        assert result.reason == "tool_not_in_caps"

    def test_unknown_intent_deny(self):
        eng = self._engine()
        result = eng.evaluate_call(
            caps=frozenset(["memory_search"]),
            tool_name="memory_search",
            arguments={},
            intent="ghost_intent",
        )
        assert result.status == "DENY"
        assert result.reason == "unknown_intent"

    def test_no_guardrail_allow(self):
        eng = self._engine()
        result = eng.evaluate_call(
            caps=frozenset(["memory_stats"]),
            tool_name="memory_stats",
            arguments={},
            intent="read_only_recall",
        )
        assert result.status == "ALLOW"

    def test_all_constraints_pass_allow(self):
        eng = self._engine()
        result = eng.evaluate_call(
            caps=frozenset(["memory_search"]),
            tool_name="memory_search",
            arguments={"query": "safe query"},
            intent="read_only_recall",
        )
        assert result.status == "ALLOW"

    def test_requires_approval_only_params_empty(self):
        eng = self._engine()
        result = eng.evaluate_call(
            caps=frozenset(["memory_delete"]),
            tool_name="memory_delete",
            arguments={},
            intent="curate_memories",
        )
        assert result.status == "REQUIRES_APPROVAL"

    def test_param_violation_beats_requires_approval(self):
        from mcp_gateway.policy.engine import PolicyEngine
        from mcp_gateway.policy.models import (
            AgentPolicy,
            GatewayPolicy,
            IntentPolicy,
            OutputFilterDef,
            ParamConstraint,
            ToolGuardrail,
        )

        policy = GatewayPolicy(
            version=1,
            output_filters={"f": OutputFilterDef(type="none")},
            intents={
                "intent_x": IntentPolicy(
                    description="x",
                    allowed_tools=["tool_a"],
                    output_filter="f",
                    guardrails={
                        "tool_a": ToolGuardrail(
                            params={"query": ParamConstraint(max_length=512)},
                            requires_approval=True,
                        )
                    },
                )
            },
            agents={"agent-a": AgentPolicy(allowed_intents=["intent_x"])},
        )
        eng = PolicyEngine(policy)
        result = eng.evaluate_call(
            caps=frozenset(["tool_a"]),
            tool_name="tool_a",
            arguments={"query": "a" * 600},
            intent="intent_x",
        )
        assert result.status == "DENY"
        assert result.reason == "param_too_long:query"
```

- [ ] **Step 3: テストが失敗することを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestParamConstraint tests/unit/test_mcp_gateway.py::TestEvaluateCall -v
```

期待出力: `AttributeError: 'PolicyEngine' object has no attribute 'evaluate_call'`

- [ ] **Step 4: コミット**

```bash
git add tests/unit/test_mcp_gateway.py
git commit -m "test(mcp-gateway): add TestParamConstraint and TestEvaluateCall"
git push -u origin feature/phase3-task1_engine-tests
```

- [ ] **Step 5: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase3_evaluate-call__base \
  --head feature/phase3-task1_engine-tests \
  --title "test: add TestParamConstraint and TestEvaluateCall" \
  --draft \
  --body "Phase 3 / Task 3.1: evaluate_call() の全分岐とパラメータ制約のテストを追加する。"
```

---

### Task 3.2: CallDecision + evaluate_call() 実装

**ブランチ派生元:** `feature/phase3-task1_engine-tests`（Task 3.1 のテストコードが前提）

**Files:**
- Modify: `src/mcp_gateway/policy/engine.py`

```bash
git checkout feature/phase3-task1_engine-tests
git checkout -b feature/phase3-task2_engine-impl
```

- [ ] **Step 1: `engine.py` の import を更新する**

既存の import ブロックを以下に置き換える。

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy, ParamConstraint
```

- [ ] **Step 2: `CallDecision` dataclass を追加する**

既存の `Grant` dataclass の直後に追加する。

```python
@dataclass(frozen=True, slots=True)
class CallDecision:
    status: Literal["ALLOW", "DENY", "REQUIRES_APPROVAL"]
    reason: str | None = None
```

- [ ] **Step 3: `PolicyEngine` に `evaluate_call()` と補助メソッドを追加する**

`check_call()` staticmethod の直後に以下を追加する。

```python
    def evaluate_call(
        self,
        *,
        caps: frozenset[str],
        tool_name: str,
        arguments: dict[str, Any],
        intent: str,
    ) -> CallDecision:
        if tool_name not in caps:
            return CallDecision(status="DENY", reason="tool_not_in_caps")

        intent_pol = self._policy.intents.get(intent)
        if intent_pol is None:
            return CallDecision(status="DENY", reason="unknown_intent")

        guardrail = intent_pol.guardrails.get(tool_name)
        if guardrail is None:
            return CallDecision(status="ALLOW")

        for param_name, constraint in guardrail.params.items():
            if param_name not in arguments:
                continue

            value = arguments[param_name]

            if constraint.forbidden:
                return CallDecision(status="DENY", reason=f"forbidden_param:{param_name}")

            if self._type_mismatch(value, constraint):
                return CallDecision(status="DENY", reason=f"param_type_mismatch:{param_name}")

            if constraint.max_length is not None and isinstance(value, str):
                if len(value) > constraint.max_length:
                    return CallDecision(status="DENY", reason=f"param_too_long:{param_name}")

            if constraint.pattern is not None and isinstance(value, str):
                if not re.fullmatch(constraint.pattern, value):
                    return CallDecision(
                        status="DENY", reason=f"param_pattern_mismatch:{param_name}"
                    )

            if constraint.allowed_values is not None:
                if value not in constraint.allowed_values:
                    return CallDecision(
                        status="DENY", reason=f"param_not_in_allowed_values:{param_name}"
                    )

        if guardrail.requires_approval:
            return CallDecision(status="REQUIRES_APPROVAL")

        return CallDecision(status="ALLOW")

    @staticmethod
    def _type_mismatch(value: Any, constraint: ParamConstraint) -> bool:
        ctype = constraint.type
        has_string_constraint = (
            constraint.max_length is not None or constraint.pattern is not None
        )

        if ctype is None and not has_string_constraint:
            return False

        if ctype == "string" or (ctype is None and has_string_constraint):
            return not isinstance(value, str)
        if ctype == "integer":
            return isinstance(value, bool) or not isinstance(value, int)
        if ctype == "number":
            return isinstance(value, bool) or not isinstance(value, (int, float))
        if ctype == "boolean":
            return not isinstance(value, bool)
        return False
```

- [ ] **Step 4: テストが通ることを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestParamConstraint tests/unit/test_mcp_gateway.py::TestEvaluateCall -v
```

期待出力: 全テスト `PASSED`

- [ ] **Step 5: 型チェックとリントを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
uv run mypy src/mcp_gateway/policy/engine.py
uv run ruff check src/mcp_gateway/policy/engine.py
```

期待出力: エラーなし

- [ ] **Step 6: 既存テストへのリグレッションがないことを確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py -v -x
```

期待出力: 全テスト `PASSED`

- [ ] **Step 7: コミット**

```bash
git add src/mcp_gateway/policy/engine.py
git commit -m "feat(mcp-gateway): add CallDecision and evaluate_call() to PolicyEngine"
git push -u origin feature/phase3-task2_engine-impl
```

- [ ] **Step 8: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase3_evaluate-call__base \
  --head feature/phase3-task2_engine-impl \
  --title "feat: add CallDecision and evaluate_call() to PolicyEngine" \
  --draft \
  --body "Phase 3 / Task 3.2: engine.py に CallDecision / evaluate_call() を実装する。"
```

---

### Phase 3 完了: Phase Base の Draft PR を作成する

```bash
gh pr create \
  --base master \
  --head feature/phase3_evaluate-call__base \
  --title "feat(phase3): PolicyEngine.evaluate_call() with semantic guardrails" \
  --draft \
  --body "Phase 3: engine.py に CallDecision dataclass と evaluate_call() を追加し、パラメータ制約（max_length / pattern / allowed_values / forbidden / type）を評価できるようにする。"
```

> **次 Phase の開始条件:** Phase 2 および Phase 3 の PR が両方とも `master` にマージされるまで Phase 4 の作業を開始しない。

---

## Phase 4: Server 統合

**Phase ブランチ:** `feature/phase4_server-integration__base`（`master` から作成、Phase 2 + Phase 3 マージ済みが前提）

Phase 4 では `server.py` の `tools/call` ハンドラを `evaluate_call()` ベースに切り替え、`app.py` の DI を更新する。また `intents.example.yaml` に guardrails サンプルを追加する。

```bash
git checkout master
git pull  # Phase 2 + Phase 3 がマージ済みであることを確認
git checkout -b feature/phase4_server-integration__base
git push -u origin feature/phase4_server-integration__base
```

---

### Task 4.1: intents.example.yaml に guardrails を追加する

**ブランチ派生元:** `feature/phase4_server-integration__base`（他タスクと独立）

**Files:**
- Modify: `src/mcp_gateway/policies/intents.example.yaml`

```bash
git checkout feature/phase4_server-integration__base
git checkout -b feature/phase4-task1_yaml-update
```

- [ ] **Step 1: `intents.example.yaml` を更新する**

以下の差分を適用する（既存エントリに `guardrails:` セクションを追加）。

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
    guardrails:
      memory_search:
        params:
          query:
            type: string
            max_length: 512
            pattern: "^[^<>{};]*$"

  curate_memories:
    description: "Curate own working memory. Search/save/delete; no external URL."
    allowed_tools: [memory_search, memory_save, memory_delete, memory_prune]
    output_filter: curator_full
    guardrails:
      memory_delete:
        requires_approval: true

  ingest_external_url:
    description: "External URL ingestion only."
    allowed_tools: [memory_save_url]
    output_filter: url_ingestion
    guardrails:
      memory_save_url:
        params:
          url:
            type: string
            max_length: 2048
            pattern: "^https?://.+"

agents:
  summarizer-bot:
    allowed_intents: [read_only_recall]
  curator-bot:
    allowed_intents: [read_only_recall, curate_memories]
  ingestion-bot:
    allowed_intents: [ingest_external_url]
```

- [ ] **Step 2: YAML ロードが成功することを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
python -c "
from importlib.resources import as_file, files
from mcp_gateway.policy.loader import load_policy
r = files('mcp_gateway').joinpath('policies/intents.example.yaml')
with as_file(r) as p:
    policy = load_policy(p)
print('OK:', list(policy.intents.keys()))
"
```

期待出力: `OK: ['read_only_recall', 'curate_memories', 'ingest_external_url']`

- [ ] **Step 3: コミット**

```bash
git add src/mcp_gateway/policies/intents.example.yaml
git commit -m "docs(mcp-gateway): add guardrails examples to intents.example.yaml"
git push -u origin feature/phase4-task1_yaml-update
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase4_server-integration__base \
  --head feature/phase4-task1_yaml-update \
  --title "docs: add guardrails examples to intents.example.yaml" \
  --draft \
  --body "Phase 4 / Task 4.1: intents.example.yaml に guardrails サンプルを追加する。"
```

---

### Task 4.2: TestServerRequiresApproval テスト作成

**ブランチ派生元:** `feature/phase4_server-integration__base`（Task 4.1 と独立）

**Files:**
- Modify: `tests/unit/test_mcp_gateway.py`

```bash
git checkout feature/phase4_server-integration__base
git checkout -b feature/phase4-task2_server-tests
```

- [ ] **Step 1: `TestServerRequiresApproval` クラスを追加する**

`tests/unit/test_mcp_gateway.py` の末尾に以下を追記する。

```python
class TestServerRequiresApproval:
    """REQUIRES_APPROVAL パスの /messages エンドポイントテスト。"""

    @pytest.fixture
    def approval_app(self, tmp_path, monkeypatch):
        policy = tmp_path / "intents.yaml"
        policy.write_text(
            textwrap.dedent(
                """
                version: 1
                output_filters:
                  f:
                    type: none
                intents:
                  curate_memories:
                    description: "x"
                    allowed_tools: [memory_delete]
                    output_filter: f
                    guardrails:
                      memory_delete:
                        requires_approval: true
                agents:
                  agent-a:
                    allowed_intents: [curate_memories]
                """
            ).lstrip()
        )
        monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(policy))
        monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"agent-a":"ck_x"}')

        from unittest.mock import AsyncMock

        from mcp_gateway.app import build_app

        upstream = AsyncMock()
        upstream.list_tools.return_value = [{"name": "memory_delete"}]
        return build_app(
            upstream_override=upstream,
            initial_tools=upstream.list_tools.return_value,
        )

    @pytest_asyncio.fixture
    async def approval_client(self, approval_app):
        import httpx
        from httpx import ASGITransport

        transport = ASGITransport(app=approval_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield client

    async def _get_session_id(self, client) -> str:
        async with client.stream(
            "GET",
            "/sse",
            headers={"Authorization": "Bearer ck_x", "X-MCP-Intent": "curate_memories"},
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data:") and "session_id=" in line:
                    data = line[len("data:"):].strip()
                    return data.split("session_id=")[1]
        raise AssertionError("SSE endpoint event did not return session_id")

    @pytest.mark.asyncio
    async def test_requires_approval_returns_32001(self, approval_client):
        sid = await self._get_session_id(approval_client)
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "memory_delete", "arguments": {"id": "m-001"}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32001
        assert body["error"]["message"] == "approval_required"
        assert "session_id" in body["error"]["data"]

    @pytest.mark.asyncio
    async def test_requires_approval_audit_log(self, approval_client, capsys):
        sid = await self._get_session_id(approval_client)
        await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "memory_delete", "arguments": {}},
            },
        )
        captured = capsys.readouterr()
        assert "requires_approval" in captured.err

    @pytest.mark.asyncio
    async def test_caps_denied_returns_32601(self, approval_client):
        sid = await self._get_session_id(approval_client)
        resp = await approval_client.post(
            f"/messages?session_id={sid}",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "admin_tool", "arguments": {}},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert body["error"]["message"] == "tool not found"
```

- [ ] **Step 2: テストが失敗することを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestServerRequiresApproval -v
```

期待出力: `-32001` が返らず `-32601` が返る（`evaluate_call()` がまだ統合されていないため）

- [ ] **Step 3: コミット**

```bash
git add tests/unit/test_mcp_gateway.py
git commit -m "test(mcp-gateway): add TestServerRequiresApproval"
git push -u origin feature/phase4-task2_server-tests
```

- [ ] **Step 4: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase4_server-integration__base \
  --head feature/phase4-task2_server-tests \
  --title "test: add TestServerRequiresApproval" \
  --draft \
  --body "Phase 4 / Task 4.2: /messages エンドポイントの REQUIRES_APPROVAL パスのテストを追加する。"
```

---

### Task 4.3: server.py の build_router() 改修

**ブランチ派生元:** `feature/phase4-task2_server-tests`（Task 4.2 のテストが前提）

**Files:**
- Modify: `src/mcp_gateway/server.py`

```bash
git checkout feature/phase4-task2_server-tests
git checkout -b feature/phase4-task3_server-impl
```

- [ ] **Step 1: `server.py` の import ブロックを更新する**

既存の import ブロック（`from __future__ import annotations` から始まる部分）を以下に置き換える。

```python
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from mcp_gateway.approval.notifier import ApprovalNotifier, ApprovalRequest
from mcp_gateway.audit.logger import AuditLogger
from mcp_gateway.auth.handshake import HandshakeService
from mcp_gateway.auth.session import SessionRegistry
from mcp_gateway.errors import AuthError, PolicyError, SessionError, UpstreamError
from mcp_gateway.filters.factory import build_filter
from mcp_gateway.policy.engine import CallDecision, PolicyEngine
from mcp_gateway.policy.models import GatewayPolicy
from mcp_gateway.tools.proxy import ToolProxy, _contains_secret
from mcp_gateway.tools.registry import ToolRegistry
```

- [ ] **Step 2: `build_router()` のシグネチャを変更する**

既存の `def build_router(...)` を以下に置き換える。

```python
def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,
    approval_notifier: ApprovalNotifier,
) -> APIRouter:
```

- [ ] **Step 3: `tools/call` ハンドラの caps チェックを `evaluate_call()` に置き換える**

`server.py` の `if tool_name not in record.caps:` ブロック（line 170〜185 付近）を以下に置き換える。

**置き換え前（削除するコード）:**
```python
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
```

**置き換え後（挿入するコード）:**
```python
            decision = engine.evaluate_call(
                caps=record.caps,
                tool_name=tool_name,
                arguments=arguments,
                intent=record.intent,
            )

            match decision.status:
                case "DENY":
                    audit.log(
                        ev="call",
                        decision="deny",
                        reason=decision.reason,
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
                case "REQUIRES_APPROVAL":
                    if any(_contains_secret(v) for v in arguments.values()):
                        audit.log(
                            ev="call",
                            decision="deny",
                            reason="secret_in_approval_args",
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
                    audit.log(
                        ev="call",
                        decision="requires_approval",
                        agent=record.agent_id,
                        sid=sid,
                        tool=tool_name,
                    )
                    await approval_notifier.request_approval(
                        ApprovalRequest(
                            session_id=record.session_id,
                            agent_id=record.agent_id,
                            intent=record.intent,
                            tool_name=tool_name,
                            arguments=arguments,
                            requested_at=datetime.now(UTC),
                        )
                    )
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": {
                                "code": -32001,
                                "message": "approval_required",
                                "data": {"session_id": record.session_id},
                            },
                        }
                    )
                case "ALLOW":
                    pass
```

- [ ] **Step 4: テストが通ることを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py::TestServerRequiresApproval -v
```

期待出力: **FAIL**（`app.py` がまだ `engine` / `approval_notifier` を渡していないため `TypeError`）

- [ ] **Step 5: 型チェックとリントを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
uv run mypy src/mcp_gateway/server.py
uv run ruff check src/mcp_gateway/server.py
```

期待出力: エラーなし（`app.py` 側の `TypeError` は mypy では検出されない）

- [ ] **Step 6: コミット**

```bash
git add src/mcp_gateway/server.py
git commit -m "feat(mcp-gateway): integrate evaluate_call() into build_router and add approval dispatch"
git push -u origin feature/phase4-task3_server-impl
```

- [ ] **Step 7: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase4_server-integration__base \
  --head feature/phase4-task3_server-impl \
  --title "feat: integrate evaluate_call() into server build_router" \
  --draft \
  --body "Phase 4 / Task 4.3: server.py の tools/call ハンドラを evaluate_call() ベースに切り替え、REQUIRES_APPROVAL 分岐を追加する。"
```

---

### Task 4.4: app.py の DI 更新

**ブランチ派生元:** `feature/phase4-task3_server-impl`（server.py のシグネチャ変更が前提）

**Files:**
- Modify: `src/mcp_gateway/app.py`

```bash
git checkout feature/phase4-task3_server-impl
git checkout -b feature/phase4-task4_app-di
```

- [ ] **Step 1: `app.py` の import ブロックに `LogOnlyApprovalNotifier` を追加する**

既存の import ブロックに以下を追加する。

```python
from mcp_gateway.approval.notifier import LogOnlyApprovalNotifier
```

- [ ] **Step 2: `build_router()` 呼び出しに `engine` と `approval_notifier` を追加する**

`app.py` の `build_router(...)` 呼び出し箇所を以下に更新する。

```python
    app.include_router(
        build_router(
            handshake=handshake,
            sessions=sessions,
            tool_registry=registry,
            upstream=upstream,
            policy=policy,
            audit=audit,
            engine=engine,
            approval_notifier=LogOnlyApprovalNotifier(),
        )
    )
```

- [ ] **Step 3: 全テストが通ることを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
pytest tests/unit/test_mcp_gateway.py -v -x
```

期待出力: 全テスト `PASSED`

- [ ] **Step 4: 型チェックとリントを Devcontainer 内で確認する**

```bash
# Devcontainer 内で実行
uv run mypy src/mcp_gateway/
uv run ruff check src/mcp_gateway/
uv run ruff format --check src/mcp_gateway/
```

期待出力: エラーなし

- [ ] **Step 5: コミット**

```bash
git add src/mcp_gateway/app.py
git commit -m "feat(mcp-gateway): wire engine and LogOnlyApprovalNotifier into build_app DI"
git push -u origin feature/phase4-task4_app-di
```

- [ ] **Step 6: Phase Base に向けた Draft PR を作成する**

```bash
gh pr create \
  --base feature/phase4_server-integration__base \
  --head feature/phase4-task4_app-di \
  --title "feat: wire engine and approval_notifier into app.py DI" \
  --draft \
  --body "Phase 4 / Task 4.4: app.py に LogOnlyApprovalNotifier をインスタンス化し build_router() へ渡す。"
```

---

### Phase 4 完了: Phase Base の Draft PR を作成する

全 Task PR を Phase Base ブランチにマージ後、以下を実行する。

```bash
gh pr create \
  --base master \
  --head feature/phase4_server-integration__base \
  --title "feat(phase4): server integration with evaluate_call and HITL approval" \
  --draft \
  --body "Phase 4: server.py を evaluate_call() ベースに切り替え、REQUIRES_APPROVAL パスで LogOnlyApprovalNotifier を呼び出す。app.py の DI を更新し、intents.example.yaml に guardrails サンプルを追加する。"
```

---

## Self-Review

設計書との対応チェック：

| 設計書セクション | 実装タスク | ステータス |
|----------------|-----------|----------|
| §3 `ParamConstraint` / `ToolGuardrail` モデル | Phase 1 Task 1.2 | ✅ |
| §3 `IntentPolicy.guardrails` フィールド | Phase 1 Task 1.2 | ✅ |
| §3 `_verify_references` バリデーション（guardrail key / ReDoS） | Phase 1 Task 1.2 | ✅ |
| §4 `CallDecision` dataclass | Phase 3 Task 3.2 | ✅ |
| §4 `evaluate_call()` 評価順序（forbidden → type → max_length → pattern → allowed_values） | Phase 3 Task 3.2 | ✅ |
| §4 ReDoS 対策（pattern は max_length の後） | Phase 3 Task 3.2 + Phase 1 Task 1.2 | ✅ |
| §5 `intents.example.yaml` 拡張 | Phase 4 Task 4.1 | ✅ |
| §6 `ApprovalRequest` / `ApprovalNotifier` / `LogOnlyApprovalNotifier` | Phase 2 Task 2.2 | ✅ |
| §7 `build_router()` シグネチャ変更 | Phase 4 Task 4.3 | ✅ |
| §7 `tools/call` ハンドラの `evaluate_call()` 統合 | Phase 4 Task 4.3 | ✅ |
| §7 シークレット検証（REQUIRES_APPROVAL 前） | Phase 4 Task 4.3 | ✅ |
| §7 `app.py` DI 更新 | Phase 4 Task 4.4 | ✅ |
| §8 エラーコード `-32601` / `-32001` | Phase 4 Task 4.3 | ✅ |
| §9 `TestParamConstraint` テストケース | Phase 3 Task 3.1 | ✅ |
| §9 `TestEvaluateCall` テストケース | Phase 3 Task 3.1 | ✅ |
| §9 `TestApprovalNotifier` テストケース | Phase 2 Task 2.1 | ✅ |
| §9 `TestServerRequiresApproval` テストケース | Phase 4 Task 4.2 | ✅ |
| §9 `TestIBACModels`（モデルバリデーション） | Phase 1 Task 1.1 | ✅ |
