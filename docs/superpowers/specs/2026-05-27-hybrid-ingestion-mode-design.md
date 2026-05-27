# Hybrid Ingestion Mode & Turn-based Full Ingestion 設計書

- **作成日**: 2026-05-27
- **対象機能**: `CHRONOS_INGESTION_MODE` ハイブリッド保存モード（`all` / `selective`）
- **スコープ**: `mcp_gateway` ツール隠蔽 + クライアント側ターン終了フック
- **言語**: 日本語（spec.json.language に準拠）

## 1. 概要

ChronosGraph に「全量保存モード（`all`）」と「従来判定モード（`selective`）」を切り替えるハイブリッド保存モードを追加する。`all` モードでは、エージェントの判断による `memory_save` ツール呼び出しを排し、ターン終了時にクライアント側の独立プロセスがすべての会話ログを fire-and-forget で保存する運用に切り替える。`memory_save` ツールは MCP Gateway の `tools/list` レスポンスから物理的に除外され、エージェントの認知資源を消費しない。

`memory_save_url`（手動 URL 取り込み）など、その他の手動保存ツールは引き続き公開する。

## 2. アーキテクチャ

```
┌──────────────────┐  shell &  ┌──────────────────────┐
│  Agent process   │ ────────► │ agent_turn_hook.py   │ (B-1: 分離プロセス)
└──────────────────┘           │  httpx + asyncio     │
                               │  timeout=2.0s        │
                               └──────────┬───────────┘
                                          │ SSE /sse → session_id
                                          │ POST /messages tools/call
                                          ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Gateway (FastAPI, port 9100)                             │
│                                                              │
│  GatewaySettings.ingestion_mode  ─── "all" | "selective"     │
│         │                                                    │
│         ▼                                                    │
│  ToolRegistry(hidden_tools={"memory_save"} if "all" else ∅)  │
│         │                                                    │
│         ├─ all_tools         ── hidden_tools 除外            │
│         └─ filter_by_caps(.) ── hidden_tools 除外            │
└─────────────────────────────────────────────────────────────┘
                                          │ tools/call memory_save (通る)
                                          ▼
┌─────────────────────────────────────────────────────────────┐
│ context_store (upstream MCP server)                          │
│  Settings.ingestion_mode ── 観測用 / 将来の Pipeline 分岐    │
│  Classifier: FALLBACK_PENALTY=0.5 でノイズ抑制（既存）       │
└─────────────────────────────────────────────────────────────┘
```

### 設計の核

- フラグ `CHRONOS_INGESTION_MODE` は `Settings`（context_store）と `GatewaySettings`（gateway）の**両方**に独立に追加し、それぞれが env エイリアス経由で同じ環境変数を読む（`MCP_GATEWAY_` プレフィックスは付かない）。
- Gateway 側は `ToolRegistry` で `memory_save` を `tools/list` から落とす。`tools/call` 経路は無修正のため、フック経由の呼び出しは引き続き成立する（「人が叩く裏口は残し、エージェントの目には見せない」）。
- 既存の `Classifier`（`FALLBACK_PENALTY=0.5`）は無変更のまま、`all` モード下の低品質コンテンツのノイズ抑制を担う。
- フックは独立した「ターン終了」プロセスとして起動され、メインのエージェント実行を一切ブロックしない。

## 3. 変更ファイル一覧

| ファイル | 変更内容 | 行数目安 |
|---|---|---|
| `src/context_store/config.py` | `Settings` に `ingestion_mode: Literal["all", "selective"]` を追加（env エイリアス `CHRONOS_INGESTION_MODE`、デフォルト `"selective"`） | +6行 |
| `src/mcp_gateway/config.py` | `GatewaySettings` に同フィールドを追加（同じ env エイリアス、`MCP_GATEWAY_` プレフィックス無視） | +6行 |
| `src/mcp_gateway/tools/registry.py` | `ToolRegistry.__init__` に `hidden_tools: AbstractSet[str] = frozenset()` を追加。`all_tools` / `filter_by_caps` は `hidden_tools` を差し引いて返す | +8行 |
| `src/mcp_gateway/app.py` | `build_app()` で `settings.ingestion_mode == "all"` のとき `hidden_tools={"memory_save"}` を渡す | +4行 |
| `scripts/agent_turn_hook.py` | 新規。stdin から会話ログを受け取り、Gateway HTTP に fire-and-forget で `memory_save` を呼ぶ | ~120行 |
| `tests/unit/test_tool_registry_hidden.py` | 新規。`hidden_tools` の挙動を検証 | ~40行 |
| `tests/unit/test_settings_ingestion_mode.py` | 新規。両 Settings の env エイリアス解決を検証 | ~30行 |

## 4. コンポーネント設計

### 4.1 `Settings.ingestion_mode`（context_store）

- 役割: 観測/ログ用。将来 `Pipeline` 分岐が必要になった時のフック地点を確保するのみで、今回の Pipeline ロジックは無変更。
- 配置: `src/context_store/config.py` の `Settings` クラス内、`# --- Ingestion ---` セクション。
- フィールド定義（イメージ）:
  ```python
  ingestion_mode: Literal["all", "selective"] = Field(
      default="selective",
      validation_alias="CHRONOS_INGESTION_MODE",
      description="記憶保存の挙動。'all' は全量保存（ツール隠蔽併用）、'selective' は従来判定。",
  )
  ```

### 4.2 `GatewaySettings.ingestion_mode`（gateway）

- 役割: ツール隠蔽の判定ソース。`build_app()` 起動時に 1 度だけ参照され、ホットリロードは非対応。
- 配置: `src/mcp_gateway/config.py` の `GatewaySettings` クラス内。
- env エイリアスにより `MCP_GATEWAY_` プレフィックスをバイパスし、context_store 側と同じ環境変数を共有する。

### 4.3 `ToolRegistry.hidden_tools`

- 役割: tools/list レスポンスから除外する tool 名の集合。
- ライフサイクル: `__init__` で固定。ランタイム変更なし。
- 新シグネチャ:
  ```python
  def __init__(
      self,
      all_tools: list[dict[str, Any]],
      *,
      hidden_tools: AbstractSet[str] = frozenset(),
  ) -> None:
  ```
- 動作:
  - `all_tools` プロパティ: `[t for t in self._all if t["name"] not in self._hidden]`
  - `filter_by_caps(caps)`: `t.name in caps AND t.name not in self._hidden` のみ返す
- `replace_tools(new_tools)`: `_all` のみ差し替え、`hidden_tools` は不変。

### 4.4 `build_app()` 連携

`src/mcp_gateway/app.py` の `ToolRegistry(initial_tools or [])` を、`settings.ingestion_mode` を読んで以下に置き換える:

```python
hidden = frozenset({"memory_save"}) if settings.ingestion_mode == "all" else frozenset()
registry = ToolRegistry(initial_tools or [], hidden_tools=hidden)
```

### 4.5 `scripts/agent_turn_hook.py`

- **入力**: stdin から会話ログ全文、または `--content` CLI 引数。stdin と `--content` 両方ある場合は `--content` を優先。
- **環境変数**:
  - `MCP_GATEWAY_URL` (default `http://127.0.0.1:9100`)
  - `MCP_GATEWAY_API_KEY` （必須、未設定なら ERROR ログ + exit 0）
  - `MCP_INTENT` (default `memory.ingest`)
  - `MCP_HOOK_TIMEOUT_SECONDS` (default `2.0`、全体タイムアウト)
  - `LOG_LEVEL` (default `INFO`)
- **シーケンス**:
  1. `httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.0))` を開く。
  2. `GET /sse` を `stream=True` で叩き、最初の `data: /messages?session_id=XXX` を取得して切断。
  3. `POST /messages?session_id=XXX` に JSON-RPC `tools/call memory_save` を投げる。
  4. レスポンスは body を読まず close。
- **fire-and-forget 運用**: 呼び出し側のシェルで `&` を付ける（`echo "$LOG" | python scripts/agent_turn_hook.py &`）。スクリプト自体は同期完結し、`os.fork()` 等の自己デタッチは行わない。
- **常に exit 0**: いかなる例外も握りつぶし、メインプロセスに影響しない。

## 5. データフロー

### 5.1 F-2 ツール隠蔽（リクエスト時）

```
POST /messages  method="tools/list"
        │
        ▼
tools = tool_registry.filter_by_caps(caps=record.caps)
        │  ┌──────────────────────────────────────────┐
        │  │ ToolRegistry.filter_by_caps:             │
        │  │   for t in self._all:                    │
        │  │     if t.name in caps                    │
        │  │     and t.name not in self._hidden:      │
        │  │       yield deepcopy(t)                  │
        │  └──────────────────────────────────────────┘
        ▼
JSON-RPC result.tools = [...memory_save_url, memory_search, ...]
                        # memory_save は含まれない
```

### 5.2 F-3 フック呼び出し

```
[エージェントのターン終了]
  $ echo "$CONVERSATION_LOG" | python scripts/agent_turn_hook.py &

[agent_turn_hook.py 内]
  asyncio.run(main(timeout=2.0))
        │
        ├─ async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0)):
        │     # SSE handshake で session_id 取得
        │     # JSON-RPC tools/call memory_save
        │
        ├─ except (asyncio.TimeoutError, httpx.HTTPError) as exc:
        │     logger.warning("turn hook failed: %s", exc)
        │
        └─ sys.exit(0)
```

## 6. エラーハンドリング & グレースフルデグラデーション

### 6.1 Gateway 側

| 失敗ケース | 挙動 |
|---|---|
| `CHRONOS_INGESTION_MODE` 不正値 | Pydantic `ValidationError` で起動失敗（fail-fast） |
| `CHRONOS_INGESTION_MODE` 未設定 | `"selective"` がデフォルトで適用、後方互換性を保証 |
| `hidden_tools` に存在しない名前 | 警告なし。何も除外しない |

### 6.2 フック側（フェイルソフト）

すべての例外を握りつぶし、exit code は常に 0。メインのエージェントプロセスは絶対にクラッシュさせない。

| 例外 | ログレベル | exit code |
|---|---|---|
| `asyncio.TimeoutError`（2秒超過） | INFO | 0 |
| `httpx.ConnectError` / `httpx.HTTPError` | WARNING | 0 |
| `httpx.HTTPStatusError` (4xx/5xx) | WARNING（status のみ、body は出さず） | 0 |
| SSE で `session_id` が取得できない | WARNING | 0 |
| `MCP_GATEWAY_API_KEY` 未設定 | ERROR | 0 |
| stdin 空 / 内容 0 バイト | DEBUG（呼び出しスキップ） | 0 |
| 想定外の `Exception`（broad catch） | WARNING with traceback | 0 |

ログフォーマット: `"%(asctime)s [%(levelname)s] agent_turn_hook: %(message)s"`、stream は stderr。

### 6.3 トラフィック増大対策（`all` モード）

- フック側 `httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0))` で打ち切り、滞留させない。
- フックは 1 ターンに 1 プロセス起動 / 1 リクエスト送信。並列度はシェル `&` に任せる。
- Gateway 側のレート制限・キューイングは今回スコープ外。タイムアウト到達でフックは諦め、後続ターンに影響を出さない。

### 6.4 `Classifier` フォールバックとの相互作用

- `memory_save` 呼び出しは通常通り `Orchestrator.save` → `Pipeline` → `Classifier` を経由する。
- `Classifier` の `FALLBACK_PENALTY=0.5` は引き続き作動し、低品質コンテンツの `importance_score` を 0.25 に下げる。
- 本実装で `Classifier` / `Pipeline` のコードは無変更。

## 7. テスト方針

### 7.1 ユニットテスト（新規）

1. `tests/unit/test_tool_registry_hidden.py`
   - `hidden_tools={"memory_save"}` で `all_tools` に `memory_save` が含まれないこと
   - `filter_by_caps({"memory_save", "memory_search"})` が `memory_save` を除外し `memory_search` を返すこと
   - デフォルト引数（`hidden_tools` 未指定）で既存挙動が壊れないこと
2. `tests/unit/test_settings_ingestion_mode.py`
   - `CHRONOS_INGESTION_MODE=all` → `Settings().ingestion_mode == "all"` および `GatewaySettings(policy_path=...).ingestion_mode == "all"`
   - 未設定時のデフォルト `"selective"`
   - 不正値で `ValidationError` 発生

### 7.2 単体テスト対象外

- `scripts/agent_turn_hook.py` は外部 I/O 依存・E2E カバー想定。型注釈と `ruff/mypy` パスのみ保証する。

## 8. 検証手順（Devcontainer 内で必ず実行）

```bash
# 0. Devcontainer に入る（VS Code: Reopen in Container、または CLI）
#    以降のコマンドはすべて devcontainer 内で実行する。

# 1. 依存関係の同期
uv sync --all-extras

# 2. Lint と Format チェック
uv run ruff check src/context_store/config.py \
                  src/mcp_gateway/config.py \
                  src/mcp_gateway/tools/registry.py \
                  src/mcp_gateway/app.py \
                  scripts/agent_turn_hook.py \
                  tests/unit/test_tool_registry_hidden.py \
                  tests/unit/test_settings_ingestion_mode.py

# 3. 静的型チェック
uv run mypy src/context_store/config.py \
            src/mcp_gateway/config.py \
            src/mcp_gateway/tools/registry.py \
            src/mcp_gateway/app.py \
            scripts/agent_turn_hook.py

# 4. 新規ユニットテスト
uv run pytest tests/unit/test_tool_registry_hidden.py -v
uv run pytest tests/unit/test_settings_ingestion_mode.py -v

# 5. 既存テストのリグレッション確認
uv run pytest tests/unit/ -k "registry or settings or gateway" -v

# 6. （任意）手動 E2E 確認
CHRONOS_INGESTION_MODE=all uv run python -m mcp_gateway &
sleep 2
curl -s -N http://127.0.0.1:9100/sse \
     -H "authorization: Bearer $TEST_API_KEY" \
     -H "x-mcp-intent: memory.ingest" | head -1
# → /messages?session_id=XXX が得られたら、その session_id で:
curl -s -X POST "http://127.0.0.1:9100/messages?session_id=XXX" \
     -H "content-type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
# → "memory_save" が含まれず、"memory_save_url" は含まれること
```

## 9. 受け入れ条件

- [ ] **AC-1**: `CHRONOS_INGESTION_MODE` 未設定または `selective` のとき、tools/list に `memory_save` が含まれる（既存挙動）。
- [ ] **AC-2**: `CHRONOS_INGESTION_MODE=all` のとき、tools/list に `memory_save` が含まれず、`memory_save_url` は含まれる。
- [ ] **AC-3**: `CHRONOS_INGESTION_MODE=all` でも `tools/call memory_save` は引き続き呼び出し可能（フック経由の隠し API として機能）。
- [ ] **AC-4**: `CHRONOS_INGESTION_MODE=invalid_value` で `mcp_gateway` 起動が `ValidationError` で fail-fast する。
- [ ] **AC-5**: `agent_turn_hook.py` が Gateway 到達不可・タイムアウト・認証失敗のいずれにおいても exit 0 で終了し、stderr に WARNING または INFO ログを出す。
- [ ] **AC-6**: `uv run ruff check` と `uv run mypy` が変更ファイル全てでパスする。
- [ ] **AC-7**: `Classifier` / `Pipeline` のコードに差分がない（git diff で確認）。

## 10. 非ゴール（YAGNI）

以下は今回のスコープ外:

- `CHRONOS_INGESTION_MODE` のホットリロード（プロセス再起動で適用）
- フック側のリトライ・キューイング・永続化
- Gateway 側のレート制限・サーキットブレーカー
- 既存 LLM Evaluator (Universal Evaluator) のコードパス変更
- `Classifier` の閾値変更や追加ロジック

## 11. 関連ファイル参照

- `src/context_store/config.py:139-148` — Ingestion セクション（追加場所）
- `src/mcp_gateway/config.py:32-86` — GatewaySettings
- `src/mcp_gateway/tools/registry.py:1-21` — ToolRegistry（拡張対象）
- `src/mcp_gateway/app.py:110-124` — ToolRegistry 構築箇所
- `src/mcp_gateway/server.py:207-209` — tools/list ハンドラ
- `src/context_store/ingestion/classifier.py:22-24` — FALLBACK_PENALTY 定数
- `src/context_store/server.py:147-195` — memory_save / memory_save_url 実装
