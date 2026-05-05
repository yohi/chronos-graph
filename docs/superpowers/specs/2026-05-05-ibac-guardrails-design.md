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

```text
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
- **ReDoS 対策の検証**（詳細はセクション 4 参照）:
    - `pattern` 文字列が規定値（200字）を超えていないか
    - `pattern` が指定されている場合に `max_length` が設定されているか
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
4. パラメータ制約評価（`forbidden` → **型チェック** → `max_length` → `pattern` → `allowed_values`）
5. `requires_approval: true` → `REQUIRES_APPROVAL`
6. 全通過 → `ALLOW`

**型チェックの仕様：**  
`constraint.type` が設定されている場合、または文字列固有の制約（`max_length` / `pattern`）が設定されている場合、値の Python 型が期待される型と一致しない場合は即座に `DENY`（reason: `param_type_mismatch:<param_name>`）とする。型チェックに失敗した場合、後続の `max_length` / `pattern` 評価は行わない。

| `constraint.type` | 期待される Python 型 |
|-------------------|---------------------|
| `"string"` | `str` |
| `"integer"` | `int`（`bool` は除く） |
| `"number"` | `int` または `float`（`bool` は除く） |
| `"boolean"` | `bool` |
| `None` かつ `max_length` または `pattern` あり | `str` |
| `None` かつ文字列固有制約なし | 型チェックなし |

**`re.fullmatch`** を使用するため `pattern` は部分一致ではなく完全マッチ。

### ReDoS 対策

ユーザー定義の `pattern` を外部入力文字列に対して評価する際、正規表現の壊滅的バックトラッキング（ReDoS）リスクが存在する。以下の2つの制御を実装に含めること。

| 対策 | 実施タイミング | 具体的な内容 |
|------|---------------|-------------|
| **パターン文字列長制限** | ポリシーロード時（`_verify_references`） | `ParamConstraint.pattern` の文字数が 200 字を超える場合は `PolicyError` として起動を拒否 |
| **評価対象の長さ先行保証** | `evaluate_call()` 内の評価順序の強制 | `pattern` チェックは必ず `max_length` チェックの**後**に実行する。`max_length` が未設定かつ `pattern` が存在する場合は `PolicyError` をロード時に発生させ、起動を拒否する |

これにより、regex エンジンに渡される文字列長は `max_length` で事前に上限が保証される。

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

```text
src/mcp_gateway/approval/
    __init__.py
    notifier.py
```

### `ApprovalRequest` データモデル

```python
@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    session_id: str          # セッション識別子（SessionRecord.session_id）
    agent_id: str            # エージェント識別子（SessionRecord.agent_id）
    intent: str              # セッションに紐づくインテント名（SessionRecord.intent）
    tool_name: str           # 承認が必要なツール名
    arguments: dict[str, Any]  # ツールに渡された引数（そのまま転送）
    requested_at: datetime   # 承認要求日時（UTC）
```

全フィールドは必須。`arguments` はシークレットスキャン済みの値のみ含む（通知直前に `ToolProxy._contains_secret()` 相当のロジックで検査し、シークレットが含まれる場合は通知せずに `DENY` とする）。

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
        # 通知前にシークレットが含まれていないか再検証（漏洩防止）
        if any(ToolProxy._contains_secret(v) for v in arguments.values()):
            audit.log(ev="call", decision="deny", reason="secret_in_approval_args", ...)
            return JSONResponse({"error": {"code": -32601, "message": "tool not found"}})

        audit.log(ev="call", decision="requires_approval", ...)
        await approval_notifier.request_approval(ApprovalRequest(...))
        return JSONResponse({
            "error": {
                "code": -32001,
                "message": "approval_required",
                "data": {"session_id": record.session_id}  # 相関用 ID
            }
        })
    case "ALLOW":
        pass  # 既存の ToolProxy フローへ
```

### `app.py` の変更点

- `engine` を `build_router()` に渡す
- `LogOnlyApprovalNotifier()` をインスタンス化して `build_router()` に渡す

---

## 8. エラーコード定義

| コード | 意味 | 備考 |
|--------|------|------|
| `-32601` | tool not found | DENY 全般、または承認対象引数にシークレットが含まれる場合 |
| `-32001` | approval_required | 承認待ち。`data.session_id` を含める |

---

## 9. テスト戦略

### 新規テストクラス（`tests/unit/test_mcp_gateway.py` に追加）

| クラス | 対象 |
|--------|------|
| `TestParamConstraint` | `max_length` / `pattern` / `allowed_values` / `forbidden` の各制約 |
| `TestEvaluateCall` | ALLOW / DENY / REQUIRES_APPROVAL の全分岐 |
| `TestApprovalNotifier` | `LogOnlyApprovalNotifier.request_approval()` の呼び出し |
| `TestServerRequiresApproval` | `/messages` エンドポイントの `-32001` レスポンス |

### エッジケーステスト入力値と期待出力

#### `TestParamConstraint` — 制約別エッジケース

| テストケース | 入力値 | 制約設定 | 期待ステータス | 期待 reason |
|-------------|--------|---------|--------------|------------|
| max_length: 境界値（ちょうど上限） | `"a" * 512` | `max_length=512` | `ALLOW` | — |
| max_length: 上限超過 | `"a" * 513` | `max_length=512` | `DENY` | `param_too_long:query` |
| max_length: 空文字列 | `""` | `max_length=512` | `ALLOW` | — |
| pattern: 完全マッチ | `"hello_world"` | `pattern="^[a-z_]+$"` | `ALLOW` | — |
| pattern: 部分的に一致する文字列（fullmatch のため拒否） | `"hello world!"` | `pattern="^[a-z_]+$"` | `DENY` | `param_pattern_mismatch:query` |
| pattern: 特殊文字（`<script>`） | `"<script>alert(1)</script>"` | `pattern="^[^<>{};]*$"` | `DENY` | `param_pattern_mismatch:query` |
| pattern: Unicode 文字 | `"こんにちは"` | `pattern="^[a-z_]+$"` | `DENY` | `param_pattern_mismatch:query` |
| allowed_values: リスト内の値 | `"read"` | `allowed_values=["read","write"]` | `ALLOW` | — |
| allowed_values: リスト外の値 | `"admin"` | `allowed_values=["read","write"]` | `DENY` | `param_not_in_allowed_values:mode` |
| forbidden: パラメータが存在する | `{"secret": "x"}` | `forbidden=True` on `secret` | `DENY` | `forbidden_param:secret` |
| forbidden: パラメータが存在しない | `{"query": "hi"}` | `forbidden=True` on `secret` | `ALLOW` | — |
| パラメータ自体が欠落（制約あり） | `{}` | `max_length=512` on `query` | `ALLOW` | — （欠落は無視）|
| パラメータ型が不正（int を文字列制約に渡す） | `{"query": 12345}` | `max_length=512, pattern="^[a-z]+$"` | `DENY` | `param_type_mismatch:query` |
| パラメータ型が不正（int を `type: string` 制約に渡す） | `{"query": 12345}` | `type="string"` のみ | `DENY` | `param_type_mismatch:query` |
| bool を `type: integer` に渡す（bool は int のサブクラスだが除外） | `{"count": True}` | `type="integer"` | `DENY` | `param_type_mismatch:count` |
| 正しい型（str を `type: string` に渡す） | `{"query": "safe"}` | `type="string"` | `ALLOW` | — |

#### `TestEvaluateCall` — 分岐全網羅

| テストケース | 入力 | 期待 `CallDecision.status` |
|-------------|------|--------------------------|
| caps になしツール | `tool_name="memory_delete"`, caps=`{"memory_search"}` | `DENY` |
| 不明な intent | `intent="ghost_intent"` | `DENY` |
| ガードレール未定義ツール | guardrails なし | `ALLOW` |
| 全制約通過 | `query="safe query"`, max_length=512, pattern=`^[^<>]*$` | `ALLOW` |
| requires_approval のみ（params 空） | `requires_approval=True` | `REQUIRES_APPROVAL` |
| パラメータ違反 + requires_approval=True | `query="a"*600`, max_length=512 | `DENY` （パラメータ違反が優先）|

#### `TestServerRequiresApproval` — エンドポイントレスポンス

| テストケース | 操作 | 期待レスポンス |
|-------------|------|--------------|
| 承認必須ツール呼び出し | `tools/call` で `memory_delete` | `{"error": {"code": -32001, "message": "approval_required"}}` |
| 承認必須ツール呼び出し時の監査ログ | 同上 | stderr に `decision=requires_approval` を含む JSON Lines |
| 通常拒否ツール（caps 外） | `tools/call` で `admin_tool` | `{"error": {"code": -32601, "message": "tool not found"}}` |

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
