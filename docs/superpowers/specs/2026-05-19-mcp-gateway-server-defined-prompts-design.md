# ChronosGraph MCP Gateway — Server-defined Prompts (Hook) 設計書

- 作成日: 2026-05-19
- 対象: `src/mcp_gateway/`
- 関連 SPEC: `SPEC.md` §16.2.1（近期予定）
- 参考文献: [LayerX ccgate (Zenn)](https://zenn.dev/layerx/articles/20260428-ccgate)
- 設計手法: superpowers/brainstorming スキルによる構造化ブレインストーミング
- ステータス: ユーザー承認済み (design 段階)

## 0. サマリー

ChronosGraph MCP Gateway に MCP プロトコルの `prompts/list` および `prompts/get` JSON-RPC メソッドを実装し、エージェントが接続時にサーバー側から「役割（intent.description）と利用可能ツール（allowed_tools）」を自動取得できるようにする。これにより、運用者が `docs/agent-prompts/*.md` を手動でエージェント設定に貼り付ける手間を排除し、ポリシー設定の「最大効率」を実現する。

実装は既存の `ToolRegistry` パターンを踏襲し、起動時に `PromptBuilder` が `policy + tools` から決定論的に Prompt を合成、`PromptRegistry` が不変キャッシュとして保持する。セッション認可は `record.intent` を介して `tools/list` と完全対称となるよう設計する。

## 1. 設計判断（ブレインストーミング結果）

ユーザーとの対話で確定した 7 つの基本方針：

| # | 判断項目 | 採択案 | 理由 |
|---|---------|--------|------|
| 1 | プロンプトの源泉 | **ポリシードリブン動的生成**（`intents.yaml` ベース） | SPEC が掲げる「手動設定ゼロ化」の最短路。Markdown テンプレを別管理する案（ハイブリッド）は YAGNI |
| 2 | プロンプト粒度 | **intent 単位**: `chronos-graph.<intent_name>` | MCP スラッシュコマンドとの親和性。`tools/list` と粒度が揃う |
| 3 | セッション中の `prompts/list` 戻り値 | **現セッションの 1 intent のみ** | セッションが 1 intent に固定されている既存設計と整合。`tools/list` の `caps` フィルタと同じ設計言語 |
| 4 | 本文構成要素 | **description + ツール説明 + guardrails 要約**（標準） | SPEC「役割と利用可能ツール」要件を満たし、エージェントが承認待ちツールを自己理解可能。`inputSchema` フル展開はトークン消費過大 |
| 5 | 出力言語 | **`GatewaySettings.prompt_language` で切替**、デフォルト `"en"` | 既存 intent.description が英語、Claude プロンプト最適化が英語、ただし運用者が日本語へオプトイン可能 |
| 6 | `prompts/get` 引数 | **なし** | intent が確定すれば本文も一意。質問 5 の言語切替はセッション全体設定で十分 |
| 7 | 生成タイミング | **起動時 lifespan で全 intent × 言語を事前合成** | `ToolRegistry`（起動時 1 回読み込み）と一貫。性能・予測性◎。ポリシー再読み込みは再起動運用 |

## 2. アーキテクチャ全体図

```text
┌─────────────── Startup (app.py lifespan) ────────────────┐
│                                                          │
│  GatewaySettings ──┐                                     │
│                    │  prompt_language                    │
│                    ▼                                     │
│  policy (intents.yaml) ──┐                               │
│                          │                               │
│  upstream.list_tools() ──┤                               │
│                          ▼                               │
│              PromptBuilder.build_all(                    │
│                 policy, tools, language                  │
│              ) → dict[intent_name, Prompt]               │
│                          │                               │
│                          ▼                               │
│                   PromptRegistry                         │
│              (frozen / cached at startup)                │
│                                                          │
└──────────────────────────────────────────────────────────┘
                           │
                           │ app.state.prompt_registry
                           ▼
┌────────────── Request (server.py /messages) ─────────────┐
│                                                          │
│  POST /messages?session_id=<sid>                         │
│    method == "prompts/list" →                            │
│        prompt_registry.list_for(record.intent)           │
│        → 1-element list (intent's prompt summary)        │
│                                                          │
│    method == "prompts/get" →                             │
│        params.name 検証                                  │
│        prompt_registry.get_for(record.intent, name)      │
│        → { description, messages: [...] }                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

設計原則：

- `PromptRegistry` は **不変** (`frozen=True` dataclass + `MappingProxyType`) → 起動後の意図しない変更を防止
- セッションフィルタリングは `tools/list` と完全対称：`tools/list` が `record.caps` でフィルタするのと同じく、`prompts/list` は `record.intent` でフィルタ
- `PromptBuilder` は純粋関数的（policy/tools/lang を入力に、決定論的出力）→ 単体テスト最小コスト
- セッション未登録 intent（policy 未整合）に対して `PromptRegistry.list_for()` は空リストを返す安全防御

## 3. コンポーネント詳細

### 3.1 データモデル (`src/mcp_gateway/prompts/models.py`)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class PromptMessage:
    """MCP prompts/get の messages 配列要素。"""
    role: Literal["user", "assistant"]  # MCP 仕様: system 役不可
    text: str  # type=text コンテンツ


@dataclass(frozen=True, slots=True)
class Prompt:
    """`prompts/get` のレスポンス本体。"""
    name: str           # "chronos-graph.<intent_name>"
    description: str    # 短いサマリー (intent.description ベース)
    messages: tuple[PromptMessage, ...]  # 不変


@dataclass(frozen=True, slots=True)
class PromptSummary:
    """`prompts/list` 戻り値の各エントリ（MCP 仕様準拠、本文除く）。"""
    name: str
    description: str
    arguments: tuple = ()  # 引数なし運用（決定 #6）
```

### 3.2 `PromptBuilder` (`src/mcp_gateway/prompts/builder.py`)

```python
class PromptBuilder:
    """policy + tools + language から決定論的に Prompt を合成する純粋関数群。"""

    @staticmethod
    def build_all(
        *,
        policy: GatewayPolicy,
        tools: list[dict[str, Any]],
        language: Literal["en", "ja"],
    ) -> dict[str, Prompt]:
        """全 intent 分の Prompt を生成して intent_name → Prompt のマップを返す。"""

    @staticmethod
    def _render(
        *, intent_name: str, intent: IntentDef,
        tools_by_name: dict[str, dict[str, Any]], language: str,
    ) -> Prompt:
        """1 intent 分。description + tools section + guardrails section を合成。"""
```

責務境界：

- `PromptBuilder` は副作用なし（I/O なし、純粋データ変換）
- 言語別文言は `prompts/templates.py` のテンプレート関数群に隔離
- フェイルファスト：`intent.description` が空文字なら `ValueError`

### 3.3 `PromptRegistry` (`src/mcp_gateway/prompts/registry.py`)

```python
from types import MappingProxyType

class PromptRegistry:
    def __init__(self, prompts_by_intent: dict[str, Prompt]) -> None:
        self._prompts = MappingProxyType(dict(prompts_by_intent))  # 不変ビュー

    def list_for(self, intent: str) -> list[PromptSummary]:
        """セッションの intent に対応する 1 件のサマリ（未登録なら空リスト）。"""

    def get_for(self, intent: str, name: str) -> Prompt | None:
        """name が intent と一致しない、または未登録なら None。"""
```

`Prompt` は frozen dataclass + 内部 `tuple` のため、`ToolRegistry` のように `deepcopy` で防御する必要なし。lookup は O(1)。

### 3.4 `server.py` ディスパッチャ差分

既存 `tools/list`, `tools/call` の直後に 2 ブランチを追加（line ~210 付近）：

```python
if method == "prompts/list":
    summaries = prompt_registry.list_for(record.intent)
    audit.log(
        ev="prompts_list", decision="allow",
        agent=record.agent_id, intent=record.intent,
        sid=sid, count=len(summaries),
    )
    return JSONResponse({
        "jsonrpc": "2.0", "id": rpc_id,
        "result": {"prompts": [asdict(s) for s in summaries]},
    })

if method == "prompts/get":
    params = body.get("params")
    if not isinstance(params, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32602,
                      "message": "Invalid params: 'params' must be an object"}})
    name = params.get("name")
    if not name:
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32602,
                      "message": "Invalid params: missing required parameter: name"}})
    prompt = prompt_registry.get_for(record.intent, name)
    if prompt is None:
        audit.log(ev="prompts_get", decision="deny", reason="unknown_prompt",
                  agent=record.agent_id, intent=record.intent, sid=sid, prompt=name)
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": -32602, "message": f"unknown prompt {name!r}"}})
    audit.log(ev="prompts_get", decision="allow",
              agent=record.agent_id, intent=record.intent, sid=sid, prompt=name)
    return JSONResponse({
        "jsonrpc": "2.0", "id": rpc_id,
        "result": {
            "description": prompt.description,
            "messages": [
                {"role": m.role, "content": {"type": "text", "text": m.text}}
                for m in prompt.messages
            ],
        },
    })
```

### 3.5 `app.py` 配線

```python
# lifespan 内、ToolRegistry.replace_tools(all_tools) の直後
prompts_by_intent = PromptBuilder.build_all(
    policy=policy, tools=all_tools, language=settings.prompt_language,
)
prompt_registry = PromptRegistry(prompts_by_intent)
app.state.prompt_registry = prompt_registry

# build_router(...) の引数に prompt_registry を追加
```

### 3.6 `config.py` 拡張

```python
class GatewaySettings(BaseSettings):
    ...
    prompt_language: Literal["en", "ja"] = "en"
```

## 4. データフロー（具体例）

### 4.1 入力（起動時）

```yaml
# intents.example.yaml（抜粋）
intents:
  curate_memories:
    description: "Curate own working memory. Search/save/delete; no external URL."
    allowed_tools: [memory_search, memory_save, memory_delete, memory_prune]
    guardrails:
      memory_delete: { requires_approval: true }
      memory_prune:  { requires_approval: true }
```

```python
# upstream.list_tools() 結果（抜粋）
[
  {"name": "memory_search", "description": "Search memories by text or vector.", ...},
  {"name": "memory_save",   "description": "Persist a memory item.", ...},
  {"name": "memory_delete", "description": "Delete a memory by id.", ...},
  {"name": "memory_prune",  "description": "Prune memories by criteria.", ...},
]
```

### 4.2 合成結果（`PromptBuilder.build_all` 出力）

```text
name:        "chronos-graph.curate_memories"
description: "Curate own working memory. Search/save/delete; no external URL."

messages[0]: role="user", text=
    You are operating under the 'curate_memories' role on ChronosGraph MCP Gateway.

    ## Role
    Curate own working memory. Search/save/delete; no external URL.

    ## Available Tools
    - memory_search: Search memories by text or vector.
    - memory_save: Persist a memory item.
    - memory_delete: Delete a memory by id. [REQUIRES APPROVAL]
    - memory_prune: Prune memories by criteria. [REQUIRES APPROVAL]

    Tools marked [REQUIRES APPROVAL] will block on a human approval gate
    before executing. Only call them when the operation is intentional.
```

### 4.3 リクエスト：`prompts/list`

```json
// Request (record.intent = "curate_memories")
{"jsonrpc":"2.0","id":1,"method":"prompts/list"}

// Response
{"jsonrpc":"2.0","id":1,"result":{"prompts":[
  {
    "name": "chronos-graph.curate_memories",
    "description": "Curate own working memory. Search/save/delete; no external URL.",
    "arguments": []
  }
]}}
```

### 4.4 リクエスト：`prompts/get`

```json
// Request
{"jsonrpc":"2.0","id":2,"method":"prompts/get",
 "params":{"name":"chronos-graph.curate_memories"}}

// Response
{"jsonrpc":"2.0","id":2,"result":{
  "description": "Curate own working memory. Search/save/delete; no external URL.",
  "messages": [
    {"role":"user","content":{"type":"text","text":"You are operating under ..."}}
  ]
}}
```

### 4.5 認可境界

| シナリオ | 動作 |
|---|------|
| `record.intent="curate_memories"` が `prompts/get name="chronos-graph.curate_memories"` | 本文返却 |
| `record.intent="curate_memories"` が `prompts/get name="chronos-graph.read_only_recall"` | -32602 `unknown prompt`（**他 intent のプロンプト本文は漏らさない**） |
| `record.intent="curate_memories"` が `prompts/get name="chronos-graph.nonexistent"` | -32602 `unknown prompt` |

エラーメッセージは「unknown prompt」で統一し、存在判定の情報漏洩を防止する。

## 5. エラーハンドリング & 監査

### 5.1 JSON-RPC エラーコード

| 状況 | code | message | HTTP |
|---|---|---|---|
| `params` が dict でない (`prompts/get`) | -32602 | `Invalid params: 'params' must be an object` | 200 |
| `params.name` 欠落・空文字 | -32602 | `Invalid params: missing required parameter: name` | 200 |
| 未登録 prompt 名 / 他 intent のプロンプト要求 | -32602 | `unknown prompt 'NAME'` | 200 |
| `session_id` invalid | 既存ハンドラ | `session_invalid` | 404 |
| body が dict でない | 既存 -32600 | `Invalid Request: body must be an object` | 200 |
| body が JSON でない | 既存 -32700 | `Parse error: ...` | 200 |
| 未知 method | 既存 -32601 | `unknown method 'METHOD'` | 200 |

`prompts/list` は引数を取らないため -32602 はほぼ発生しない。

### 5.2 起動時の故障モード（フェイルファスト）

| 故障 | 動作 | 理由 |
|---|------|------|
| `intent.description` が空文字 | `ValueError("intent <name> has empty description")` → app 起動失敗 | プロンプトの「役割」が空のままサーブするのは仕様違反 |
| `intent.allowed_tools=[]` | 警告ログ、Prompt は生成（`## Available Tools\n(none)`） | 構文的には合法（read-only な intent 等で許容） |
| 上流 `tools/list` に `allowed_tools` の一部が含まれない | 警告ログ + そのツールはプロンプトから除外 | ポリシー残骸検知用ログ。実害なし |
| `prompt_language` が `"en"/"ja"` 以外 | Pydantic `Literal` 検証で起動失敗 | 設定ミス検知 |

### 5.3 ランタイム例外

`PromptBuilder` は純粋関数で副作用なし。ランタイムの呼び出しは `PromptRegistry.list_for/get_for` のみで `MappingProxyType` の lookup のため例外発生は通常ない。初版では防御的 `try/except` を**入れず**、純粋データ参照は例外しない前提とする（コード簡素化）。

### 5.4 監査ログ

```python
# prompts/list 成功
audit.log(ev="prompts_list", decision="allow",
          agent=record.agent_id, intent=record.intent, sid=sid, count=len(summaries))

# prompts/get 成功
audit.log(ev="prompts_get", decision="allow",
          agent=record.agent_id, intent=record.intent, sid=sid, prompt=name)

# prompts/get unknown_prompt
audit.log(ev="prompts_get", decision="deny", reason="unknown_prompt",
          agent=record.agent_id, intent=record.intent, sid=sid, prompt=name)
```

機微情報の取り扱い：プロンプト本文には `intent.description` と上流 `tool.description` しか含まれず、認証情報・ユーザ入力は一切入らないため、ログには本文を残さず `prompt=name` のみ記録する。

## 6. テスト戦略

### 6.1 単体テスト

| ファイル | 対象 |
|---|------|
| `tests/unit/test_mcp_gateway_prompts_builder.py` | `PromptBuilder` |
| `tests/unit/test_mcp_gateway_prompts_registry.py` | `PromptRegistry` |

**`PromptBuilder` 単体テストケース**：

1. `build_all` が `policy.intents` 全件分の Prompt を返す
2. `Prompt.name` が `"chronos-graph.<intent>"` 形式
3. `Prompt.description` が `intent.description` と一致
4. `messages[0].text` が `allowed_tools` 全件を列挙し、各ツールの description を含む
5. `requires_approval: true` のツールに `[REQUIRES APPROVAL]` マーカーが付く
6. `allowed_tools` 中で上流 tools にないツールはスキップ + ログ警告
7. `language="ja"` で日本語テンプレートが選択される
8. `intent.description` 空文字 → `ValueError` 発生
9. `allowed_tools=[]` → Prompt は生成され、ツールセクションは `(none)` 相当
10. 同一入力で複数回呼んでも完全一致（純粋性）

**`PromptRegistry` 単体テストケース**：

1. `list_for(intent)` が登録済み intent に対して 1 件 `PromptSummary` を返す
2. `list_for(intent)` が未登録 intent に対して空リスト
3. `get_for(intent, name)` で name が intent と一致しない場合 `None`
4. `get_for(intent, name)` で完全一致時 `Prompt` を返す
5. 返却値が呼び出し元で改変できない（不変性検証）

### 6.2 統合テスト (`tests/integration/test_mcp_gateway_prompts_e2e.py`)

FastAPI `TestClient` + 既存 `build_app(upstream_override=...)` パターン使用：

1. **handshake → prompts/list → 1 件返却**：`intent=curate_memories` でセッション張り、JSON-RPC `prompts/list` の戻りが `[{name: "chronos-graph.curate_memories", ...}]`
2. **handshake → prompts/get → 本文返却**：`prompts/get name=chronos-graph.curate_memories` の `messages` 配列 text に description と全 tool 名を含む
3. **認可境界**：`intent=read_only_recall` セッションで `prompts/get name=chronos-graph.curate_memories` → -32602 `unknown prompt`
4. **パラメータ検証**：`prompts/get` の `params` 欠落 / `name` 欠落 → -32602
5. **言語切替**：`GatewaySettings(prompt_language="ja")` で起動 → 本文の固定文言（`Available Tools` 等）が日本語化

### 6.3 既存テストへの影響

- `tests/unit/test_mcp_gateway_server.py`：既存 `tools/list` / `tools/call` ハンドラテストには影響なし
- `tests/unit/test_mcp_gateway_app.py`（あれば）：`build_app` の lifespan に `PromptRegistry` 構築が追加されるため、既存テスト assertion を更新（`app.state.prompt_registry` の存在確認程度）

## 7. ファイル構成

| パス | 種別 | 責務 |
|------|------|------|
| `src/mcp_gateway/prompts/__init__.py` | 新規 | パッケージ初期化 |
| `src/mcp_gateway/prompts/models.py` | 新規 | `Prompt`, `PromptMessage`, `PromptSummary` |
| `src/mcp_gateway/prompts/templates.py` | 新規 | 言語別固定文言テンプレート関数群 |
| `src/mcp_gateway/prompts/builder.py` | 新規 | `PromptBuilder`（純粋関数） |
| `src/mcp_gateway/prompts/registry.py` | 新規 | `PromptRegistry`（不変キャッシュ） |
| `src/mcp_gateway/config.py` | 修正 | `prompt_language: Literal["en","ja"]` 追加 |
| `src/mcp_gateway/app.py` | 修正 | lifespan に `PromptRegistry` 構築追加・`build_router` に渡す |
| `src/mcp_gateway/server.py` | 修正 | `build_router` 引数追加・dispatcher 拡張・監査ログ |
| `tests/unit/test_mcp_gateway_prompts_builder.py` | 新規 | `PromptBuilder` 単体 |
| `tests/unit/test_mcp_gateway_prompts_registry.py` | 新規 | `PromptRegistry` 単体 |
| `tests/integration/test_mcp_gateway_prompts_e2e.py` | 新規 | dispatcher 経由 E2E |
| `SPEC.md` | 修正 | §16.2.1 から削除・§16.1 実装済みへ移動 |

## 8. 実装フェーズ（writing-plans への引き継ぎ）

```
Phase 1: モデル + ビルダー
  1.1 prompts/models.py (Prompt, PromptMessage, PromptSummary) [TDD]
  1.2 prompts/templates.py (en/ja テンプレート関数) [TDD]
  1.3 prompts/builder.py (PromptBuilder.build_all) [TDD]

Phase 2: レジストリ + 認可
  2.1 prompts/registry.py (PromptRegistry) [TDD]

Phase 3: 配線
  3.1 config.py (prompt_language 追加)
  3.2 app.py (lifespan で構築・state 配置)
  3.3 server.py (dispatcher 拡張 + 監査ログ) [TDD]

Phase 4: E2E + ドキュメント
  4.1 integration/test_mcp_gateway_prompts_e2e.py [TDD]
  4.2 SPEC.md 更新（§16.1 へ移動、§16.2 から削除）
```

## 9. 設計外（YAGNI）

以下は今回スコープ外。将来要件が顕在化したら別スペックで対応：

- ホットリロード（`POST /admin/reload`）：質問 7-C で却下。現状のポリシー読み込みパターンと一致しない
- `notifications/prompts/list_changed`：起動時固定のため不要
- `prompts/get` 引数によるテンプレート展開（質問 6-B/C）：現状の決定論的生成で十分
- セッション複数 intent 化（質問 3'-A-3）：既存 `SessionRecord` モデルの大規模リファクタリングを要する
- ハイブリッド Markdown テンプレート（質問 2-C）：手書きの手間が残るため SPEC 目的に反する
- ツール `inputSchema` のプロンプト埋め込み：トークン消費過大、エージェント側で `tools/list` から取得可能

## 10. 上流（context_store）への波及

なし。本機能は MCP Gateway 内部で完結する。上流 `context_store` の MCP サーバーへの `prompts/*` 実装は将来課題（gateway が pass-through する設計に切替えるなら別途検討）。
