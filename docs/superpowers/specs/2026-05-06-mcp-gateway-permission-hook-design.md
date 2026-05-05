# MCP Gateway Permission Hook (Suspend/Resume Approval Flow) — 設計書

- 作成日: 2026-05-06
- 対象モジュール: `src/mcp_gateway/`
- 参照: LayerX `ccgate` (Server-defined Prompts / Permission Hook 概念)

## 1. 背景と目的

`chronos-graph` の MCP Gateway には、IBAC ポリシー (`intents.yaml`) と
`requires_approval: bool` フラグが既に実装されている。ただし `tools/call` が
`REQUIRES_APPROVAL` と判定された場合、現状の `server.py` は次の挙動を取る:

1. JSON-RPC エラー `-32001 approval_required` を即座に返却。
2. `_schedule_approval_request()` で `ApprovalNotifier` を fire-and-forget 呼び出し。
3. クライアントは別途リトライ/ポーリングする必要がある。

本設計では、ccgate の Permission Hook 概念に準拠し、
**「ツール呼び出しを一時停止し、ユーザの承認応答を待ってから再開/中断する」
suspend/resume 型の承認フロー**をオプトイン機能として追加する。
既存テスト互換性は config フラグで担保する。

## 2. スコープ

### In-Scope

- `PendingApprovalRegistry` (新規): `asyncio.Event` ベースの承認待ち管理。
- `POST /approvals/{approval_id}` (新規エンドポイント): UI/operator からの decision 受信。
- `server.py` の `tools/call` 処理拡張: blocking モード時に suspend/resume。
- `GatewaySettings` 拡張: `approval_blocking_mode` (default `False`)、
  `approval_timeout_seconds` (default `30`)。
- 単体テスト (TDD)。

### Out-of-Scope

- MCP プロトコル `elicitation/sampling` での UI 統合 (将来課題)。
- フロントエンド (Cytoscape ダッシュボード) からの承認 UI 実装。
- 永続化された承認キュー (Redis/DB バックエンド)。本設計はインメモリのみ。
- Slack/Webhook 等の通知実装本体。既存 `LogOnlyApprovalNotifier` を拡張可能ポイントとして温存。

## 3. アーキテクチャ

```
┌───────────────────────────────────────────────────────────────┐
│                     MCP Gateway Process                        │
│                                                                │
│  ┌────────────────┐   register   ┌──────────────────────────┐ │
│  │ /messages       │─────────────▶│ PendingApprovalRegistry  │ │
│  │ (tools/call)    │              │  - approval_id: Event    │ │
│  │                 │  await event │  - decision storage      │ │
│  │  [SUSPEND]◀─────┼──────────────┤                          │ │
│  └────────┬────────┘              └──────────────────────────┘ │
│           │ approve                          ▲                 │
│           ▼                                  │ resolve         │
│      ToolProxy / Upstream                    │                 │
│                                  ┌───────────┴───────────────┐ │
│                                  │ POST /approvals/{id}      │ │
│                                  │  decision: approve|reject │ │
│                                  └───────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ ApprovalNotifier (Hook → UI: log/Slack/Webhook/SSE)      │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

## 4. コンポーネント詳細

### 4.1 `src/mcp_gateway/approval/models.py` (新規)

```python
from enum import Enum
from dataclasses import dataclass

class DecisionStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT  = "timeout"

@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    status: DecisionStatus
    reason: str | None = None
```

`ApprovalRequest` 型は既存 `notifier.py` のものをそのまま再利用する
(後方互換のためモジュールから re-export してもよい)。

### 4.2 `src/mcp_gateway/approval/registry.py` (新規)

```python
class PendingApprovalRegistry:
    def __init__(self, *, max_pending: int = 1000) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._max_pending = max_pending
        # _Pending: { event: asyncio.Event, decision: ApprovalDecision|None,
        #             session_id: str, request: ApprovalRequest }

    async def register(self, *, session_id: str, request: ApprovalRequest) -> str:
        """approval_id (uuid hex) を発行し、Event を初期化して dict に登録する。
        - サイズ上限 (max_pending) 到達時は KeyError("approval_registry_full")。"""

    async def wait_for_decision(self, approval_id: str, *, timeout: float) -> ApprovalDecision:
        """asyncio.Event を timeout 付きで待機。
        - timeout 発火時: dict から削除し DecisionStatus.TIMEOUT を返す。
        - resolve 済み時 (Event 既セット含む): 保存した decision を返し、dict から削除。
        - 未登録 ID への呼び出しは KeyError (server.py 直後呼び出しでは発生し得ない)。"""

    async def resolve(
        self, approval_id: str, *, status: DecisionStatus, reason: str | None = None
    ) -> bool:
        """既に resolve 済みなら False、未登録なら False。
        成功時は decision をセットして Event.set()。エントリ自身は wait 側が削除。"""

    async def cancel_session(self, session_id: str) -> None:
        """指定 session_id に紐づく未解決の承認をすべて REJECTED で解決。"""
```

#### 不変条件

- 同一 `approval_id` への `resolve()` は idempotent (2回目は False)。
- `wait_for_decision()` は必ず `_pending` から自身のエントリを削除して返却する。
- `register()` の戻り `approval_id` は uuid4 hex で、衝突確率は無視可能とみなす。

### 4.3 `src/mcp_gateway/server.py` 拡張

#### 4.3.1 `build_router()` シグネチャ拡張

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
    approval_notifier: ApprovalNotifier | None = None,
    approval_registry: PendingApprovalRegistry | None = None,  # NEW
    approval_blocking_mode: bool = False,                       # NEW
    approval_timeout_seconds: float = 30.0,                      # NEW
) -> APIRouter:
```

- `approval_blocking_mode=False` (default): 既存挙動を維持 (`-32001` 即時返却)。
- `approval_blocking_mode=True`: 以下の suspend/resume フローを実行。

#### 4.3.2 REQUIRES_APPROVAL ハンドラ (blocking モード時)

```
1. registry.register(session_id, ApprovalRequest) → approval_id
2. _schedule_approval_request(notifier, request)  # 既存通り fire-and-forget
3. audit.log(ev="call", decision="approval_pending",
             agent=..., sid=..., tool=..., approval_id=approval_id)
4. decision = await registry.wait_for_decision(approval_id, timeout=approval_timeout_seconds)

5. match decision.status:
   case APPROVED:
       # 既存 ALLOW パスと同じ処理
       payload = await proxy._call_server_trusted(tool_name, arguments)
       audit.log(ev="call", decision="allow_after_approval", ..., approval_id=...)
       return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}
   case REJECTED:
       audit.log(ev="call", decision="approval_rejected", ..., approval_id=...,
                 reason=decision.reason)
       return JSON-RPC error -32002 "approval_rejected"
   case TIMEOUT:
       audit.log(ev="call", decision="approval_timeout", ..., approval_id=...)
       return JSON-RPC error -32003 "approval_timeout"
```

#### 4.3.3 新エンドポイント `POST /approvals/{approval_id}`

- 認証: 既存の Bearer API key (Authorization ヘッダ) を流用。`HandshakeService`
  ではなく `ApiKeyAuthenticator` を直接呼んで agent_id 解決のみ行う
  (intent ヘッダ等は不要)。認証失敗時は 401。
- リクエストボディ:
  ```json
  {
    "decision": "approve",          // | "reject"
    "reason": "explanation (optional)"
  }
  ```
- 処理:
  1. body をパースし、`decision in {"approve","reject"}` を検証 (それ以外は 400)。
  2. `registry.resolve(approval_id, status=APPROVED|REJECTED, reason=...)` を呼ぶ。
  3. 戻り値が `False` なら 404 (`approval_not_found_or_already_resolved`)。
  4. 成功時 200 `{"status": "resolved", "approval_id": "..."}`。
- audit log: `ev="approval_decision", decision=..., agent=..., approval_id=..., reason=...`。
- セキュリティ: body はサイズ制限 (例: 1KB) を `Request.body()` の長さチェックで設ける。

### 4.4 `src/mcp_gateway/config.py`

```python
class GatewaySettings(BaseSettings):
    ...
    approval_blocking_mode: bool = False
    approval_timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
```

### 4.5 `src/mcp_gateway/app.py`

- `PendingApprovalRegistry` をライフサイクルでシングルトン生成。
- `build_router()` に `approval_registry`、`approval_blocking_mode`、
  `approval_timeout_seconds` を渡す。
- 既存の `LogOnlyApprovalNotifier` 注入箇所はそのまま維持。

## 5. データフロー (REQUIRES_APPROVAL → APPROVED 例)

```
client (LLM)         gateway                      registry        notifier   operator UI
   │                    │                            │                │           │
   │── tools/call ─────▶│                            │                │           │
   │                    │── evaluate_call ──┐        │                │           │
   │                    │◀── REQUIRES_APPROVAL       │                │           │
   │                    │── register ───────────────▶│                │           │
   │                    │◀── approval_id ────────────│                │           │
   │                    │── notify (fire-and-forget) ─────────────────▶│          │
   │                    │                            │                │── show──▶│
   │                    │── await wait_for_decision ▶│                │           │
   │                    │     (suspended)            │                │           │
   │                    │                            │                │  ◀───approve
   │                    │                            │                            │
   │                    │                            │◀── POST /approvals/{id}────│
   │                    │                            │── set Event                │
   │                    │◀── ApprovalDecision(APPROVED)                            │
   │                    │── proxy.call_through ─────▶ upstream                    │
   │◀── result ─────────│                                                          │
```

## 6. JSON-RPC エラーコード

| コード   | 意味                  | 既存/新規 |
|----------|-----------------------|-----------|
| -32001   | `approval_required`   | 既存 (immediate モード) |
| -32002   | `approval_rejected`   | **新規** |
| -32003   | `approval_timeout`    | **新規** |

## 7. テスト戦略 (TDD)

### 7.1 `TestPendingApprovalRegistry` (registry 単体)

| テスト名                                              | 期待 |
|-------------------------------------------------------|------|
| `test_register_returns_unique_approval_id`            | 連続登録で uuid hex がユニーク |
| `test_wait_for_decision_returns_approved_when_resolved` | resolve(APPROVED) 後の wait は APPROVED を返す |
| `test_wait_for_decision_returns_rejected_when_resolved` | 同上 (REJECTED) |
| `test_wait_for_decision_times_out`                    | timeout 経過で TIMEOUT |
| `test_resolve_unknown_id_returns_false`               | 未登録 ID は idempotent に False |
| `test_resolve_already_resolved_returns_false`         | 2 回目の resolve は False |
| `test_concurrent_resolve_is_safe`                     | 同時 resolve でも 1 つだけ True |
| `test_cancel_session_rejects_pending`                 | session_id 単位で REJECTED 解決 |

### 7.2 `TestServerApprovalSuspend` (httpx ASGITransport, blocking モード)

| テスト名                                                | 期待 |
|---------------------------------------------------------|------|
| `test_blocking_mode_suspends_until_approve`             | approve 後 result が返る |
| `test_blocking_mode_returns_32002_on_reject`            | -32002 + reason |
| `test_blocking_mode_returns_32003_on_timeout`           | timeout 後 -32003 |
| `test_approval_callback_404_for_unknown_id`             | 未登録 ID で 404 |
| `test_approval_callback_404_for_already_resolved`       | 2回目の resolve は 404 (404 に統合) |
| `test_approval_callback_400_for_invalid_decision`       | decision が approve/reject 以外なら 400 |
| `test_approval_callback_401_without_auth`               | Authorization ヘッダ欠落で 401 |
| `test_blocking_mode_audit_logs_pending_and_resolution`  | pending/resolved/rejected/timeout の audit log が出力される |
| `test_blocking_mode_does_not_call_upstream_on_reject`   | upstream モックが呼ばれない |

### 7.3 既存テストの扱い

- `TestServerRequiresApproval` (immediate モード) は `approval_blocking_mode=False`
  下のテストとして維持し、既存の挙動契約を保証する。
- 新規 fixture `approval_app_blocking` を追加し、blocking モード ON で別 app を組む。

## 8. セキュリティ考慮

- **承認エンドポイントの認可**: 現バージョンでは Bearer API key (任意の登録 agent)
  で承認可能とする。将来的には operator 専用 key スコープを追加する余地を残す。
  本仕様では `approval_id` 自体が unguessable な uuid4 hex (128bit)
  であることをもって "authenticated callback" を成立させる。
- **シークレット混入**: 既存 `_contains_secret(arguments)` チェックは
  `evaluate_call` 後に既に行われているため、approval_id に紐付く request 内に
  原始的な secret が混入することはない。`_sanitize_for_log` で notifier 引数も既にマスク済。
- **DoS 対策**: `PendingApprovalRegistry` の最大エントリ数を `max_pending`
  (default 1000) で上限制御。`register()` 時に上限到達なら
  `PolicyError("approval_registry_full")` を送出し、`tools/call` は
  JSON-RPC `-32603 internal_error` を返す。timeout (default 30s) による
  自然回収を併用。
- **request body サイズ**: `POST /approvals/{id}` は 1KB 上限。

## 9. 後方互換性

- `approval_blocking_mode` のデフォルトは `False`。
- 既存の `TestServerRequiresApproval` テスト群は無修正で通る。
- 新規挙動は `MCP_GATEWAY_APPROVAL_BLOCKING_MODE=true` 環境変数または
  `GatewaySettings(approval_blocking_mode=True)` でオプトイン。

## 10. 受け入れ条件

1. `uv run pytest tests/unit/test_mcp_gateway.py -v` が devcontainer 内で全て成功する。
2. `uv run mypy src/` がエラーなしで通る。
3. `uv run ruff check src/ tests/` がエラーなしで通る。
4. `intents.example.yaml` の `requires_approval: true` を持つツール
   (`memory_delete` 等) を blocking モードで呼び出した際、
   `POST /approvals/{id}` で `approve` するとアップストリームが呼ばれ、
   `reject` すると `-32002` が返ることが新規テストで検証される。

## 11. 既知の限界 / 将来課題

- インメモリ実装のためマルチプロセス展開 (gunicorn workers) では承認状態が共有されない。
  将来 Redis Pub/Sub 等への置換を想定する。
- ccgate の "Server-defined Prompts" 相当の MCP elicitation 連携は本仕様では扱わない。
- 承認エンドポイントの operator 認可ロールは将来課題。
