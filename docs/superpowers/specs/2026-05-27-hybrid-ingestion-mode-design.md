# Hybrid Ingestion Mode — 設計書

- **ID**: 2026-05-27-hybrid-ingestion-mode-design
- **Status**: Implemented
- **Owner**: ChronosGraph maintainers
- **Last updated**: 2026-05-29 (JST)

## 1. 概要

ChronosGraph の長期記憶への取り込み (ingestion) を、AI エージェントの **自律判断によるツール呼び出し** に依存する従来モードに加え、**ターン終了時の全量自動保存** を選択できるハイブリッド構成として再設計する。
本機能は環境変数 `CHRONOS_INGESTION_MODE` 1 つで切り替わり、以下の 2 値を取る。

| 値 | 主体 | 動作 |
|---|---|---|
| `selective` (既定) | AI エージェント | エージェントが自律判断で `memory_save` ツールを呼び出す |
| `all` | クライアント側 hook | ターン終了時に会話ログ全量をバックグラウンドで保存。`memory_save` ツールはエージェントから不可視化される |

## 2. 動機

`selective` モードでは、AI エージェントが「保存する価値がある」と判断したものだけが残る。一方で次の問題がある:

- **取りこぼし**: AI が見落とした重要発言が永遠に失われる。
- **トークン消費**: AI に保存判断させるため、実装の都度プロンプトに長い指示を入れる必要がある。
- **重複保存**: AI が同じ事実を別表現で繰り返し保存しがち。

`all` モードはこれらのトレードオフを解消するために導入された。

## 3. アーキテクチャ

### 3.1 トポロジ

```text
┌──────────────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code / Codex / Cursor / Antigravity / OpenCode) │
│   ┌─────────────────────────────────────────────────────┐         │
│   │ ターン実行 → 終了時に Stop / session.idle 等が発火     │         │
│   └────────────────────┬────────────────────────────────┘         │
│                        │ stdin: 会話ログ or hook payload (JSON)    │
└────────────────────────┼─────────────────────────────────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  scripts/agent_turn_hook.py (フェイルソフトの薄い HTTP クライアント)│
│   1. extract_payload: --client 値に応じて payload から会話ログ抽出  │
│   2. truncate_log: 末尾保持で 8MB に切り詰め (UTF-8 境界対応)       │
│   3. SSE handshake → session_id 取得 (timeout=1.0s)              │
│   4. POST /messages → tools/call memory_save (timeout=2.0s)      │
│   5. いかなるエラーも握りつぶし exit 0                              │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP (Bearer + x-mcp-intent: memory.ingest)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  mcp_gateway (FastAPI)                                            │
│   - tools/list 応答: ingestion_mode == "all" なら memory_save を隠蔽│
│   - 起動時 WARNING: 設定漏れ早期発見のため stderr に出力             │
│   - upstream_env_passthrough で CHRONOS_INGESTION_MODE を子プロセスへ│
└────────────────────────┬─────────────────────────────────────────┘
                         │ stdio (MCP)
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  context_store (FastMCP サブプロセス)                              │
│   - session_flush ツールが BatchProcessor で非同期処理              │
│   - Chunker → Classifier → Embedding → Deduplicator → Storage    │
│   - Fire-and-forget: 即座に {"status":"accepted"} を返す           │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 設定 SSOT

`CHRONOS_INGESTION_MODE` の型・デフォルト値・変数名は、クロスパッケージ参照を防ぐため独立した
`src/chronos_shared/ingestion_mode.py` に集約する。

```python
IngestionMode = Literal["all", "selective"]
DEFAULT_INGESTION_MODE: Final[IngestionMode] = "selective"
CHRONOS_INGESTION_MODE_ENV: Final[str] = "CHRONOS_INGESTION_MODE"
```

`mcp_gateway` と `context_store` の双方からこのモジュールのみを import する。
これは `mcp_gateway/upstream/context_store_client.py` の「the gateway must NOT import anything from `context_store`」というトポロジ規則と整合する。

### 3.3 環境変数の伝播

Gateway の `GatewaySettings.upstream_env_passthrough` のデフォルトに `CHRONOS_INGESTION_MODE_ENV` が含まれており、
Gateway 起動時に子プロセスの context_store にも同じ値が伝わる。
allowlist 方式 (`build_upstream_env`) により、Secrets が `os.environ` 継承で漏れることはない。

## 4. 実装コンポーネント

### 4.1 `mcp_gateway/app.py` の隠蔽ロジック

```python
if settings.ingestion_mode == "all":
    hidden_tools: frozenset[str] = frozenset({"memory_save"})
    logging.getLogger(__name__).warning(
        "ingestion mode: all - 'memory_save' tool is HIDDEN from agents. "
        "Client-side hook (e.g. scripts/agent_turn_hook.py via Stop event) "
        "MUST be configured to send conversation logs at turn end. "
        "See README.md §Hybrid Ingestion Mode for client-specific setup."
    )
else:
    hidden_tools = frozenset()
registry = ToolRegistry(initial_tools or [], hidden_tools=hidden_tools)
```

### 4.2 `mcp_gateway/tools/registry.py` のフィルタ

`ToolRegistry.all_tools` は `hidden_tools` に含まれるツール名を物理的に応答から除外する。
`tools/list` 応答時にエージェントから `memory_save` の存在自体が見えなくなる。

### 4.3 `scripts/agent_turn_hook.py` のクライアントアダプタ

`--client` 引数で payload 形式を切り替える。サポート値は次の通り:

| `--client` 値 | 解釈 |
|---|---|
| `raw` (既定) | stdin の生テキストをそのまま送信 |
| `claude-code` | stdin の JSON から `transcript_path` を読み、JSONL transcript を整形 |
| `codex` | 同上 (Claude Code 互換) |
| `cursor` | 同上 (Claude Code 互換) |
| `antigravity` | stdin の JSON から `transcriptPath` (キャメルケース) も解釈 |

`OpenCode` は plugin 機構で会話ログを直接抽出して `agent_turn_hook.py --content "..."` を spawn するため、`--client` には対応しない (raw でよい)。

### 4.4 純関数群 (テスト容易性)

- `truncate_log(content, max_bytes) -> (str, bool)` — UTF-8 境界対応の末尾保持切り詰め
- `format_transcript_messages(messages) -> str` — JSONL messages を `Role: text` 形式に整形
- `read_jsonl_transcript(path) -> str` — JSONL ファイル読み込み + 整形
- `extract_payload(client, raw) -> str` — クライアント別 payload 解釈

## 5. クライアント別 hook 設定例

### 5.1 Claude Code (`~/.claude/settings.json` または `.claude/settings.json`)

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python ${CLAUDE_PROJECT_DIR}/scripts/agent_turn_hook.py --client claude-code &"
          }
        ]
      }
    ]
  }
}
```

Claude Code は `Stop` event の payload に `transcript_path` (JSONL ファイルへのパス) を含めて stdin に渡す。
`--client claude-code` がこれを解釈する。

### 5.2 Codex CLI (`hooks.json` または `config.toml` の `[hooks]`)

Codex は Claude Code 互換の hook 仕様を採用しているため、Claude Code とほぼ同じ設定を `hooks.json` に書く。
`/hooks` コマンドで信頼レビュー (trust) を完了させる必要がある。

### 5.3 Cursor (`.cursor/hooks.json`)

Cursor は Claude Code 形式の `.claude/settings.json` も読めるため、両方の方式が使える。

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "python ./scripts/agent_turn_hook.py --client cursor &"
      }
    ]
  }
}
```

Cursor は stdin に Claude Code 互換の JSON payload を渡す。

### 5.4 Antigravity CLI (`.agents/hooks.json` または `~/.gemini/config/hooks.json`)

```json
{
  "chronos-ingestion": {
    "Stop": [
      {
        "type": "command",
        "command": "python ./scripts/agent_turn_hook.py --client antigravity &",
        "timeout": 5
      }
    ]
  }
}
```

Antigravity は payload に `transcriptPath` (キャメルケース) を含める。

### 5.5 OpenCode (`.opencode/plugins/chronos-turn-end.ts`)

OpenCode は hook ではなく **TypeScript プラグイン** で `session.idle` イベントを購読する。
プラグインから子プロセスを spawn して `agent_turn_hook.py --content "..."` を呼ぶ。

```typescript
import { spawn } from "node:child_process";

export const ChronosTurnEnd = async ({ client }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;
      // OpenCode SDK で会話履歴を取得
      const messages = await client.session.messages.list({ path: { id: sessionId } });
      const text = messages.data
        .map((m) => `${m.role}: ${(m.parts ?? [])
          .map((p) => p.type === "text" ? p.text : "")
          .filter(Boolean)
          .join("\n")}`)
        .join("\n\n");
      // fire-and-forget で agent_turn_hook.py を起動
      const child = spawn("python", [
        "scripts/agent_turn_hook.py",
        "--content", text,
      ], { detached: true, stdio: "ignore" });
      child.unref();
    },
  };
};
```

## 6. フェイルソフト多層化

| 層 | 失敗対応 |
|---|---|
| クライアント hook | プロセス spawn 失敗は無視 (各クライアントの責務) |
| `agent_turn_hook.py` | 全例外 catch + `exit 0` でメインプロセスクラッシュ防止 |
| Gateway HTTP | 4xx は warning ログ、5xx も握りつぶす |
| context_store ingestion | 分類失敗は EPISODIC + `FALLBACK_PENALTY=0.5` で救済 |
| シャットダウン | 進行中ジョブは `cancel_all` で強制終了 (ロス受容) |

## 7. ノイズ抑制

`all` モードでは相槌や空返事も保存される。これを検索結果から自然に下げるために:

1. **Classifier フォールバック**: 分類できなかった memory は EPISODIC として保存し、`importance_score *= 0.5` (FALLBACK_PENALTY) を適用。
2. **Deduplicator**: `dedup_threshold=0.90` で類似メモリは SUPERSEDES エッジで統合される。
3. **Lifecycle Decay**: 半減期 30 日のデフォルトでアクセスされない記憶は自動的にスコアが減衰する。

## 8. 観測性

- Gateway 起動時 stderr に `ingestion mode: all - ...` の WARNING を出力 (設定漏れ早期発見)。
- `agent_turn_hook.py` は LOG_LEVEL 環境変数で出力レベル調整可能 (DEBUG/INFO/WARNING/ERROR/CRITICAL)。
- 切り詰め発生時は `payload truncated: original=N bytes, sent=M bytes` の WARNING を出力。
- 413 Payload Too Large 時は `MCP_HOOK_MAX_LOG_BYTES` の見直しを促す WARNING。

## 9. 制限と注意

1. **MCP_GATEWAY_API_KEY 未設定時** はフックが no-op (stderr に ERROR ログのみ)。
2. **シャットダウン中の取り込みは保証されない** — `TaskRegistry.cancel_all` により進行中ジョブは未保存のまま消える。
3. **DB 容量増加** — 全ターンを保存するため `selective` より明確に増える。`purge_retention_days` で運用カバー。
4. **マルチプロセス並行制限の限界** — `URL_FETCH_CONCURRENCY` 等のセマフォはプロセス内のみ。複数 Gateway 並走時はシステム全体での真の制限にはならない。
5. **Codex の trust レビュー** — Codex は新しい hook を初回 `/hooks` レビュー後にしか実行しない。

## 10. 関連ファイル

- `src/chronos_shared/ingestion_mode.py` — 設定 SSOT
- `src/mcp_gateway/app.py` — 隠蔽ロジック + 起動時警告
- `src/mcp_gateway/config.py` — `GatewaySettings.upstream_env_passthrough`
- `src/mcp_gateway/tools/registry.py` — `hidden_tools` フィルタ
- `src/mcp_gateway/upstream/context_store_client.py` — `build_upstream_env` (allowlist)
- `src/context_store/config.py` — `Settings.ingestion_mode` (子プロセス側)
- `src/context_store/orchestrator.py` — `session_flush` (Fire-and-forget 受信)
- `scripts/agent_turn_hook.py` — クライアント側 hook 本体
- `tests/unit/test_chronos_shared_ingestion_mode.py` — SSOT 契約検証
- `tests/unit/test_settings_ingestion_mode.py` — 両 Settings の env passthrough 検証
- `tests/unit/test_build_app_hidden_tools.py` — `all` モード時の隠蔽 + 起動警告検証
- `tests/unit/test_agent_turn_hook_truncate.py` — 切り詰め純関数の検証
- `tests/unit/test_agent_turn_hook_payload_adapter.py` — payload adapter 純関数の検証

## 11. 受け入れ基準 (AC)

| ID | 内容 | 検証 |
|---|---|---|
| AC-1 | `CHRONOS_INGESTION_MODE` 未設定時のデフォルトは `selective` | `test_chronos_shared_ingestion_mode.py::test_default_ingestion_mode_is_selective` |
| AC-2 | `IngestionMode` Literal は `"all"` `"selective"` の 2 値のみ | `test_chronos_shared_ingestion_mode.py::test_ingestion_mode_literal_has_exactly_two_values` |
| AC-3 | `all` モード時に `memory_save` が `tools/list` から消える | `test_build_app_hidden_tools.py::test_all_mode_hides_memory_save` |
| AC-4 | `selective` モード時は `memory_save` が見える | `test_build_app_hidden_tools.py::test_selective_mode_does_not_hide_memory_save` |
| AC-5 | `replace_tools` 後も `hidden_tools` が維持される | `test_build_app_hidden_tools.py::test_hidden_tools_persists_after_replace` |
| AC-6 | `all` モード起動時に WARNING ログが stderr に出る | `test_build_app_hidden_tools.py::test_all_mode_emits_setup_warning` (新規) |
| AC-7 | hook の payload 切り詰めは UTF-8 境界を尊重する | `test_agent_turn_hook_truncate.py::test_truncate_log_multibyte_utf8_does_not_corrupt` |
| AC-8 | `--client claude-code` で transcript_path が解釈される | `test_agent_turn_hook_payload_adapter.py::test_extract_payload_claude_code_reads_transcript` (新規) |
| AC-9 | `--client antigravity` で transcriptPath (キャメル) が解釈される | `test_agent_turn_hook_payload_adapter.py::test_extract_payload_antigravity_camelcase` (新規) |
| AC-10 | Gateway → context_store の env passthrough に `CHRONOS_INGESTION_MODE` が含まれる | `test_settings_ingestion_mode.py::test_gateway_upstream_passthrough_includes_ingestion_mode` |
| AC-11 | `--client` 不正値はargparseでエラーになる | `test_agent_turn_hook_payload_adapter.py::test_invalid_client_rejected` (新規) |
| AC-12 | JSON パース失敗時は raw を返してフェイルソフト | `test_agent_turn_hook_payload_adapter.py::test_extract_payload_invalid_json_falls_back_to_raw` (新規) |
