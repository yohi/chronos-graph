# MCP Gateway 設計書 (ChronosGraph)

- **作成日**: 2026-04-30
- **対象パッケージ**: `src/mcp_gateway/` (新規)
- **対象環境**: Python 3.12 / `uv` / devcontainer
- **依存(無変更)**: `src/context_store/`

## 1. 目的とスコープ

外部AIエージェント (MCPクライアント) と既存コア `src/context_store/` の間に位置する **MCPゲートウェイ** を新規実装する。エージェント型AIの「権限の危機」(過剰権限・セマンティック特権昇格・認可ギャップ)に対して、以下のセキュリティ原則を実装上の責務に分解する。

- **ゼロ・スタンディング・権限 (ZSP)**: エージェントには永続的な権限を持たせず、SSE接続ごとに短命JIT(Just-In-Time)で権限を解決し、内部 `SessionRecord` に閉じ込める(エージェントは長期APIキー以外を保持しない)。
- **意図に基づくアクセス制御 (IBAC)**: エージェントが宣言した「意図」と実際のツール呼び出しを照合し、意図逸脱をブロックする。
- **認可ギャップの解消**: 取得時 (Default Deny によるツール非露出) と出力時 (構造ベース allowlist フィルタ) の二段で、想定外フィールドの漏出を防ぐ。
- **ツールレベル Default Deny と分離**: 公開ツールはデフォルトで拒否。バックエンドのシークレットはゲートウェイ側で管理し、エージェントへ渡さない。

### 非目標 (out of scope)

- mTLS / OAuth2 / OIDC によるエージェント認証 (`AgentAuthenticator` プロトコルを切ることで将来拡張可能とする)
- LLM ベースの意図分類 (確率的挙動を避けるため、明示的な intent class 宣言のみ)
- センシティビティ・タグの伝播 (context_store コアの改変が必要となるため除外)
- マルチプロセス共有のセッションストア (MVP はプロセス内 dict, 後で Redis 化可能なプロトコル化)

## 2. アーキテクチャ概要

### 2.1 全体図

```text
┌────────────────┐  GET /sse (接続時のみ:                  ┌──────────────────────────────────┐    MCP over          ┌──────────────────────┐
│ External AI    │   Authorization: Bearer ck_<api_key>     │   src/mcp_gateway/  (新規)        │ ───stdio (subprocess)─▶ │ src/context_store/   │
│ Agent (client) │   X-MCP-Intent: <intent_class>) ────────▶│   ZSP / IBAC / 出力フィルタ        │ ◀─────────────────── │ (既存・無変更)        │
│                │  POST /messages?session_id=<sid> ◀─────▶ │   (内部 SessionRegistry が         │  Gateway 側で秘密注入     └──────────────────────┘
└────────────────┘                                          │    SessionRecord を保持)          │
                                                            └──────────────────────────────────┘
```

- 外向き (エージェント ↔ Gateway): **MCP over SSE トランスポート** — `GET /sse` (server→client イベントストリーム) + `POST /messages?session_id=<sid>` (client→server メッセージ)。**SSE接続確立時のみ** `Authorization: Bearer ck_<api_key>` と `X-MCP-Intent: <intent_class>` (任意で `X-MCP-Requested-Tools: tool_a,tool_b`) を検証する。標準MCPクライアントは追加のトークン交換APIを呼ぶことなく接続できる。
- 内向き (Gateway ↔ context_store): Gateway が **stdio MCP クライアント** として `python -m context_store` を subprocess 起動し維持する
- context_store のコードは **Python レベルで import しない**(MCP プロトコル経由のみ)。これにより制約「context_store を直接書き換えない」を構造的に保証する。
- ZSP / IBAC / 出力フィルタ等のセキュリティ原則は変わらない。変わるのは **JITトークン相当の権限解決・セッション管理が完全に Gateway 内部に閉じる**点のみ(エージェントは session_id しか知らない)。

### 2.2 採用アーキテクチャ判断

| 項目 | 採用 | 主な理由 |
|---|---|---|
| トランスポート | MCP-to-MCP プロキシ。外向きは **SSE トランスポート** (`GET /sse` + `POST /messages?session_id=...`)、内向きは stdio | 標準MCPクライアントが広範に対応する形態。事前トークン交換不要(接続時に Bearer + Intent ヘッダのみ) → 透過性を維持 |
| エージェント認証 | 事前共有APIキー(Bearer)を **SSE接続確立時のみ** 検証 + `AgentAuthenticator` 抽象化 | 自己完結。devcontainer/ローカル開発に適合。将来 mTLS/OIDC 拡張余地。APIキーはツール呼び出しごとには使われない(ZSPの精神を維持) |
| 意図 (Intent) 表現 | Intent class + 要求ツール集合のハイブリッド (案D)。SSE接続時に **HTTPヘッダ** で宣言 (`X-MCP-Intent`, `X-MCP-Requested-Tools`) | 二段絞り込み (intent ∩ requested_tools) で最小権限を厳守。LLM 不要。MCPクライアントの一般的なヘッダ設定機能と互換 |
| 出力フィルタ | 構造ベース allowlist (プラグイン構造) | 決定論的・テスト可能。`OutputFilter` プロトコルで拡張 (PII redaction 等)。 |
| 内部セッション形式 | プロセス内 `SessionRegistry` が保持する `SessionRecord` (frozen dataclass) | エージェントへ渡らないため JWT 署名は不要(YAGNI)。session_id (uuid4) はSSEで通知。失効は TTL + 接続切断 + アイドルタイムアウトで実現 |
| セッション単位 | SSE 接続単位、TTL=900s (デフォルト) + アイドルタイムアウト | 1接続=1意図=1ケイパビリティセット。MCPの会話モデルと整合。SSE切断で即座に失効。 |

### 2.3 主要コンポーネント

| 層 | モジュール | 責務 |
|---|---|---|
| 入口層 | `server.py` (FastAPI + MCP SSE トランスポート) | `GET /sse` (接続時認証 + 内部セッション生成 + イベントストリーム維持) と `POST /messages?session_id=...` (MCPメッセージ受付・ディスパッチ) の二系統 |
| 認証層 | `auth/api_key.py`, `auth/protocol.py` | 長期APIキーの検証(`AgentAuthenticator` プロトコル)。**SSE接続時のみ呼ばれる** |
| セッション層 | `auth/handshake.py`, `auth/session.py`, `auth/headers.py` | SSE接続時のヘッダ検証 → intent 解決 → 内部 `SessionRecord` 生成・参照・TTL/アイドル失効。`SessionRegistry` プロトコル経由で後付け Redis 化可能 |
| 認可層 (IBAC) | `policy/loader.py`, `policy/engine.py` | `intents.yaml` 読み込み + intent×tool×output_filter 検証 |
| ツール公開層 | `tools/registry.py`, `tools/proxy.py` | 上流ツール定義を `SessionRecord.caps` でDefault Denyフィルタ。実呼び出しを上流にプロキシ |
| 出力フィルタ層 | `filters/protocol.py`, `filters/structural_allowlist.py`, `filters/none_filter.py` | プラガブルな出力フィルタ。intentに紐付くプロファイルを適用 |
| 上流クライアント層 | `upstream/context_store_client.py` | context_storeをstdioサブプロセスとして起動・MCPクライアント接続を維持・シークレット注入(env=...)・呼び出しの仲介 |
| 設定層 | `config.py` | Pydantic Settings(`MCP_GATEWAY_*` 環境変数) |
| 監査層 | `audit/logger.py` | 構造化JSONログをstderrへ |
| エントリ | `__main__.py`, `app.py` | `python -m mcp_gateway` で起動 |

## 3. データフローとシーケンス

### 3.1 セッション開始 (SSE 接続時認証 + 内部セッション生成)

```text
Agent                               mcp_gateway                              context_store
  │ GET /sse                              │                                         │
  │ Authorization: Bearer ck_<api_key>    │                                         │
  │ X-MCP-Intent: read_only_recall        │                                         │
  │ X-MCP-Requested-Tools: memory_search  │ ← 任意。省略時は intent.allowed_tools 全体 │
  ├──────────────────────────────────────▶│                                         │
  │                                       │ ① AgentAuthenticator.authenticate()     │
  │                                       │   失敗ならば SSE 確立せず 401 で終了      │
  │                                       │                                         │
  │                                       │ ② Headers から intent/requested_tools を │
  │                                       │   パース。PolicyEngine.evaluate_grant(   │
  │                                       │     agent_id, intent, requested_tools)  │
  │                                       │   ・intent が存在するか                   │
  │                                       │   ・requested ⊆ intent.allowed_tools     │
  │                                       │   ・agent が intent を使う権限を持つか    │
  │                                       │   違反ならば SSE 確立せず 403 で終了      │
  │                                       │                                         │
  │                                       │ ③ SessionRegistry.create(...) で         │
  │                                       │   SessionRecord を生成 (session_id=uuid4)│
  │                                       │   {agent_id, intent, caps, out,         │
  │                                       │    issued_at, expires_at}               │
  │                                       │   ※ Agent には返さない(内部状態のみ)     │
  │                                       │                                         │
  │ SSE: event: endpoint                  │                                         │
  │ data: /messages?session_id=<sid>      │                                         │
  │◀──────────────────────────────────────┤                                         │
  │ (以降、SSE ストリームを維持。          │                                         │
  │  サーバから notifications を流す)      │                                         │
```

- 長期APIキーは **SSE接続確立時にしか使われない** ← ZSP の中核(ツール呼び出しごとに長期権限が露出しない)
- `effective_caps = requested_tools ∩ intent.allowed_tools` (ハイブリッド絞り込み)。`X-MCP-Requested-Tools` ヘッダ省略時は `intent.allowed_tools` 全体を採用
- 失敗パスはすべて構造化監査ログを残す (`decision=deny, reason=...`)
- **エージェントは session_id しか持たない**。SessionRecord(intent / caps / output_filter 等)はゲートウェイ内部のみで保持されるため、JWT 署名のような改ざん防御は不要(YAGNI)

### 3.2 `tools/list` (Default Deny)

```text
Agent                               mcp_gateway                              context_store
  │ POST /messages?session_id=<sid>      │                                         │
  │ MCP: tools/list                      │                                         │
  ├─────────────────────────────────────▶│                                         │
  │                                      │ ① SessionRegistry.lookup(session_id)     │
  │                                      │   → SessionRecord                        │
  │                                      │   無効/期限切れ/失効ならば 404 で SSE 切断 │
  │                                      │ ② upstream.list_tools()  (キャッシュ)     │
  │                                      ├────────── tools/list ──────────────────▶│
  │                                      │◀────── ToolDefinition[] ───────────────┤
  │                                      │ ③ ToolRegistry.filter_by_caps(           │
  │                                      │     all_tools, session.caps)            │
  │ SSE: event: message                  │                                         │
  │ data: tools = [filtered]             │                                         │
  │◀─────────────────────────────────────┤                                         │
```

- 認可されていないツールは**そもそも露出しない** (Default Deny)
- 上流の tools/list はゲートウェイ起動直後に1回キャッシュする (運用で変動しないため)。再ロードは管理APIまたは再起動。
- レスポンスは SSE ストリーム経由で返却される(MCP SSE 仕様の `event: message` フレーム)

### 3.3 `tools/call` (主経路: IBAC + 出力フィルタ)

```text
Agent                               mcp_gateway                              context_store
  │ POST /messages?session_id=<sid>      │                                         │
  │ MCP: tools/call(name=memory_search,  │                                         │
  │   arguments={query:"..."})           │                                         │
  ├─────────────────────────────────────▶│                                         │
  │                                      │ ① SessionRegistry.lookup(session_id)     │
  │                                      │   無効/期限切れならば 404 で SSE 切断     │
  │                                      │ ② PolicyEngine.check_call(               │
  │                                      │     session, tool_name, arguments)      │
  │                                      │   ・tool_name ∈ session.caps             │
  │                                      │   違反ならば エラー応答 + 監査           │
  │                                      │ ③ シークレット注入は subprocess の         │
  │                                      │   env で完結。arguments のサニタイズ検査 │
  │                                      │ ④ upstream.call_tool(tool_name, args)    │
  │                                      ├────────── tools/call ──────────────────▶│
  │                                      │◀──────── result payload ────────────────┤
  │                                      │ ⑤ OutputFilter.apply(                    │
  │                                      │     intent, tool_name, payload,         │
  │                                      │     filter_profile=session.out)         │
  │ SSE: event: message                  │                                         │
  │ data: filtered payload               │                                         │
  │◀─────────────────────────────────────┤                                         │
  │                                      │ ⑥ AuditLogger.log(allow, latency_ms…)    │
```

- ステップ② が **IBAC 防御の主柱** (ツールの実体呼び出し前)
- ステップ⑤ が **認可ギャップ防御の主柱** (レスポンス出力時)
- ステップ③ で「エージェント側 arguments にシークレット風の文字列(例: `sk-...` プレフィックス)が含まれないか」を**サニタイズ検査**(混入防止)
- 結果は SSE ストリームで `event: message` フレームとして返却される

### 3.4 エラー応答ポリシー

| 状況 | 通知経路 | エージェントへの応答 | 監査記録 |
|---|---|---|---|
| API キー不正 (SSE 接続時) | HTTP 401 | SSE 確立せず終了 | `decision=deny, reason=auth_failed` |
| intent ヘッダ欠落 / 範囲外要求 (SSE 接続時) | HTTP 403 | SSE 確立せず終了 | `decision=deny, reason=policy_violation` |
| session_id 不明 / 期限切れ (POST /messages) | HTTP 404 | SSE 切断 | `decision=deny, reason=session_invalid` |
| 未認可ツール呼び出し | SSE message | MCP `error: tool not found` (存在自体を露出させない) | `decision=deny, reason=tool_not_in_caps` |
| 上流エラー | SSE message | MCP `error: upstream_error` (詳細は隠蔽) | `decision=upstream_error` |

## 4. ファイル構造

### 4.1 `src/mcp_gateway/`

```text
src/mcp_gateway/
├── __init__.py                       # パッケージマーカー
├── __main__.py                       # `python -m mcp_gateway` エントリ
├── py.typed                          # PEP 561 (strict mypy 適合)
│
├── app.py                            # FastAPI アプリ生成 + ルート登録 (/sse, /messages)
├── server.py                         # MCP SSE トランスポートハンドラ (GET /sse + POST /messages)
├── config.py                         # Pydantic Settings (MCP_GATEWAY_*)
│
├── auth/
│   ├── __init__.py
│   ├── protocol.py                   # AgentAuthenticator Protocol
│   ├── api_key.py                    # APIキー方式の実装
│   ├── headers.py                    # X-MCP-Intent / X-MCP-Requested-Tools パース
│   ├── handshake.py                  # SSE接続時のヘッダ検証 + Intent解決 + Session生成
│   └── session.py                    # SessionRecord (frozen dataclass) + SessionRegistry (Protocol + InMemory実装、TTL/アイドル管理)
│
├── policy/
│   ├── __init__.py
│   ├── models.py                     # IntentPolicy / GatewayPolicy (Pydantic)
│   ├── loader.py                     # intents.yaml → GatewayPolicy
│   └── engine.py                     # evaluate_grant / check_call (IBAC)
│
├── tools/
│   ├── __init__.py
│   ├── registry.py                   # 上流ツール定義の保持 + caps フィルタ
│   └── proxy.py                      # tools/call を上流へ仲介
│
├── filters/
│   ├── __init__.py
│   ├── protocol.py                   # OutputFilter Protocol
│   ├── factory.py                    # プロファイル名 → OutputFilter
│   ├── none_filter.py                # 素通し
│   └── structural_allowlist.py       # フィールド allowlist
│
├── upstream/
│   ├── __init__.py
│   └── context_store_client.py       # stdio MCP クライアント (subprocess)
│
├── audit/
│   ├── __init__.py
│   └── logger.py                     # 構造化 JSON ログ (stderr)
│
├── policies/
│   └── intents.example.yaml          # 同梱サンプル (実運用は env で外部指定)
│
└── errors.py                         # GatewayError 階層
```

### 4.2 テスト構造

既存リポジトリ慣習 (`tests/unit/test_*.py` のフラット単一ファイル) に従う。

```text
tests/unit/
└── test_mcp_gateway.py        # 全テストクラスを集約
```

### 4.3 モジュール間依存方向

```text
server.py ──depends on──▶ auth.handshake, auth.session, policy.engine,
                          tools.registry, tools.proxy, filters.factory,
                          upstream.context_store_client, audit.logger

auth.handshake ──depends on──▶ auth.api_key, auth.headers, auth.session, policy.engine

policy.engine ──depends on──▶ policy.models  (純粋ロジック; I/O 依存なし)

tools.proxy ──depends on──▶ upstream.context_store_client, filters.factory, audit.logger

filters.* ──no inbound deps to gateway──▶ 純粋関数として実装

upstream.context_store_client ──only depends on──▶ mcp.client.stdio + config
                                                 (※ src/context_store/ には Python import しない)
```

### 4.4 `pyproject.toml` の差分

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
    # ── mcp_gateway で追加 ──
    "fastapi>=0.115.0",          # 既に dashboard で使用 / 通常依存に昇格
    "uvicorn[standard]>=0.30.0", # 同上
    "sse-starlette>=2.1.0",      # SSEトランスポートのレスポンス実装
    "pyyaml>=6.0",               # intents.yaml 読込
]

[project.scripts]
context-store = "context_store.__main__:main"
chronos-dashboard = "context_store.dashboard.api_server:main"
chronos-mcp-gateway = "mcp_gateway.__main__:main"   # 追加

[tool.hatch.build.targets.wheel]
packages = ["src/context_store", "src/mcp_gateway"] # mcp_gateway を追加

[[tool.mypy.overrides]]
module = "sse_starlette.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "yaml.*"
ignore_missing_imports = true
```

> **注**: `fastapi` / `uvicorn` は既存 `[project.optional-dependencies] dashboard` のみに含まれていた。`mcp_gateway` も使うため、**通常依存(必須)** に昇格させる。dashboard 専用の extras 構成は維持する(冪等)。

## 5. 設定モデルとポリシーDSL

### 5.1 環境変数 (`config.py` / Pydantic Settings)

```python
class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_GATEWAY_", env_file=".env")

    # ── HTTPサーバー ──
    host: str = "127.0.0.1"
    port: int = 9100

    # ── 内部セッション ──
    session_ttl_seconds: int = 900           # デフォルト 15 分(SSE 接続時刻からの絶対TTL)
    session_idle_timeout_seconds: int = 300  # 5 分間 POST /messages が無ければ失効
    session_issuer: str = "chronos-mcp-gateway"  # 監査ログの ev 識別用

    # ── 認証 ──
    # APIキーマップ: {"agent_id": "raw_api_key"}
    # MCP_GATEWAY_API_KEYS_JSON='{"summarizer-bot":"ck_xxx"}'
    api_keys_json: SecretStr | None = None

    # ── ポリシー ──
    policy_path: Path                    # 必須: intents.yaml の絶対パス

    # ── 上流(context_store) ──
    # NOTE: デフォルトは devcontainer 内 (uv sync 済み .venv が PATH 上位) を前提。
    # devcontainer 外で使用する場合は MCP_GATEWAY_UPSTREAM_COMMAND を
    # ["uv", "run", "python", "-m", "context_store"] 等に明示的に設定すること。
    upstream_command: list[str] = ["python", "-m", "context_store"]
    upstream_env_passthrough: list[str] = [
        "OPENAI_API_KEY", "CONTEXT_STORE_DB_PATH",
        "GRAPH_ENABLED", "EMBEDDING_PROVIDER",
    ]

    # ── 監査 ──
    audit_log_level: Literal["INFO", "DEBUG"] = "INFO"
```

- `api_keys_json` は `SecretStr` で `repr` マスク → ログ汚染防止
- `upstream_env_passthrough` は **allowlist 方式**(網羅的継承禁止) → シークレット漏出最小化
- `policy_path` 必須 → ポリシー無しでは起動しない (Default Deny の徹底)
- 内部 `SessionRecord` はゲートウェイ内に閉じるため署名鍵は不要(SSE接続単位の生存期間 + アイドルタイムアウトで失効)

### 5.2 ポリシー DSL (`intents.yaml`)

```yaml
version: 1

# 出力フィルタプロファイル定義
output_filters:
  recall_safe:
    type: structural_allowlist
    schemas:
      memory_search:
        results:
          - id
          - content
          - created_at
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

# Intent 定義
intents:
  read_only_recall:
    description: "過去メモリの検索・要約用途。書き込み・外部送出は不可。"
    allowed_tools: [memory_search, memory_search_graph, memory_stats]
    output_filter: recall_safe

  curate_memories:
    description: "自分の作業メモリの整理。検索・保存・削除可、外部URLは不可。"
    allowed_tools: [memory_search, memory_save, memory_delete, memory_prune]
    output_filter: curator_full

  ingest_external_url:
    description: "外部URLからの取り込み専用。"
    allowed_tools: [memory_save_url]
    output_filter: url_ingestion

# エージェント↔Intent 認可マトリクス
agents:
  summarizer-bot:
    allowed_intents: [read_only_recall]
  curator-bot:
    allowed_intents: [read_only_recall, curate_memories]
  ingestion-bot:
    allowed_intents: [ingest_external_url]
```

### 5.3 Pydantic モデル (`policy/models.py` 抜粋)

```python
class StructuralAllowlistSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    # キー = フィールド名, 値 = True (スカラ残置) | list[str] (ネストの allowlist)
    # NOTE: extra="allow" は動的キー構造のため必須。タイポ検出は
    # GatewayPolicy._verify_references で schemas キーとツール名の整合性を検証する。

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
        # intent.output_filter が output_filters に存在
        # agent.allowed_intents が intents に存在
        # type=structural_allowlist のとき schemas 必須
        # output_filters[*].schemas のキー(ツール名)が、いずれかの
        #   intents[*].allowed_tools に含まれること (タイポ検出)
        # 不整合は起動失敗 (Fail-fast / Default Deny)
        ...
```

### 5.4 内部 `SessionRecord` 形状

エージェントへ渡らない内部状態のため、署名・暗号化は不要 (YAGNI)。`frozen` な dataclass で不変性を保証する。

```python
@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str               # uuid4 — Agent には SSE event endpoint 経由で通知される
    agent_id: str                 # API キーから解決
    intent: str                   # X-MCP-Intent ヘッダ値
    caps: frozenset[str]          # effective_caps = requested_tools ∩ intent.allowed_tools
    output_filter_profile: str    # intent.output_filter のキー名
    issued_at: datetime           # 接続確立時刻 (UTC)
    expires_at: datetime          # issued_at + session_ttl_seconds
```

`SessionRegistry` プロトコルが TTL 失効・アイドル失効・SSE 切断時の即時削除を担う。リクエストパスでは `lookup(session_id)` のみ → 高速。後付けで Redis 実装に差し替え可能。

**アイドルタイムアウト管理**: `last_active_at` は `SessionRecord` の外部で管理する。`frozen=True` による不変性を維持しつつ TOCTOU 競合を回避するため、`SessionRegistry` が内部 `dict[str, datetime]` (`_last_active`) として保持し、`POST /messages` 受信ごとにアトミックに更新する。`lookup()` 時にアイドル判定を行い、タイムアウト超過時はセッションを失効させる。

### 5.5 監査ログ形状 (JSON Lines, stderr)

```json
{"ts":"2026-04-30T12:00:00Z","ev":"handshake","agent":"summarizer-bot","intent":"read_only_recall","decision":"allow","sid":"5a0f...","caps":["memory_search"]}
{"ts":"2026-04-30T12:00:01Z","ev":"call","agent":"summarizer-bot","tool":"memory_search","decision":"allow","sid":"5a0f...","latency_ms":42}
{"ts":"2026-04-30T12:00:02Z","ev":"call","agent":"summarizer-bot","tool":"memory_save","decision":"deny","sid":"5a0f...","reason":"tool_not_in_caps"}
```

stderr 出力は既存 ChronosGraph の方針と一致 (stdout は MCP 通信に使うため絶対に汚染しない)。

## 6. テスト戦略

### 6.1 方針

- **devcontainer 内で完結**: `uv run pytest tests/unit/test_mcp_gateway.py -v` で通る
- **`mypy --strict` 適合**: テストは既存の `[[tool.mypy.overrides]] module = "tests.*"` 緩和に乗る
- **`ruff check` クリーン**: 既存ルール (`E,F,I,S,B`) で警告ゼロ
- **`asyncio_mode = "auto"`**: 既存設定どおり `async def test_*` を直接記述
- **外部I/O禁止**: 上流 context_store の subprocess は **AsyncMock で代替**
- **テストデータ完結**: `tmp_path` で `intents.yaml` を一時生成

### 6.2 テストクラス構成 (`tests/unit/test_mcp_gateway.py`)

```python
class TestSettings: ...                  # env → GatewaySettings 解決 / 必須欠落で失敗
class TestPolicyLoader: ...              # YAML 読込 / 参照整合性 / 不正DSL で起動失敗
class TestPolicyEngine: ...              # IBAC 評価ロジック (純粋関数)
class TestApiKeyAuthenticator: ...       # APIキー解決 / 不正キー
class TestHeaderParsing: ...             # X-MCP-Intent / X-MCP-Requested-Tools パース・正規化・空欄処理
class TestSessionLifecycle: ...          # SessionRecord 生成→lookup→TTL失効→アイドル失効→明示削除
class TestToolRegistry: ...              # Default Deny: caps外を露出させない
class TestStructuralAllowlistFilter: ... # allowlist 適用 / ネスト / list[dict]
class TestUpstreamClientMock: ...        # subprocess env allowlist / list_tools / call_tool
class TestSseHandshakeEndpoint: ...      # GET /sse: ヘッダ検証 → session 生成 → endpoint event 通知 / 認証失敗 / intent違反
class TestMcpMessagesEndpoint: ...       # POST /messages?session_id=...: tools/list の caps 絞込 / tools/call の認可・出力フィルタ・拒否・上流エラー
class TestSecretIsolation: ...           # env allowlist / レスポンスにシークレットなし
```

### 6.3 共通 fixture (抜粋)

```python
@pytest.fixture
def sample_policy_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "intents.yaml"
    p.write_text(textwrap.dedent("""
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
    """).strip())
    return p

@pytest.fixture
def settings(sample_policy_yaml, monkeypatch) -> GatewaySettings:
    monkeypatch.setenv("MCP_GATEWAY_API_KEYS_JSON", '{"test-agent":"ck_test"}')
    monkeypatch.setenv("MCP_GATEWAY_POLICY_PATH", str(sample_policy_yaml))
    return GatewaySettings()  # type: ignore[call-arg]

@pytest.fixture
def mock_upstream() -> AsyncMock:
    m = AsyncMock()
    m.list_tools.return_value = [
        {"name": "memory_search", "description": "...", "inputSchema": {}},
        {"name": "memory_save",   "description": "...", "inputSchema": {}},
    ]
    m.call_tool.return_value = {
        "results": [
            {"id": "m1", "content": "hello",
             "embedding": [0.1, 0.2], "internal_score": 0.9}
        ],
        "total_count": 1,
    }
    return m
```

### 6.4 代表アサーション例

```python
# (a) SSE ハンドシェイク: ヘッダ検証 → endpoint イベント通知
async def test_sse_handshake_emits_endpoint_event(app_client, ...):
    headers = {"Authorization": "Bearer ck_test", "X-MCP-Intent": "read_only_recall"}
    async with app_client.stream("GET", "/sse", headers=headers) as resp:
        assert resp.status_code == 200
        # 最初のイベントが endpoint で session_id を含む
        first_line = await anext(resp.aiter_lines())
        assert "/messages?session_id=" in first_line

# (b) Default Deny: tools/list が caps で絞られる
async def test_tools_list_filters_to_caps(app_client, session_id, ...):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = await app_client.post(f"/messages?session_id={session_id}", json=body)
    # SSE で返ってきたイベントを集約
    tools = [t["name"] for t in collected_event["result"]["tools"]]
    assert tools == ["memory_search"]
    assert "memory_save" not in tools

# (c) IBAC: caps 外ツール拒否(存在自体を露出しない)
async def test_call_unauthorized_tool_denied(app_client, session_id, ...):
    body = {"jsonrpc": "2.0", "id": 2,
            "method": "tools/call",
            "params": {"name": "memory_save", "arguments": {}}}
    resp = await app_client.post(f"/messages?session_id={session_id}", json=body)
    assert "tool not found" in collected_event["error"]["message"].lower()

# (d) 出力フィルタ: 機密フィールド除去
async def test_output_filter_strips_unlisted_fields(app_client, session_id, ...):
    payload = collected_event["result"]
    assert "embedding" not in payload["results"][0]
    assert "internal_score" not in payload["results"][0]
    assert payload["results"][0]["content"] == "hello"

# (e) セッション無効: 不明な session_id は 404
async def test_unknown_session_id_returns_404(app_client):
    resp = await app_client.post("/messages?session_id=nonexistent",
                                  json={"jsonrpc":"2.0","id":1,"method":"tools/list"})
    assert resp.status_code == 404

# (f) シークレット隔離
def test_upstream_env_allowlist(monkeypatch, settings):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-leak")
    env = build_upstream_env(settings)
    assert "AWS_SECRET_ACCESS_KEY" not in env
```

### 6.5 検証コマンド (devcontainer 内)

```bash
# 単体テスト
uv run pytest tests/unit/test_mcp_gateway.py -v

# 静的解析
uv run ruff check src/mcp_gateway/ tests/unit/test_mcp_gateway.py
uv run ruff format --check src/mcp_gateway/ tests/unit/test_mcp_gateway.py
uv run mypy src/mcp_gateway/

# CI 相当
uv run ruff check src/mcp_gateway/ && uv run mypy src/mcp_gateway/ && \
  uv run pytest tests/unit/test_mcp_gateway.py -v
```

## 7. リスクと留意点

| リスク | 影響 | 緩和策 |
|---|---|---|
| MCP SSE トランスポートの SDK 仕様差異 | エンドポイント名やイベントフレーム形式の乖離 | 実装着手時に最新の `mcp` SDK と接続先MCPクライアントの仕様を確認。`/sse` + `/messages` は MCP HTTP/SSE 仕様に準拠する形で実装し、必要なら `sse-starlette` を使って生実装する |
| 上流 subprocess の起動失敗 / 異常終了 | ゲートウェイが「沈黙する」 | ヘルスチェックエンドポイント (`/healthz`) を用意。失敗時は502。再起動戦略はMVP外 |
| プロセス内セッションストアの再起動消失 | 既存セッションが消え、エージェントは再接続が必要 | TTL を短く保つ (デフォルト900s) + アイドルタイムアウト。Redis 化は後続 PR で `SessionRegistry` プロトコル経由で差し替え |
| ポリシー誤設定 | 過剰権限 | 起動時 Fail-fast バリデーション + 監査ログで `decision` を全件記録 → 監査で発見可能 |
| シークレットがレスポンスに混入 | 機密漏洩 | (a) 出力 allowlist で構造的に除去 (b) シークレット風文字列のサニタイズ検査 (c) `SecretStr` で内部表現を保護 |

## 8. 受け入れ基準 (Acceptance Criteria)

実装が以下を満たすこと:

1. devcontainer 内で `uv run pytest tests/unit/test_mcp_gateway.py -v` が **全グリーン**
2. `uv run ruff check src/mcp_gateway/` が **警告ゼロ**
3. `uv run mypy src/mcp_gateway/` が **エラーゼロ** (strict)
4. `uv run python -m mcp_gateway` で起動でき、`GET /sse` (Bearer + `X-MCP-Intent` ヘッダで接続) → `POST /messages?session_id=...` (tools/list, tools/call) の主経路が通る
5. **既存 `src/context_store/` 配下のファイルが diff で 0 件**(無変更を保証)
6. `intents.yaml` の参照整合性違反で**起動が失敗**する (Fail-fast 検証)
7. 監査ログが stderr に JSON Lines で出力され、stdout が汚染されない

## 9. 後続作業 (out of scope for this spec)

- マルチプロセス対応 (Redis ベースの `SessionRegistry` 実装 / 共有ポリシーキャッシュ)
- mTLS / OIDC エージェント認証の実装 (`AgentAuthenticator` 拡張)
- PII redaction フィルタの追加
- レート制限 / 同時実行制御
- ポリシーホットリロード (現状は再起動)
