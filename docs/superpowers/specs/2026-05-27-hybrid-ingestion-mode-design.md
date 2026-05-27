# Hybrid Ingestion Mode & Turn-based Full Ingestion 設計書

- **作成日**: 2026-05-27
- **対象機能**: `CHRONOS_INGESTION_MODE` ハイブリッド保存モード（`all` / `selective`）
- **スコープ**: `mcp_gateway` ツール隠蔽 + クライアント側ターン終了フック
- **言語**: 日本語（spec.json.language に準拠）

## 1. 概要

ChronosGraph に「全量保存モード（`all`）」と「従来判定モード（`selective`）」を切り替えるハイブリッド保存モードを追加する。`all` モードでは、エージェントの判断による `memory_save` ツール呼び出しを排し、ターン終了時にクライアント側の独立プロセスがすべての会話ログを fire-and-forget で保存する運用に切り替える。`memory_save` ツールは MCP Gateway の `tools/list` レスポンスから物理的に除外され、エージェントの認知資源を消費しない。

`memory_save_url`（手動 URL 取り込み）など、その他の手動保存ツールは引き続き公開する。

## 2. アーキテクチャ

```text
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

- フラグ `CHRONOS_INGESTION_MODE` の**型・デフォルト値・env 変数名は独立した共通パッケージ `src/chronos_shared/ingestion_mode.py` に集約**し、`Settings`（context_store）と `GatewaySettings`（gateway）の両方がそこから import して使用する（Single Source of Truth）。共通モジュールを `context_store` や `mcp_gateway` のいずれかに置くと既存のアーキテクチャ原則（`mcp_gateway/upstream/context_store_client.py:3-4`「Gateway は context_store から何も import しない」）を破るため、両者の外側に新規 top-level パッケージを設ける。Gateway は context_store を subprocess として起動する（`build_app()` の `python -m context_store`）独立プロセスのため、ランタイムの値伝達は (a) `GatewaySettings.upstream_env_passthrough` の allowlist に `CHRONOS_INGESTION_MODE` を含めて子プロセスに env を継承、(b) 各 `Settings` がその env を独立に読む、の 2 段で成立する。重複するのは Pydantic フィールド宣言 1 行のみで、型・デフォルト・env 名は単一モジュールに一元化される。
- Gateway 側は `ToolRegistry` で `memory_save` を `tools/list` から落とす。`tools/call` 経路は無修正のため、フック経由の呼び出しは引き続き成立する（「人が叩く裏口は残し、エージェントの目には見せない」）。
- 既存の `Classifier`（`FALLBACK_PENALTY=0.5`）は無変更のまま、`all` モード下の低品質コンテンツのノイズ抑制を担う。
- フックは独立した「ターン終了」プロセスとして起動され、メインのエージェント実行を一切ブロックしない。Gateway の `MaxBodySizeMiddleware`（既定 10 MiB、`mcp_gateway/config.py:81`）に抵触しないよう、フック側で送信前に上限サイズで切り詰める。

## 3. 変更ファイル一覧

| ファイル | 変更内容 | 行数目安 |
|---|---|---|
| `src/chronos_shared/__init__.py` | **新規**。空のパッケージ初期化ファイル | 0行 |
| `src/chronos_shared/ingestion_mode.py` | **新規**。共通モジュール。`IngestionMode = Literal["all", "selective"]` 型、`DEFAULT_INGESTION_MODE: IngestionMode = "selective"`、`CHRONOS_INGESTION_MODE_ENV = "CHRONOS_INGESTION_MODE"` の 3 シンボルのみ公開 | ~10行 |
| `pyproject.toml` | `[tool.hatch.build.targets.wheel].packages` に `"src/chronos_shared"` を追加 | +1行 |
| `src/context_store/config.py` | `Settings` に `ingestion_mode: IngestionMode` を追加。型・デフォルト・env エイリアスは `chronos_shared.ingestion_mode` から import した定数を参照 | +6行 |
| `src/mcp_gateway/config.py` | `GatewaySettings` に同フィールドを追加（同じく `chronos_shared.ingestion_mode` から import）。さらに `upstream_env_passthrough` のデフォルトに `"CHRONOS_INGESTION_MODE"` を追加し subprocess へ伝達 | +7行 |
| `src/mcp_gateway/tools/registry.py` | `ToolRegistry.__init__` に `hidden_tools: AbstractSet[str] = frozenset()` を追加。`all_tools` / `filter_by_caps` は `hidden_tools` を差し引いて返す | +8行 |
| `src/mcp_gateway/app.py` | `build_app()` で `settings.ingestion_mode == "all"` のとき `hidden_tools={"memory_save"}` を渡す | +4行 |
| `scripts/agent_turn_hook.py` | 新規。stdin から会話ログを受け取り、上限サイズで切り詰めたうえで Gateway HTTP に fire-and-forget で `memory_save` を呼ぶ。切り詰めロジックは pure 関数として切り出し単体テスト可能にする | ~140行 |
| `tests/unit/test_tool_registry_hidden.py` | 新規。`hidden_tools` の挙動を検証 | ~40行 |
| `tests/unit/test_settings_ingestion_mode.py` | 新規。両 Settings の env 解決と共通モジュールの型一致、`upstream_env_passthrough` への `"CHRONOS_INGESTION_MODE"` 含有を検証 | ~50行 |
| `tests/unit/test_agent_turn_hook_truncate.py` | 新規。フックの切り詰め pure 関数を検証（HTTP I/O は対象外） | ~30行 |

## 4. コンポーネント設計

### 4.0 共通パッケージ `src/chronos_shared/ingestion_mode.py`（新規）

- 役割: `CHRONOS_INGESTION_MODE` の型・デフォルト値・env 変数名の **Single Source of Truth**。`Settings` と `GatewaySettings` の両方からこのモジュールのみを import する。
- 公開シンボル（これ以外は公開しない）:
  ```python
  from typing import Final, Literal

  IngestionMode = Literal["all", "selective"]
  DEFAULT_INGESTION_MODE: Final[IngestionMode] = "selective"
  CHRONOS_INGESTION_MODE_ENV: Final[str] = "CHRONOS_INGESTION_MODE"
  ```
- 配置理由: `src/mcp_gateway/upstream/context_store_client.py:3-4` に「We intentionally do NOT import anything from `src/context_store/`」というアーキテクチャ原則が明記されている。本共有モジュールを `src/context_store/` 配下に置くと Gateway からのクロスパッケージ import が発生し、この原則を破る。したがって `context_store` にも `mcp_gateway` にも属さない独立した top-level パッケージ `src/chronos_shared/` を新設し、両者から平等に import する形を取る（依存方向: `context_store → chronos_shared`、`mcp_gateway → chronos_shared`。両者の相互依存は引き続き発生しない）。
- パッケージ構成: `src/chronos_shared/__init__.py`（空）と `src/chronos_shared/ingestion_mode.py` の 2 ファイル構成。本モジュールに将来「複数プロセスで一致させる必要のある型・定数」が増える際の置き場としても機能する。
- `pyproject.toml` 更新: `[tool.hatch.build.targets.wheel]` の `packages` に `"src/chronos_shared"` を追加する必要がある（現状 `["src/context_store", "src/mcp_gateway"]`）。

### 4.1 `Settings.ingestion_mode`（context_store）

- 役割: 観測/ログ用。将来 `Pipeline` 分岐が必要になった時のフック地点を確保するのみで、今回の Pipeline ロジックは無変更。
- 配置: `src/context_store/config.py` の `Settings` クラス内、`# --- Ingestion ---` セクション。
- フィールド定義（イメージ）:
  ```python
  from chronos_shared.ingestion_mode import (
      CHRONOS_INGESTION_MODE_ENV,
      DEFAULT_INGESTION_MODE,
      IngestionMode,
  )

  ingestion_mode: IngestionMode = Field(
      default=DEFAULT_INGESTION_MODE,
      validation_alias=CHRONOS_INGESTION_MODE_ENV,
      description="記憶保存の挙動。'all' は全量保存（ツール隠蔽併用）、'selective' は従来判定。",
  )
  ```

### 4.2 `GatewaySettings.ingestion_mode` および `upstream_env_passthrough`（gateway）

- 役割: ツール隠蔽の判定ソース。`build_app()` 起動時に 1 度だけ参照され、ホットリロードは非対応。
- 配置: `src/mcp_gateway/config.py` の `GatewaySettings` クラス内。
- 共通モジュール（`4.0`）から型・デフォルト・env 名を import。`MCP_GATEWAY_` プレフィックスはこのフィールドのみ `validation_alias` でバイパスし、`Settings` と同じ環境変数を読む。
- **サブプロセスへの env 伝達**: `build_app()` は context_store を Python サブプロセス (`python -m context_store`) として起動するため、Gateway プロセスに設定された `CHRONOS_INGESTION_MODE` を子プロセスに継承させる必要がある。`build_upstream_env`（`src/mcp_gateway/upstream/context_store_client.py:26`）は allowlist 方式で env を絞り込む実装になっており、`GatewaySettings.upstream_env_passthrough` の **デフォルトリストに `"CHRONOS_INGESTION_MODE"` を追加**する。これにより Gateway 側と context_store 側の両 `Settings` が同一の env 値を読み、設計の核（"同じ env 変数を各プロセスが独立に読む"）が実コードで成立する。
  - 変更前: `["OPENAI_API_KEY", "CONTEXT_STORE_DB_PATH", "GRAPH_ENABLED", "EMBEDDING_PROVIDER"]`
  - 変更後: `["OPENAI_API_KEY", "CONTEXT_STORE_DB_PATH", "GRAPH_ENABLED", "EMBEDDING_PROVIDER", "CHRONOS_INGESTION_MODE"]`

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

- **入力**: `--content` CLI 引数が指定されていればそれを使用し、未指定の場合は stdin から会話ログ全文を読み取る。
- **環境変数**:
  - `MCP_GATEWAY_URL` (default `http://127.0.0.1:9100`)
  - `MCP_GATEWAY_API_KEY` （必須、未設定なら ERROR ログ + exit 0）
  - `MCP_INTENT` (default `memory.ingest`)
  - `MCP_HOOK_TIMEOUT_SECONDS` (default `2.0`、全体タイムアウト)
  - `MCP_HOOK_MAX_LOG_BYTES` (default `8388608` = 8 MiB、UTF-8 エンコード後の最大送信サイズ。Gateway の `max_request_body_size_bytes` 既定 10 MiB に対し JSON 包装オーバーヘッドを見込んだ 2 MiB のマージン)
  - `LOG_LEVEL` (default `INFO`)
- **送信前の切り詰め (truncation)**:
  - 純関数 `def truncate_log(content: str, max_bytes: int) -> tuple[str, bool]` をモジュールトップレベルに定義し、`(切り詰め後の文字列, was_truncated)` を返す。
  - 切り詰めポリシーは**末尾保持**（先頭側を捨てる）。会話ログでは末尾（最新発話・最終決定）の方が再利用価値が高いため。
  - 切り詰め発生時は冒頭に `"[truncated to last %d bytes]\n"` のマーカー行を付加。マーカー込みでも `max_bytes` を超えない範囲で末尾を切り出す。
  - **UTF-8 境界の扱い**: `content.encode("utf-8")` のバイト列から末尾 N バイトをスライスしたあと `bytes.decode("utf-8", errors="ignore")` でデコードする。`errors="ignore"` はカット境界に残った不完全マルチバイトシーケンスを**破棄**するため、結果文字列には有効な UTF-8 文字のみが残る（境界バイトを「保持して文字化けさせる」のではなく「捨てる」挙動）。末尾保持ポリシーでは破棄対象は先頭側に集中するため、最新情報（末尾）が失われるリスクは低い。最悪ケースで失われるのは切り口の先頭側 1〜3 バイト分の文字のみ。
  - `was_truncated=True` の場合、`logger.warning("payload truncated: original=%d bytes, sent=%d bytes", ...)` を出力。
- **シーケンス**:
  1. `--content` 指定時はその値、未指定時は stdin から `raw` を取得。空なら DEBUG ログ + exit 0。
  2. `payload, was_truncated = truncate_log(raw, MCP_HOOK_MAX_LOG_BYTES)`。
  3. `httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.0))` を開く。
  4. `GET /sse` を `stream=True` で叩き、最初の `data: /messages?session_id=XXX` を取得して切断。
  5. `POST /messages?session_id=XXX` に JSON-RPC `tools/call memory_save` を `arguments.content=payload` で投げる。
  6. レスポンスは body を読まず close。
- **fire-and-forget 運用**: 呼び出し側のシェルで `&` を付ける（`echo "$LOG" | python scripts/agent_turn_hook.py &`）。スクリプト自体は同期完結し、`os.fork()` 等の自己デタッチは行わない。
- **常に exit 0**: いかなる例外も握りつぶし、メインプロセスに影響しない。

## 5. データフロー

### 5.1 F-2 ツール隠蔽（リクエスト時）

```text
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

```text
[エージェントのターン終了]
  $ echo "$CONVERSATION_LOG" | python scripts/agent_turn_hook.py &

[agent_turn_hook.py 内]
  asyncio.run(main(timeout=2.0))
        │
        ├─ async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0)):
        │     # SSE handshake で session_id 取得
        │     # JSON-RPC tools/call memory_save
        │
        ├─ except asyncio.TimeoutError as exc:
        │     logger.info("turn hook timed out: %s", exc)   # all モードで頻発しうるため INFO
        │
        ├─ except httpx.HTTPError as exc:
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

| 例外 / 条件 | ログレベル | exit code |
|---|---|---|
| `asyncio.TimeoutError`（2秒超過） | INFO | 0 |
| `httpx.ConnectError` / `httpx.HTTPError` | WARNING | 0 |
| `httpx.HTTPStatusError` (4xx/5xx) | WARNING（status のみ、body は出さず） | 0 |
| Gateway から `413 Payload Too Large`（切り詰め後でも超過した場合） | WARNING（`MCP_HOOK_MAX_LOG_BYTES` 調整を促すメッセージ含む） | 0 |
| SSE で `session_id` が取得できない | WARNING | 0 |
| `MCP_GATEWAY_API_KEY` 未設定 | ERROR | 0 |
| 入力ログが `MCP_HOOK_MAX_LOG_BYTES` を超過し切り詰め発生 | WARNING（送信は継続） | 0 |
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
   - 未設定時のデフォルト `"selective"`（共通モジュールの `DEFAULT_INGESTION_MODE` と一致）
   - 不正値で `ValidationError` 発生
   - 共通モジュール `chronos_shared.ingestion_mode` から両 Settings が同じ型・定数を import していること（import パスを比較）
   - `GatewaySettings().upstream_env_passthrough` に `"CHRONOS_INGESTION_MODE"` が含まれること（AC-10 担保）
   - `build_upstream_env(passthrough=GatewaySettings().upstream_env_passthrough, base_env={"CHRONOS_INGESTION_MODE": "all", ...})` の戻り値に `"CHRONOS_INGESTION_MODE": "all"` が含まれること
3. `tests/unit/test_agent_turn_hook_truncate.py`
   - `truncate_log(short_text, max=1024)` → `(short_text, False)`（無切り詰め）
   - `truncate_log("a" * 5000, max=1024)` → 結果が `max_bytes` 以下かつ末尾の `"a"` を含み、`was_truncated == True`
   - マルチバイト UTF-8 入力（日本語）でバイト境界が破壊されないこと（`decode("utf-8", errors="ignore")` でも文字化けが起きない範囲）
   - 切り詰め時に `"[truncated to last %d bytes]"` マーカーが冒頭に付くこと

### 7.2 単体テスト対象外

- `scripts/agent_turn_hook.py` の HTTP I/O 部分（handshake・POST）は外部 I/O 依存・E2E カバー想定。型注釈と `ruff/mypy` パスのみ保証する。pure 関数の `truncate_log` のみ単体テスト対象。

## 8. 検証手順（Devcontainer 内で必ず実行）

```bash
# 0. Devcontainer に入る（VS Code: Reopen in Container、または CLI）
#    以降のコマンドはすべて devcontainer 内で実行する。

# 1. 依存関係の同期
uv sync --all-extras

# 2. Lint と Format チェック
uv run ruff check src/chronos_shared/ingestion_mode.py \
                  src/context_store/config.py \
                  src/mcp_gateway/config.py \
                  src/mcp_gateway/tools/registry.py \
                  src/mcp_gateway/app.py \
                  scripts/agent_turn_hook.py \
                  tests/unit/test_tool_registry_hidden.py \
                  tests/unit/test_settings_ingestion_mode.py \
                  tests/unit/test_agent_turn_hook_truncate.py

# 3. 静的型チェック
uv run mypy src/chronos_shared/ingestion_mode.py \
            src/context_store/config.py \
            src/mcp_gateway/config.py \
            src/mcp_gateway/tools/registry.py \
            src/mcp_gateway/app.py \
            scripts/agent_turn_hook.py

# 4. 新規ユニットテスト
uv run pytest tests/unit/test_tool_registry_hidden.py -v
uv run pytest tests/unit/test_settings_ingestion_mode.py -v
uv run pytest tests/unit/test_agent_turn_hook_truncate.py -v

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
- [ ] **AC-8**: `agent_turn_hook.py` が `MCP_HOOK_MAX_LOG_BYTES`（既定 8 MiB）を超える入力を受けた場合、末尾保持で切り詰めて送信し、先頭に `[truncated to last %d bytes]` マーカーを付加することで通常は Gateway 側で 413 が発生しない。切り詰め発生時には WARNING ログを出力する。万が一（JSON 包装オーバーヘッド・追加マージン不足等で）Gateway から 413 が返った場合も、フックは WARNING ログを出力して exit 0 で終了しメインプロセスをクラッシュさせない。
- [ ] **AC-9**: `CHRONOS_INGESTION_MODE` の型・デフォルト値・env 名は `src/chronos_shared/ingestion_mode.py` のみで定義され、`Settings` と `GatewaySettings` の両方が同モジュールから import している（grep で確認）。`src/mcp_gateway/` から `src/context_store/` への import は引き続き 0 件（`grep "from context_store" src/mcp_gateway/` が空）。
- [ ] **AC-10**: `GatewaySettings.upstream_env_passthrough` のデフォルト値に `"CHRONOS_INGESTION_MODE"` が含まれ、Gateway を `CHRONOS_INGESTION_MODE=all` で起動すると context_store サブプロセスの `Settings.ingestion_mode` も `"all"` になる（統合テストまたは subprocess の env を検証するユニットテストで確認）。

## 10. 非ゴール（YAGNI）

以下は今回のスコープ外:

- `CHRONOS_INGESTION_MODE` のホットリロード（プロセス再起動で適用）
- フック側のリトライ・キューイング・永続化
- Gateway 側のレート制限・サーキットブレーカー
- 既存 LLM Evaluator (Universal Evaluator) のコードパス変更
- `Classifier` の閾値変更や追加ロジック

## 11. 関連ファイル参照

- `src/chronos_shared/ingestion_mode.py` — **新規**。共通パッケージ（型・デフォルト・env 名の SSOT）
- `src/context_store/config.py:139-148` — Ingestion セクション（追加場所）
- `src/mcp_gateway/config.py:32-86` — GatewaySettings
- `src/mcp_gateway/config.py:67-72` — `upstream_env_passthrough` のデフォルトリスト（`CHRONOS_INGESTION_MODE` 追加対象）
- `src/mcp_gateway/config.py:81` — `max_request_body_size_bytes`（既定 10 MiB、フックの切り詰め上限の根拠）
- `src/mcp_gateway/upstream/context_store_client.py:3-4` — クロスパッケージ import 禁止のアーキ原則
- `src/mcp_gateway/upstream/context_store_client.py:26-29` — `build_upstream_env` allowlist 実装
- `src/mcp_gateway/tools/registry.py:1-21` — ToolRegistry（拡張対象）
- `src/mcp_gateway/app.py:100-108` — context_store subprocess 起動
- `src/mcp_gateway/app.py:110-124` — ToolRegistry 構築箇所
- `src/mcp_gateway/server.py:207-209` — tools/list ハンドラ
- `src/context_store/ingestion/classifier.py:22-24` — FALLBACK_PENALTY 定数
- `src/context_store/server.py:147-195` — memory_save / memory_save_url 実装
- `pyproject.toml` — `[tool.hatch.build.targets.wheel].packages` への `"src/chronos_shared"` 追加
