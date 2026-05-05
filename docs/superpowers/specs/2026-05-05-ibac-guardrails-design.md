# MCP Gateway IBAC Guardrails & HITL Design

**Date:** 2026-05-05  
**Status:** Approved  
**Scope:** `src/mcp_gateway/` — 破壊的変更なし

---

## 1. 背景と目的

MCP Gateway では既にハンドシェイク時の Intent ベースアクセス制御（IBAC）が実装されている。  
本設計は以下の3つのギャップを埋める拡張を定義する。

| # | ギャップ | 対応 |
|---|----------|------|
| 1 | `IntentPolicy` にパラメータ制約（Semantic Guardrails）が未定義 | `models.py` 拡張 |
| 2 | ツール引数の意味的検証ロジックが未実装 | `engine.py` 拡張 |
| 3 | `REQUIRES_APPROVAL` ステータスと HITL スタブが未実装 | `approval/notifier.py` 新設 |

### コアセキュリティ思想

- **IBAC（Intent-Based Access Control）**: タスクセッションの「意図」に紐づいた制御
- **ゼロ・スタンディング・権限**: エージェントには永続的な権限を与えない
- **認可ギャップの解消**: 入力（引数）と出力（レスポンス）の両方を検証

---

## 2. アーキテクチャ概要

### 選択アプローチ：PolicyEngine 中心 + server.py での判断分岐

```
GET /sse (handshake)
  └─ PolicyEngine.evaluate_grant()  ← 既存（変更なし）
  └─ SessionRecord { caps, intent, ... }

POST /messages (tools/call)
  └─ PolicyEngine.evaluate_call()   ← 新規
        ├─ caps チェック
        ├─ Semantic Guardrails 評価（パラメータ制約）
        └─ requires_approval フラグ確認
  └─ [DENY]             → audit log + error -32601
  └─ [REQUIRES_APPROVAL] → ApprovalNotifier.request_approval() + error -32001
  └─ [ALLOW]            → ToolProxy.call_through()  ← 変更なし
```

**既存の `check_call()` と `ToolProxy` は変更なし**（後方互換を完全維持）。

---

## 3. データモデル拡張（`policy/models.py`）

### 新規モデル

```python
class ParamConstraint(BaseModel):
    type: Literal["string", "integer", "number", "boolean"] | None = None
    max_length: int | None = None
    pattern: str | None = None          # re.fullmatch で検証
    allowed_values: list[str] | None = None
    forbidden: bool = False             # 引数そのものを禁止

class ToolGuardrail(BaseModel):
    params: dict[str, ParamConstraint] = {}
    requires_approval: bool = False     # HITL 対象フラグ
```

### `IntentPolicy` への追加フィールド

```python
class IntentPolicy(BaseModel):
    description: str
    allowed_tools: list[str] = Field(..., min_length=1)
    output_filter: str
    guardrails: dict[str, ToolGuardrail] = {}  # tool_name -> ToolGuardrail（省略可）
```

### バリデーション拡張（`GatewayPolicy._verify_references`）

- `guardrails` のキー（tool_name）が `allowed_tools` に含まれるかを検証
- 不整合は起動時 `PolicyError` としてフェイルファスト

---

## 4. PolicyEngine 拡張（`policy/engine.py`）

### 新規型

```python
@dataclass(frozen=True, slots=True)
class CallDecision:
    status: Literal["ALLOW", "DENY", "REQUIRES_APPROVAL"]
    reason: str | None = None
```

### 新規メソッド `evaluate_call()`

```python
def evaluate_call(
    self,
    *,
    caps: frozenset[str],
    tool_name: str,
    arguments: dict[str, Any],
    intent: str,
) -> CallDecision:
```

**評価順序：**

1. `tool_name not in caps` → `DENY` (reason: `tool_not_in_caps`)
2. `intent` が未知 → `DENY` (reason: `unknown_intent`)
3. `guardrail` が存在しない → `ALLOW`（ガードレール未定義 = 制約なし）
4. パラメータ制約評価（`forbidden` → `max_length` → `pattern` → `allowed_values`）
5. `requires_approval: true` → `REQUIRES_APPROVAL`
6. 全通過 → `ALLOW`

**`re.fullmatch`** を使用するため `pattern` は部分一致ではなく完全マッチ。

---

## 5. intents.example.yaml 拡張

既存エントリへの後方互換を維持しつつ `guardrails` を追加：

```yaml
intents:
  read_only_recall:
    # ...（既存フィールド）
    guardrails:
      memory_search:
        params:
          query:
            type: string
            max_length: 512
            pattern: "^[^<>{};]*$"   # スクリプトインジェクション防止

  curate_memories:
    # ...
    guardrails:
      memory_delete:
        requires_approval: true       # 削除操作はHITL承認が必要

  ingest_external_url:
    # ...
    guardrails:
      memory_save_url:
        params:
          url:
            type: string
            max_length: 2048
            pattern: "^https?://.+"   # http/https のみ許可
```

---

## 6. REQUIRES_APPROVAL スタブ（新規 `approval/notifier.py`）

```
src/mcp_gateway/approval/
    __init__.py
    notifier.py
```

### 抽象基底

```python
class ApprovalNotifier(ABC):
    @abstractmethod
    async def request_approval(self, req: ApprovalRequest) -> None: ...
```

### 現行実装（スタブ）

```python
class LogOnlyApprovalNotifier(ApprovalNotifier):
    async def request_approval(self, req: ApprovalRequest) -> None:
        # TODO: Slack Webhook / CIBA event queue への送信
        logging.getLogger(__name__).info(...)
```

**将来の拡張ポイント：**
- `SlackApprovalNotifier(webhook_url=...)` を実装して差し替え
- `CIBANotifier(queue_url=...)` でイベントキューへ投入
- `app.py` の DI を変更するだけで切り替え可能

---

## 7. server.py 改修

### `build_router()` シグネチャ変更

```python
def build_router(
    *,
    handshake: HandshakeService,
    sessions: SessionRegistry,
    tool_registry: ToolRegistry,
    upstream: Any,
    policy: GatewayPolicy,
    audit: AuditLogger,
    engine: PolicyEngine,                      # 追加
    approval_notifier: ApprovalNotifier,       # 追加
) -> APIRouter:
```

### `tools/call` ハンドラの変更点

既存の `if tool_name not in record.caps:` ブロックを `evaluate_call()` 呼び出しに置き換え：

```python
decision = engine.evaluate_call(
    caps=record.caps,
    tool_name=tool_name,
    arguments=arguments,
    intent=record.intent,
)

match decision.status:
    case "DENY":
        audit.log(ev="call", decision="deny", reason=decision.reason, ...)
        return JSONResponse({"error": {"code": -32601, "message": "tool not found"}})
    case "REQUIRES_APPROVAL":
        audit.log(ev="call", decision="requires_approval", ...)
        await approval_notifier.request_approval(ApprovalRequest(...))
        return JSONResponse({"error": {"code": -32001, "message": "approval_required"}})
    case "ALLOW":
        pass  # 既存の ToolProxy フローへ
```

### `app.py` の変更点

- `engine` を `build_router()` に渡す
- `LogOnlyApprovalNotifier()` をインスタンス化して `build_router()` に渡す

---

## 8. エラーコード定義

| コード | 意味 |
|--------|------|
| `-32601` | tool not found（既存。DENY 全般に使用） |
| `-32001` | approval_required（新規。REQUIRES_APPROVAL 時） |

---

## 9. テスト戦略

### 新規テストクラス（`tests/unit/test_mcp_gateway.py` に追加）

| クラス | 対象 |
|--------|------|
| `TestParamConstraint` | `max_length` / `pattern` / `allowed_values` / `forbidden` の各制約 |
| `TestEvaluateCall` | ALLOW / DENY / REQUIRES_APPROVAL の全分岐 |
| `TestApprovalNotifier` | `LogOnlyApprovalNotifier.request_approval()` の呼び出し |
| `TestServerRequiresApproval` | `/messages` エンドポイントの `-32001` レスポンス |

### devcontainer でのテスト実行

```bash
# コンテナ内で実行
pytest tests/unit/test_mcp_gateway.py -v

# 型チェック
uv run mypy src/mcp_gateway/

# リント
uv run ruff check src/mcp_gateway/
```

---

## 10. 変更ファイル一覧

| ファイル | 変更種別 |
|----------|----------|
| `src/mcp_gateway/policy/models.py` | 拡張（`ParamConstraint`, `ToolGuardrail`, `IntentPolicy.guardrails`） |
| `src/mcp_gateway/policy/engine.py` | 拡張（`CallDecision`, `evaluate_call()`） |
| `src/mcp_gateway/policies/intents.example.yaml` | 拡張（`guardrails` サンプル追加） |
| `src/mcp_gateway/approval/__init__.py` | 新規 |
| `src/mcp_gateway/approval/notifier.py` | 新規 |
| `src/mcp_gateway/server.py` | 改修（`evaluate_call()` 組み込み、シグネチャ追加） |
| `src/mcp_gateway/app.py` | 改修（`engine` / `approval_notifier` DI） |
| `tests/unit/test_mcp_gateway.py` | 拡張（新規テストクラス追加） |
