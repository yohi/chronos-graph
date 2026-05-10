# ChronosGraph Universal Evaluator (ccgate 代替機構) — 将来構想と設計書

- 作成日: 2026-05-10
- 対象: `src/mcp_gateway/` およびエージェントの Hook システム

## 1. 背景と目的

現在の ChronosGraph MCP Gateway は、サーバー側でプロトコル（JSON-RPC）を透過的にインターセプトする形で Permission Hook を実現しています。これにより、`memory_delete` などの MCP ツールに対してはクライアント側の複雑な Hook 設定なしにガードレールを提供できています。

しかし、「ChronosGraph の強力なポリシーエンジン（`intents.yaml` と Semantic Guardrails）を、MCP ツールだけでなく、エージェントが実行する**すべてのローカルツール（`bash`, `write_file`, `replace` 等）の評価にも適用したい**」という高度なユースケース（LayerX 社の `ccgate` の完全な代替としての利用）には現在対応していません。

本ドキュメントは、ChronosGraph を **「エージェントのクライアント側フックから呼び出される汎用的な評価CLI（Universal Evaluator）」** として機能させるための将来構想と実装ロードマップを定義します。これにより、別のセッションですぐにこの思想を引き継いで実装を開始できます。

## 2. アーキテクチャ構想

```text
┌────────────────────────────────────────────────────────┐
│  AI Agent (Claude Code / Gemini CLI / OpenCode)        │
│                                                        │
│  [PreToolUse Hook]                                     │
│  ツール実行要求: `bash` (args: "rm -rf /")             │
│         │                                              │
│         ▼ (spawn process)                              │
│  $ python -m mcp_gateway evaluate --tool bash \        │
│      --args '{"command": "rm -rf /"}'                  │
└─────────┼──────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────────┐
│  ChronosGraph Gateway CLI                              │
│                                                        │
│  1. `intents.yaml` をロード                            │
│  2. PolicyEngine で `bash` と引数を評価                │
│     - Regex パターン、許容値、禁止フラグの検証         │
│  3. 評価結果を出力                                     │
│     - 許可: exit code 0                                │
│     - 拒否: exit code 2 + stderr に拒否理由            │
└────────────────────────────────────────────────────────┘
```

## 3. 必要な機能追加・修正

### 3.1 CLI 評価エンドポイントの実装
`src/mcp_gateway/__main__.py` を拡張（または `evaluate.py` の追加）し、サーバーを起動せずに単発の評価スクリプトとして機能する CLI インターフェースを実装します。

**想定インターフェース:**
```bash
python -m mcp_gateway evaluate \
    --intent "default" \
    --tool "bash" \
    --args '{"command": "rm -rf /"}' \
    --policy-path "src/mcp_gateway/policies/intents.yaml"
```

**仕様:**
- 内部で `PolicyEngine.evaluate_call()` を呼び出す。
- `status == "ALLOW"` の場合は `exit 0` を返す。
- `status == "DENY"` の場合は、拒否理由を `stderr` に出力し、フックをブロックするための `exit 2`（または指定のコード）を返す。
- 高速に実行・終了すること（ミリ秒単位）。重いモジュール（FastAPI等）のインポートを回避する設計が望ましい。

### 3.2 Policy Engine と `intents.yaml` の拡張
現在、`intents.yaml` は「ChronosGraph の MCP ツール」の保護を前提としています。これをローカルツールにも適用できるよう、外部ツール用のガードレール定義ブロックを許容する（または検証の制約を緩める）必要があります。

**`intents.example.yaml` 拡張例:**
```yaml
intents:
  local_development:
    description: "ローカル環境での一般的な開発作業"
    allowed_tools: ["bash", "write_file", "replace", "memory_save"]
    guardrails:
      bash:
        params:
          command:
            type: string
            max_length: 2000
            pattern: "^(?!.*rm -rf).*$" # 危険なコマンドの簡易ブロック
            # 注記: 正規表現のみによるガードレールは回避が容易なため、実運用では
            # AST 解析や許可リスト方式など、より厳密な検証ロジックへの置き換えを推奨。
            
      write_file:
        params:
          file_path:
            type: string
            pattern: "^(?!.*\\.env).*$" # シークレットファイルへの書き込み禁止
            # 注記: 大文字小文字の差異や相対パス指定によるバイパスに注意。
```

### 3.3 クライアント側のフック設定の公式サポート

CLI が実装された後、各エージェントの設定ファイル（`settings.json` など）で ChronosGraph の評価コマンドを呼び出す方法を公式にドキュメント化します。

#### Claude Code (`.claude/settings.json`)
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --directory /path/to/chronos-graph python -m mcp_gateway evaluate --tool \"$CLAUDE_TOOL_NAME\" --args \"$CLAUDE_TOOL_ARGS\""
          }
        ]
      }
    ]
  }
}
```

#### Gemini CLI (`.gemini/settings.json`)
Gemini CLI は stdin/stdout を用いた JSON ベースのやり取りを好むため、CLI 側に `--json-io` モード（標準入力から JSON を受け取り、`{"decision": "deny", "reason": "..."}` を標準出力に返すモード）を追加すると親和性が高まります。

```json
{
  "hooks": {
    "BeforeTool": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "name": "chronos-gate",
            "type": "command",
            "command": "uv run --directory /path/to/chronos-graph python -m mcp_gateway evaluate --json-io"
          }
        ]
      }
    ]
  }
}
```

## 4. 次期セッション向けの実装タスクリスト (Implementation Plan)

1. **[ ] Task 1: CLI エンドポイントの作成**
   - `src/mcp_gateway/cli.py` を新設し、`argparse` を用いて引数（tool, args, intent）を受け取るロジックを実装。
   - `__main__.py` のルーティングを調整し、`python -m mcp_gateway evaluate ...` で呼び出せるようにする。
   - 高速起動のため、`app.py` などの不要なインポートが評価時に走らないよう最適化する。

2. **[ ] Task 2: PolicyEngine の検証**
   - 既存の `PolicyEngine` が MCP 以外のツール名（`bash` など）を受け取っても正常に `Guardrail` を評価・適用できるか単体テストを作成し、必要に応じて修正する。

3. **[ ] Task 3: JSON I/O モードの実装（Gemini CLI 向け）**
   - `--json-io` フラグが渡された場合、標準入力からツールのコンテキストを読み取り、評価結果を標準出力に JSON 形式で返すロジックを実装。

4. **[ ] Task 4: E2E テストの追加**
   - サブプロセスとして `python -m mcp_gateway evaluate` を実行し、許可されるケースで exit 0、ブロックされるケースで exit 2 が返ることを検証するテストを `tests/integration/` に追加。

5. **[ ] Task 5: ドキュメントの更新**
   - `README.md` に「Universal Evaluator (ccgate代替モード)」のセクションを新設し、各クライアントの設定例を記載する。設定例を記載する。