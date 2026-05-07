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
- `POST /approvals` (新規エンドポイント): UI/operator からの decision 受信。
- `server.py` の `tools/call` 処理拡張: blocking モード時に suspend/resume。
- `GatewaySettings` 拡張: `approval_blocking_mode` (default `False`)、
  `approval_timeout_seconds` (default `30`)、`approval_max_pending` (default `1000`)。
- `InMemorySessionRegistry` の eviction hook 追加 (`on_session_evicted`)。
  hook 起動時の例外は必ず audit log + `logger.error` で観測可能とする。
- 単体テスト (TDD)。

### Out-of-Scope

- MCP プロトコル `elicitation/sampling` での UI 統合 (将来課題)。
- フロントエンド (Cytoscape ダッシュボード) からの承認 UI 実装。
- 永続化された承認キュー (Redis/DB バックエンド)。本設計はインメモリのみ。
- Slack/Webhook 等の通知実装本体。既存 `LogOnlyApprovalNotifier` を拡張可能ポイントとして温存。

## 3. アーキテクチャ

```text
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
│                                  │ POST /approvals      │ │
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
class ResolveOutcome(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"          # 未登録 or 既に resolve 済みで wait 側削除済
    ALREADY_RESOLVED = "already_resolved"
    FORBIDDEN = "forbidden"          # resolver agent_id が許可主体と不一致

class PendingApprovalRegistry:
    def __init__(self, *, max_pending: int = 1000) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, _Pending] = {}
        self._max_pending = max_pending
        # _Pending: { event: asyncio.Event, decision: ApprovalDecision|None,
        #             session_id: str, requester_agent_id: str,
        #             request: ApprovalRequest }

    async def register(
        self, *, session_id: str, requester_agent_id: str, request: ApprovalRequest
    ) -> str:
        """approval_id (uuid hex) を発行し、Event を初期化して dict に登録する。
        - サイズ上限 (max_pending) 到達時は PolicyError("approval_registry_full") を送出。
          server.py 側で捕捉し JSON-RPC -32603 internal_error に変換する。"""

    async def wait_for_decision(self, approval_id: str, *, timeout: float) -> ApprovalDecision:
        """asyncio.Event を timeout 付きで待機。
        - timeout 発火時: dict から削除し DecisionStatus.TIMEOUT を返す。
        - resolve 済み時 (Event 既セット含む): 保存した decision を返し、dict から削除。
        - 未登録 ID への呼び出しは KeyError(approval_id) を送出 (プログラミングエラー扱い)。"""

    async def resolve(
        self,
        approval_id: str,
        *,
        resolver_agent_id: str,
        status: DecisionStatus,
        reason: str | None = None,
    ) -> ResolveOutcome:
        """resolver_agent_id を必須引数化し、許可主体検証を内蔵する。
        - 未登録: NOT_FOUND
        - 既に resolve 済み (decision 設定済): ALREADY_RESOLVED
        - resolver_agent_id == requester_agent_id (自己承認): FORBIDDEN
        - 上記以外で成功: OK (decision をセットして Event.set())
        エントリの削除は wait_for_decision() 側で行う。"""

    async def cancel_session(self, session_id: str) -> None:
        """指定 session_id に紐づく未解決の承認をすべて REJECTED で解決。
        呼び出し契機は §4.5 の SessionRegistry expiry hook 参照。"""
```

#### 不変条件

- 同一 `approval_id` への `resolve()` 成功は 1 回のみ (2 回目以降は ALREADY_RESOLVED)。
- `wait_for_decision()` は必ず `_pending` から自身のエントリを削除して返却する。
- `register()` の戻り `approval_id` は uuid4 hex で、衝突確率は無視可能とみなす。
- 自己承認 (resolver == requester) は常に FORBIDDEN (audit log 漏洩経由の自己昇格防御)。

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

##### 前提条件 (precondition)

`build_router()` 関数冒頭で以下の検証を行い、不正組み合わせを起動時に検出する:

```python
if approval_blocking_mode and approval_registry is None:
    raise ValueError(
        "approval_registry must be provided when approval_blocking_mode=True"
    )
```

これにより `app.py` でのワイヤリングミスが実行時 `AttributeError` ではなく
**起動時 ValueError** として検出され、Fail-fast 原則を維持する。

#### 4.3.2 REQUIRES_APPROVAL ハンドラ (blocking モード時)

```text
1. try:
       approval_id = await registry.register(
           session_id=record.session_id,
           requester_agent_id=record.agent_id,
           request=ApprovalRequest(...),
       )
   except PolicyError as exc:
       # max_pending overflow
       audit.log(ev="call", decision="deny", reason="approval_registry_full", ...)
       return JSON-RPC error -32603 "internal_error"

2. _schedule_approval_request(notifier, request)  # 既存通り fire-and-forget
3. approval_id_log = _approval_id_for_log(approval_id)  # 先頭 8 文字 + "..."
   audit.log(ev="call", decision="approval_pending",
             agent=..., sid=..., tool=..., approval_ref=approval_id_log)
4. decision = await registry.wait_for_decision(approval_id, timeout=approval_timeout_seconds)

5. match decision.status:
   case APPROVED:
       # 既存 ALLOW パスと同じ処理
       payload = await proxy._call_server_trusted(tool_name, arguments)
       audit.log(ev="call", decision="allow_after_approval",
                 ..., approval_ref=approval_id_log)
       return {"jsonrpc": "2.0", "id": rpc_id, "result": payload}
   case REJECTED:
       audit.log(ev="call", decision="approval_rejected",
                 ..., approval_ref=approval_id_log, reason=decision.reason)
       return JSON-RPC error -32002 "approval_rejected"
   case TIMEOUT:
       audit.log(ev="call", decision="approval_timeout",
                 ..., approval_ref=approval_id_log)
       return JSON-RPC error -32003 "approval_timeout"
```

##### audit log での approval_id 取り扱い

`_approval_id_for_log(approval_id: str) -> str` ヘルパを `server.py` に追加し、
audit log には常に `approval_id[:8] + "..."` (先頭 8 文字 + 省略記号、機械可読
ではあるが原 ID 推測不可) を `approval_ref` フィールドで出力する。
原 `approval_id` (32 文字 uuid hex) は **process メモリ内でのみ保持** し、
log/stderr/stdout に出力しない。これにより監査ログ漏洩経由での承認エンドポイント
不正利用を防ぐ (詳細は §8 を参照)。

#### 4.3.3 新エンドポイント `POST /approvals`

- **設計上の決定**: 原 `approval_id` がリバースプロキシや ASGI サーバーのアクセスログに露出するのを防ぐため、パスパラメータではなくリクエストボディで ID を受け取る設計とする。これにより、アクセスログのパス・マスキング設定に依存せず ID の秘匿性を担保する。
- **認証**: 既存の Bearer API key (Authorization ヘッダ) を流用。`HandshakeService`
  ではなく `ApiKeyAuthenticator` を直接呼んで `resolver_agent_id` を解決
  (intent ヘッダ等は不要)。認証失敗時は 401。
- **認可 (許可主体検証)**: `registry.resolve()` 内で `resolver_agent_id` と
  `requester_agent_id` を比較し、**自己承認 (一致)** を `FORBIDDEN` として拒否。
  `tools/call` を出した agent がそのまま自分の approval を承認することを禁ずる。
  これにより監査ログから推測された approval_id が万が一漏洩しても、
  自己昇格 (self-approval) は成立しない。
- リクエストボディ:

  ```json
  {
    "approval_id": "32-char-uuid-hex",
    "decision": "approve",
    "reason": "explanation (optional)"
  }
  ```

  `decision` は `"approve" | "reject"` のいずれか。
- **処理フロー**:
  1. `Authorization` ヘッダを `ApiKeyAuthenticator` で検証 → `resolver_agent_id` を取得。
     失敗時 401 `{"error": "auth_failed"}`。
  2. `Request.body()` で生のバイト列を取得し、サイズを検証する。1KB を超過している場合は即座に 413 `{"error": "payload_too_large"}` を返す。サイズが許容範囲内であれば JSON パースを試みる。
  3. `body` 内の `approval_id` (必須) および `decision in {"approve","reject"}` を検証。不備がある場合は 400 `{"error": "invalid_request"}` 等を返す。
  4. **サニタイズ**: `normalized_reason = sanitize_reason(body.get("reason"))` を取得。これは §8.6 の正規化・切り詰めルールを確実に適用するため、ロジックの最前段で行う。
  5. `outcome = await registry.resolve(approval_id, resolver_agent_id=..., status=..., reason=normalized_reason)` を呼ぶ。
  6. `outcome` に応じて HTTP 応答を返す:

     | outcome             | HTTP | body                                              |
     |---------------------|------|---------------------------------------------------|
     | `OK`                | 200  | `{"status": "resolved", "approval_id": "..."}`    |
     | `NOT_FOUND`         | 404  | `{"error": "approval_not_found"}`                 |
     | `ALREADY_RESOLVED`  | 404  | `{"error": "approval_not_found"}` (NOT_FOUND と統合) |
     | `FORBIDDEN`         | 403  | `{"error": "self_approval_forbidden"}`            |

     `ALREADY_RESOLVED` と `NOT_FOUND` を 404 に統合する理由は
     存在判定オラクルを与えないため。
- **audit log**: `ev="approval_decision", outcome=..., resolver=resolver_agent_id,
  approval_ref=approval_id[:8]+"...", reason=normalized_reason` を記録。
  原 approval_id は出力しない。

### 4.4 `src/mcp_gateway/config.py`

```python
class GatewaySettings(BaseSettings):
    ...
    approval_blocking_mode: bool = False
    approval_timeout_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    approval_max_pending: int = Field(default=1000, gt=0, le=100_000)
```

環境変数:

- `MCP_GATEWAY_APPROVAL_BLOCKING_MODE=true|false`
- `MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS=30`
- `MCP_GATEWAY_APPROVAL_MAX_PENDING=1000`

### 4.5 `src/mcp_gateway/app.py`

- `PendingApprovalRegistry` をライフサイクル (FastAPI `lifespan`) で
  シングルトン生成し、`app.state.approval_registry` に格納。
- `build_router()` に `approval_registry`、`approval_blocking_mode`、
  `approval_timeout_seconds` を渡す。
- 既存の `LogOnlyApprovalNotifier` 注入箇所はそのまま維持。

#### Session lifecycle hook の配線

`InMemorySessionRegistry` を拡張し、コンストラクタで
`on_session_evicted: Callable[[str], Awaitable[None]] | None = None`
を受け取れるようにする。`lookup()` (TTL/idle expiry 検出時)、`remove()`、
`purge()` で session が辞書から削除されるパスにおいて、callback が設定済なら
**例外回収可能な形で** 非同期発火する (詳細は次節)。

`app.py` では以下の通り配線する:

具体的な配線コードは次節 (§4.5 Eviction callback の例外監視) を参照

これにより、クライアント切断 (idle timeout)・TTL expiry・明示的 `remove`
すべての session 終了経路で、当該 session に紐づく未解決 approval が
`REJECTED` で解決され、`_pending` が直ちに回収される。**§8 の `max_pending` 上限
保護はこの hook を前提として成立する。**

#### Eviction callback の例外監視 (要件)

`asyncio.create_task()` で起動した eviction task の例外は、デフォルトでは
task が GC されるまで補足されず stderr の `Task exception was never retrieved`
警告として流れるのみとなる。本設計の hook は `max_pending` 解放という
**DoS 防御のクリティカルパス** を担うため、cleanup 失敗が silent になることは
許容できない。したがって責務は以下の通り 2 層に分離して満たすこと:

**`InMemorySessionRegistry` 側 (hook 起動層)** — 不変条件:

1. `asyncio.create_task(on_session_evicted(sid), name=f"session_evict_{sid[:8]}")`
   で生成し、識別可能な name を付与する。
2. 直ちに `task.add_done_callback(_log_evict_exception)` を呼んで
   done callback を登録する。
3. `_log_evict_exception(task)` 内で `task.exception()` を取得し、`None`
   でなければ `logger.error("session_eviction_callback_failed", ..., exc_info=True)`
   でモジュールロガーに記録する。`AuditLogger` は **呼ばない**。

`InMemorySessionRegistry` は `AuditLogger` を直接依存しない。
これにより低レベルの registry コンポーネントと高レベルの監査機構を疎結合に保つ。

**`app.py` 側 (on_session_evicted ラッパー層)** — 不変条件:

`app.py` は `on_session_evicted` を `approval_registry.cancel_session` で直接配線
するのではなく、以下のようなラッパー coroutine を介して配線する:

```python
async def _on_session_evicted(sid: str) -> None:
    try:
        await approval_registry.cancel_session(sid)
    except Exception as exc:
        audit.log(
            ev="session_evict_failed",
            error_type=exc.__class__.__name__,
            sid=sid,
        )
        raise

sessions = InMemorySessionRegistry(
    ttl_seconds=settings.session_ttl_seconds,
    idle_timeout_seconds=settings.session_idle_timeout_seconds,
    on_session_evicted=_on_session_evicted,
)
```

ラッパーは例外を再 `raise` してタスクに伝播させることで、
`InMemorySessionRegistry` 側の `_log_evict_exception` による
`logger.error` も確実に発火する。

これにより hook 失敗 (例: `cancel_session` 実装変更で `RuntimeError`) は
`logger.error` (registry 層) と `AuditLogger.log` (app 層) の両方で観測可能となり、
回帰テスト (§7.4 `test_eviction_callback_logs_exception_when_callback_raises`)
で不変条件を保証する。

## 5. データフロー (REQUIRES_APPROVAL → APPROVED 例)

```text
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
   │                    │                            │◀── POST /approvals────│
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

| テスト名                                                  | 期待 |
|-----------------------------------------------------------|------|
| `test_register_returns_unique_approval_id`                | 連続登録で uuid hex がユニーク |
| `test_register_raises_policy_error_on_overflow`           | `max_pending` 超過で `PolicyError("approval_registry_full")` |
| `test_wait_for_decision_returns_approved_when_resolved`   | resolve(APPROVED) 後の wait は APPROVED を返す |
| `test_wait_for_decision_returns_rejected_when_resolved`   | 同上 (REJECTED) |
| `test_wait_for_decision_times_out`                        | timeout 経過で TIMEOUT |
| `test_wait_for_decision_unknown_id_raises_keyerror`       | 未登録 ID で KeyError |
| `test_resolve_unknown_id_returns_not_found`               | 未登録 ID は `ResolveOutcome.NOT_FOUND` |
| `test_resolve_already_resolved_returns_already_resolved`  | 2 回目は `ALREADY_RESOLVED` |
| `test_resolve_self_approval_returns_forbidden`            | resolver == requester で `FORBIDDEN`、Event 未セット |
| `test_concurrent_resolve_is_safe`                         | 同時 resolve で OK は 1 つのみ |
| `test_cancel_session_rejects_pending`                     | session_id 単位で REJECTED 解決 |
| `test_cancel_session_is_idempotent_for_unknown_sid`       | 未登録 session_id でも例外なし |

### 7.2 `TestServerApprovalSuspend` (httpx ASGITransport, blocking モード)

| テスト名                                                | 期待 |
|---------------------------------------------------------|------|
| `test_blocking_mode_suspends_until_approve`             | approve 後 result が返る |
| `test_blocking_mode_returns_32002_on_reject`            | -32002 + reason |
| `test_blocking_mode_returns_32003_on_timeout`           | timeout 後 -32003 |
| `test_blocking_mode_returns_32603_when_registry_full`   | `max_pending=1` で 2 件目は -32603 |
| `test_blocking_mode_session_eviction_cancels_pending`   | session expiry で pending が REJECTED 解決される |
| `test_approval_callback_404_for_unknown_id`             | 未登録 ID で 404 |
| `test_approval_callback_404_for_already_resolved`       | 2回目の resolve は 404 (404 に統合) |
| `test_approval_callback_403_for_self_approval`          | resolver == requester で 403 `self_approval_forbidden` |
| `test_approval_callback_400_for_invalid_decision`       | decision が approve/reject 以外なら 400 |
| `test_approval_callback_413_for_oversized_body`         | body が 1KB 超で 413 |
| `test_approval_callback_401_without_auth`               | Authorization ヘッダ欠落で 401 |
| `test_blocking_mode_audit_logs_truncate_approval_id`    | audit log には `approval_ref` のみ出力され、原 ID は出ない |
| `test_blocking_mode_does_not_call_upstream_on_reject`   | upstream モックが呼ばれない |
| `test_build_router_raises_when_blocking_without_registry` | `approval_blocking_mode=True` かつ `approval_registry=None` で `ValueError` |

### 7.3 既存テストの扱い

- `TestServerRequiresApproval` (immediate モード) は `approval_blocking_mode=False`
  下のテストとして維持し、既存の挙動契約を保証する。
- 新規 fixture `approval_app_blocking` を追加し、blocking モード ON で別 app を組む。

### 7.4 `TestSessionEvictionHook` (`InMemorySessionRegistry` の eviction hook)

| テスト名                                                              | 期待 |
|-----------------------------------------------------------------------|------|
| `test_eviction_callback_invoked_on_idle_expiry`                       | idle timeout 経過後 lookup() で hook が起動する |
| `test_eviction_callback_invoked_on_ttl_expiry`                        | TTL 経過後 lookup() で hook が起動する |
| `test_eviction_callback_invoked_on_remove`                            | 明示的 remove() で hook が起動する |
| `test_eviction_callback_invoked_on_purge`                             | purge() で全 expired session の hook が起動する |
| `test_eviction_callback_logs_exception_when_callback_raises`          | hook 内例外が `session_evict_failed` audit + `logger.error` で観測可能 |
| `test_eviction_callback_does_not_block_caller`                        | hook の awaitable は同期パスをブロックしない (即時 return) |

## 8. セキュリティ考慮

### 8.1 承認エンドポイントの認可モデル (defense-in-depth)

承認の安全性は以下 **3 段階** で担保する。いずれか単独に依存しない:

1. **Bearer API key 認証** (Authorization ヘッダ): `ApiKeyAuthenticator` で
   `resolver_agent_id` を解決。失敗時 401。
2. **`approval_id` 知識** (uuid4 hex 128bit): URL path から取得した値が
   registry に存在しない/既解決なら 404。総当たり耐性は uuid4 のエントロピーで担保。
3. **許可主体検証 (自己承認禁止)**: `registry.resolve()` 内で
   `resolver_agent_id == requester_agent_id` の場合 `FORBIDDEN` (HTTP 403)。
   これにより万が一 audit log 経由で `approval_id` が要求元 agent に
   漏洩しても、自己昇格 (self-approval) は成立しない。

将来課題として「operator 専用 agent role / API key スコープ」(任意の許可主体集合を
policy で明示) を残すが、本仕様の範囲では「**要求元 agent ≠ resolver agent**」
の単純規則で扱う。これは複数 agent (例: AI agent と UI operator) を別 API key で
登録する運用前提で十分機能する。

#### 既知の限界 (lateral approval)

本モデルは **要求元と異なる任意の登録 agent による承認 ("lateral approval")**
を防がない。具体的には次の脅威モデルに対しては脆弱:

- 複数の AI agent (例: agent_A, agent_B) が登録されており、両者の API key が
  独立した管理者の手元にある場合、agent_B の鍵保持者は (audit log 経由で
  `approval_id` の漏洩を得れば) agent_A 由来の `tools/call` を承認できる。

ChronosGraph の主要ユースケース (個人セルフホスト、全鍵を単一ユーザが保有)
ではこの脅威は受容範囲内とみなすが、**多者運用を行う場合は本仕様のままでは
不十分** であり、§11 の「`permitted_approvers: [agent_id, ...]` の policy DSL
拡張」を実装する必要がある。本 Spec はこの不完全性を明示的に文書化することで
運用者の判断材料とする。

### 8.2 監査ログ経由の自己昇格対策

audit log には原 `approval_id` (32 文字) を **絶対に出力しない**。
代わりに `approval_ref = approval_id[:8] + "..."` (先頭 8 文字 + 省略記号) を
全ての関連 audit ログ (`approval_pending` / `allow_after_approval` /
`approval_rejected` / `approval_timeout` / `approval_decision`) に記録する。

8 文字 (32bit 相当) は人間が pending な承認をログ上で識別する用途には十分で、
かつ残り 24 文字 (96bit) のエントロピーが ID 推測に対して残るため、
log 漏洩経由での総当たり攻撃は実質困難 (`2^96` 試行が必要)。
仮にログから推測 ID を完全に復元されても、§8.1 の自己承認禁止により
要求元 agent では承認できない。

### 8.3 シークレット混入

既存の `_contains_secret(arguments)` チェックは `evaluate_call` 後に
既に行われているため、`approval_id` に紐付く request 内に原始的な secret が
混入することはない。`_sanitize_for_log` で notifier 引数も既にマスク済。

### 8.4 DoS 対策

- `PendingApprovalRegistry` の最大エントリ数を `max_pending` (default 1000)
  で上限制御。`register()` 時に上限到達なら `PolicyError("approval_registry_full")`
  を送出し、`tools/call` は JSON-RPC `-32603 internal_error` を返す。
- timeout (default 30s) による自然回収。
- §4.5 の **session lifecycle hook (`cancel_session`)** により、クライアント切断・
  session expiry 経路でも `_pending` エントリは即時回収される。
  これにより `max_pending` の保護が「TTL/idle 単位での即時開放」と組み合わせて
  実効的に機能する。

### 8.5 request body サイズ

`POST /approvals` の body は 1KB 上限 (`Request.body()` 長さチェック)。超過時 413 を返却。
**必須事項**: Starlette/FastAPI の `Request.body()` はペイロード全体をメモリにキャッシュするため、このコード層のチェックだけでは大容量ボディを送りつける DoS 攻撃を防げない。さらに Uvicorn 単体にはボディサイズ上限の起動オプションが存在しない。そのため、防御の主体として**リバースプロキシ (例: Nginx の `client_max_body_size`) または ASGI レベルのミドルウェアでリクエストサイズの上限を設定することを必須化**する。`Request.body()` による後段チェックは、あくまで防御の補助として位置づける。

### 8.6 audit "reason" フィールドの正規化と文字数制限 (`sanitize_reason`)

`reason` フィールド (および全箇所で出現する同名の理由文字列) は、ログインジェクションやログ基盤の破壊を防ぐため、ヘルパー関数 `sanitize_reason()` 等を用いて以下のクレンジングと切り詰め (Truncation) を**必須**とする:

1. **制御文字の除去**: 改行 (`\n`) を除く ASCII < 32 の制御文字をすべてストリップする。
2. **空白の正規化**: 連続する空白文字を 1 つのスペースに置換し、前後の空白をトリムする。
3. **最大バイト長制限**: UTF-8 エンコーディングで最大 256 バイトに切り詰める (文字境界での切り捨てを保証すること)。

**実装要件**: これらの正規化・切り詰め処理は、`PermissionHook` の評価時や、`POST /approvals` ハンドラ層、および audit log schema において、永続化・ログ出力される**前**にランタイムコードで確実に実行されるように実装すること。

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
   `POST /approvals` で `approve` するとアップストリームが呼ばれ、
   `reject` すると `-32002` が返ることが新規テストで検証される。

## 11. 既知の限界 / 将来課題

- **マルチプロセス非対応**: インメモリ実装のため gunicorn 等の複数 worker
  展開では承認状態が共有されない。将来 Redis Pub/Sub 等への置換を想定する。
- **MCP elicitation 未統合**: ccgate の "Server-defined Prompts" 相当の
  MCP プロトコルレベルでの UI 連携は本仕様では扱わない。
- **operator role の policy 表現 (lateral approval 対策)**: 本仕様の認可は
  「要求元 ≠ resolver」の単純規則のみで、§8.1 末尾の「既知の限界 (lateral approval)」
  に記載した脅威 (複数登録 agent 間での横断承認) を防がない。policy DSL に
  許可主体 (例: `permitted_approvers: [agent_id, ...]` や
  `approver_role: operator`) を導入する高度な表現は将来課題。
  実装時は `IntentPolicy` / `ToolGuardrail` への `permitted_approvers:
  frozenset[str] | None` 追加と、`PolicyEngine.evaluate_call()` 戻り値への
  許可主体集合の伝搬、`PendingApprovalRegistry.register()` 引数への
  `permitted_approvers: frozenset[str]` 追加が必要となる。
- **永続化された監査ログの長期保管**: 本仕様では audit log を `AuditLogger`
  経由の構造化ログ出力に留める。長期保管・改ざん検知 (例: WORM ストレージ)
  は将来課題。
