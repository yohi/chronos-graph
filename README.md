# ChronosGraph 🚀

**MCP-based Long-Term Memory System for AI Agents**

---

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGraph は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）にセッションを跨いだ**永続的な長期記憶**を提供する Model Context Protocol (MCP) サーバーです。

## 核心的なアプローチ

1. **多層記憶グラフ (MAGMA):** 情報を単なるベクトルとして保存するのではなく、時間軸を伴うグラフ構造として保持。[📜 Episodic]（経験）・[🧠 Semantic]（知識）・[🕒 Procedural]（手順）の変遷を正確に追跡します。
2. **動的忘却アルゴリズム:** 指数関数的な減衰モデルと重要度評価により、記憶の肥大化を防ぎつつ、重要な教訓を「意味記憶」として抽出します。
3. **RL 拡張ポイント:** 将来の強化学習（PPO 等）統合に向けたインターフェースを設計。ユーザーとの対話を通じたエージェントの行動論理の継続的アップデートを可能にします。

---

## ⚙️ セットアップ (Setup)

### 👥 For Humans (人間用セットアップ)

> [!TIP]
> **人間は設定を打ち間違えることがあります。** このプロジェクトのインストールと設定は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）に丸投げすることを強く推奨します。以下のプロンプトをコピーして貼り付けてください。
> *※実際にファイルを変更せずに構成や手順だけを確認したい（デバッグしたい）場合は、プロンプトの最後に「デバッグモード（Dry-run）で実行してください」と書き添えてください。*

```text
Install and configure ChronosGraph by following the instructions here:
https://raw.githubusercontent.com/yohi/chronos-graph/refs/heads/master/README.md
```

---

### 🤖 AIエージェント向け自動セットアップ（Agent Setup Protocol）

AIエージェントにセットアップを依頼する場合の詳細な手順と制約は、[Agent Setup Protocol](docs/agent-setup-protocol.md) を参照してください。


## 🧠 Agent Identity & Memory Protocol

本プロジェクトでは、セットアップ完了後、各AIエージェントが使用する `AGENTS.md` や `.cursorrules` などの指示ファイルに対して、エージェントが長期記憶システムを自律運用するためのプロンプトを追記する運用を想定しています。

> [!NOTE]
> **追記の必要性について**:
> - **【ケース A】長期記憶サーバーの場合**: **必須**です。エージェントが自律的に記憶を保存（`memory_save`）するための指示が必要です。
> - **【ケース B】Hook (安全評価器) のみの場合**: **原則不要**です。Hook は透明な防壁として機能するため、エージェント側での意識的な対応は必要ありません。

追記すべきプロンプトの原本（テンプレート）は以下に格納されています。セットアップ完了時にこの内容を対象プロジェクトの `AGENTS.md` 等に追記してください。

👉 **[Memory Ingestion Prompt Template](docs/agent-prompts/memory-save-system-prompt.md)**


---

## ⚡ 特徴

- **ハイブリッド検索** — ベクトル検索 + キーワード検索 + グラフ結果を RRF で融合（グラフ有効時）
- **自動マイグレーション** — SQLite / PostgreSQL 両対応の SQL ベース軽量マイグレーション
- **多層記憶モデル** — [📜 Episodic] / [🧠 Semantic] / [🕒 Procedural] の自動分類
- **時間的減衰** — 指数関数的減衰スコアで古い記憶を整理（明示的な `memory_prune` は現行実装では SQLite バックエンドのみ実行）
- **重複排除** — Append-only 置換 + SUPERSEDES グラフエッジで変遷を追跡
- **ライトウェイトモード** — SQLite + sqlite-vec でゼロ設定で起動
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応、Supabase Data API による HTTPS 経由のアクセス（Supabase のグラフ機能は現時点で非対応）
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース
- **Dashboard Web UI** — Cytoscape.js グラフ可視化・リアルタイムログストリーミング（React + FastAPI、SQLite read-only 中心）

- **Universal Evaluator** — AIエージェントのツール呼び出しを deterministic + LLM の二層で判定する CLI (`PreToolUse` Hook 対応)

> [!NOTE]
> **現行実装上の注意**: `memory_search` の `memory_type` フィルタは API 互換性のため受け取りますが、検索結果にはまだ反映されません。`memory_search_graph` の `edge_types` / `depth` 指定も専用経路は未実装で、標準のハイブリッド検索へフォールバックします。

---

## Quick Start (uvx を使用する場合)

リポジトリをクローンせずに、`uvx` を使用して ChronosGraph を MCP サーバーとして即座にセットアップするための最小設定例です。

#### Claude Desktop 設定例

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) または `%APPDATA%\Claude\claude_desktop_config.json` (Windows) に以下の設定を追加します。

```json
{
  "mcpServers": {
    "chronos-graph": {
      "command": "uvx",
      "args": [
        "--from",
        "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git",
        "context-store"
      ],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "GRAPH_ENABLED": "true",
        "CACHE_BACKEND": "inmemory"
      }
    }
  }
}
```
*💡 **環境変数について**: この Quick Start は長期記憶 MCP サーバー (`context-store`) の最小例です。Universal Evaluator / Gateway を使う場合は、別途 `CHRONOS_EVALUATOR_API_KEY` や `MCP_GATEWAY_API_KEYS_JSON` などを設定してください。Claude Desktop は JSON 設定ファイル内の `${VAR}` 構文を展開しません。機密情報を渡す場合は、環境変数をエクスポートしてから起動するラッパースクリプトを指定することを推奨します。*

---

## マイグレーション (Migration)

### ベクトル次元数の変更 (1024 -> 768)

ChronosGraph の推奨埋め込みモデルの変更に伴い、デフォルトのベクトル次元数が **1024** から **768** に更新されました。以前のバージョンから移行する場合、次元不一致により `ConfigurationError` が発生します。

#### 1. データの再埋め込み (推奨)
既存の記憶を新しい 768 次元モデルで再計算します。
```bash
uv run python scripts/migrate_dimension.py
```

#### 2. ストレージスキーマの更新
> [!IMPORTANT]
> スキーマ変更を実行する前に、必ずデータベースのバックアップを取得し、必要に応じて `scripts/migrate_dimension.py` を検証してから実行してください。

**Supabase / PostgreSQL 用 SQL 例:**
```sql
-- memories テーブルのベクトルカラムを 768 次元の新しい定義に変更する
ALTER TABLE memories ALTER COLUMN embedding TYPE vector(768);

-- または、一度削除して再作成する場合（データが失われるため migrate_dimension.py 実行前に実施）
ALTER TABLE memories DROP COLUMN embedding;
ALTER TABLE memories ADD COLUMN embedding vector(768);
```

**SQLite 用の対応:**
SQLite では `ALTER COLUMN TYPE` がサポートされていないため、以下のいずれかの手順が必要です。
- **カラムの再作成:** `STORAGE_BACKEND=sqlite` を設定している場合、一度 `embedding` カラムを削除して再作成（`DROP/ADD`）するか、データベースをエクスポートしてから、新しい次元で `memories` テーブルを再作成してデータを移行してください。
- **移行手順:** テーブルを再作成（またはカラムを NULL で追加）した後、`scripts/migrate_dimension.py` を実行して再埋め込みを行ってください。

#### 3. エラーと対処
起動時に `ConfigurationError` や `StorageError` が発生した場合は、`.env` の `EMBEDDING_DIMENSION` がストレージ側の次元と一致しているか確認してください。

## 🛡️ Universal Evaluator (MCP Gateway)

エージェントの `PreToolUse` Hook から呼び出され、提案されたツール呼び出しを **deterministic（決定論的ポリシー: intents.yaml）** + **LLM（LiteLLM経由）** の二層で多面的に検証・判定する防壁 CLI です。

### 💡 AIエージェントへの Hook 設定方法 (Configuration)

Universal Evaluator は、ツール実行前フック（`PreToolUse` Hook）を持つ様々な AI エージェントとシームレスに連携できます。エージェント側でツールを提案した際、このフックを通して自動的に安全性が検証されます。

環境依存の絶対パスや認証用のAPIキーなどの機微情報は、**設定ファイルに直接書き込まず、各クライアントの環境変数ロード機能やシェルの環境変数**を利用して動的にロードできるように構成することが極めて推奨されます。

---

#### 📌 設定パターン A：Claude Code への MCP フック直接連携（推奨・最もシンプル）

Claude Code は MCP フックをネイティブにサポートしているため、**ラッパースクリプトを一切作成することなく**、すでにマウントされている MCP サーバー（例: `chronos-graph`）の `evaluate` ツールを直接指定できます。Antigravity CLI / Codex CLI / Cursor も同様の MCP フック記法をサポートしていますが、それぞれ設定パターン D / F / G に専用セクションがあります。

Claude Code の設定ファイル (`~/.claude/settings.json` または `.claude/settings.json`) に以下のように記述します。

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "mcp",
            "server": "chronos-graph",
            "tool": "evaluate"
          }
        ]
      }
    ]
  }
}
```

> [!TIP]
> **簡略表記について**: Antigravity CLI などの一部のエージェントでは、上記をさらに簡略化したオブジェクト形式（`"PreToolUse": { "mcp": { ... } }`）をサポートしている場合があります。環境のドキュメントに合わせて調整してください。

> [!CAUTION]
> **OpenCode の重要な制限**: JSON設定ファイル（`opencode.json`）での **`hooks` キーは未サポート** です。エージェントは **絶対に `hooks` を含む JSON を OpenCode 向けに生成してはいけません。** フックを実装するには、以下の **プラグイン形式** を参照して TypeScript/JavaScript プラグインを作成・登録してください。

#### 📌 設定パターン B：HTTP フックによるリモート連携

リモートサーバー側で `mcp_gateway` を稼働させている場合、**HTTP フック** 経由で一元管理されているリモートエンジンに直接リクエストを飛ばせます。APIキーやホストURLなどの認証情報・接続情報は、環境変数から動的にロードできるように構成します。

---

#### 📌 設定パターン C：OpenCode プラグイン形式による連携

OpenCode では、フック機能を **「プラグイン」** として拡張・ロードします。 Node.js プラグインを構成し、ツール実行前イベントにフックさせて `uvx` からオンザフライに `evaluate` を実行させます。

* **プラグインの JavaScript 実装例:**
  OpenCode では TypeScript/JavaScript プラグインとしてフックを実装します。

  ```javascript
  const { spawn } = require('child_process');
  const path = require('path');

  /**
   * OpenCode ツール実行前フック (tool.execute.before)
   * Universal Evaluator を呼び出し、実行の可否を判定します。
   */
  async function OnBeforeToolExecute(toolCall) {
    return new Promise((resolve, reject) => {
      // ポリシーファイル (intents.yaml) は設定ファイルと同じディレクトリを優先的に参照
      const defaultConfigDir = path.join(process.env.HOME || process.env.USERPROFILE, '.config', 'opencode');
      const policyPath = process.env.CHRONOS_EVALUATOR_POLICY_PATH || path.join(defaultConfigDir, 'intents.yaml');

      const proc = spawn('uvx', [
        '--quiet',
        '--from', 'context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git',
        'chronos-mcp-gateway', 'evaluate', '--json-io',
        '--policy-path', policyPath
      ]);

      proc.stdin.write(JSON.stringify(toolCall));
      proc.stdin.end();

      let output = '';
      proc.stdout.on('data', (data) => { output += data; });
      
      proc.on('close', (code) => {
        if (code !== 0) return reject(new Error('Evaluation failed'));
        const result = JSON.parse(output);
        
        if (result.decision === 'allow') {
          resolve({ status: 'allow' });
        } else {
          resolve({ status: 'deny', reason: result.reason });
        }
      });
    });
  }
  ```

* **設定ファイル (`~/.config/opencode/opencode.json`) への登録:**
  作成したプラグインファイルをプロジェクト内の適切な場所に配置し、**`plugins`** キーを使用して登録します（`hooks` キーは使用しません）。
  ```json
  {
    "plugins": [
      {
        "name": "chronos-safety-gate",
        "path": "./.opencode/plugins/chronos-gate.js",
        "enabled": true
      }
    ]
  }
  ```

> [!CAUTION]
> **OpenCode の重要な制限**: **`hooks` キーは未サポート** です。エージェントは **絶対に `hooks` を含む JSON を OpenCode 向けに生成してはいけません。** また、設定の変更は新規作成ではなく、**`~/.config/opencode/opencode.json(c)`** の更新を行ってください。

---

#### 📌 設定パターン D：Antigravity CLI による連携

Antigravity CLI（本エージェント）の `hooks` セクションに記述することで、MCP フックまたは CLI コマンドワンライナー（クローン不要）のいずれかで保護を有効化できます。

##### 1. MCPフック経由での設定 (推奨)
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "mcp",
            "server": "chronos-graph",
            "tool": "evaluate"
          }
        ]
      }
    ]
  }
}
```

##### 2. コマンド直接指定による設定 (クローン不要・uvx 使用)
絶対パスの代わりに、シェル環境変数 `$CHRONOS_EVALUATOR_POLICY_PATH` から動的にポリシーをロードします。
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "uvx --quiet --from \"context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git\" chronos-mcp-gateway evaluate --json-io --policy-path \"$CHRONOS_EVALUATOR_POLICY_PATH\""
          }
        ]
      }
    ]
  }
}
```

---

#### 📌 設定パターン E：従来のラッパースクリプト方式

CLI 実行ファイルのパスしか指定できない環境では、共通のラッパースクリプト（例: `chronos-evaluator-hook.sh`）を作成して登録します。すべてのパスを環境変数経由でロードすることで、環境依存の絶対パスの直書きを完全に排除します。

##### 1. スクリプトの作成 (`chronos-evaluator-hook.sh`)

💡 **ポリシーファイル (`intents.yaml`) の配置ルール**:
- **原則（エージェント個別）**: 各エージェントの設定ファイル（例: `~/.config/opencode/`）と同じディレクトリに配置することを推奨します。
- **例外（グローバル/共有）**: `uvx` やリモート実行等で共通のポリシーを使用したい場合は、`$HOME/.config/chronos/intents.yaml` を共有の場所として使用してください。

* **📦 推奨：クローン不要版 (uvx を使用)**
  ```bash
  #!/usr/bin/env bash
  # chronos-evaluator-hook.sh (クローン不要版)
  uvx --quiet --from "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git" \
    chronos-mcp-gateway evaluate \
    --json-io \
    --policy-path "${CHRONOS_EVALUATOR_POLICY_PATH:-$HOME/.config/chronos/intents.yaml}"
  ```

* **📁 ローカル実行版 (クローン済みリポジトリを使用)**
  ```bash
  #!/usr/bin/env bash
  # chronos-evaluator-hook.sh (ローカル実行版)
  uv --directory "${CHRONOS_REPO_PATH:-$HOME/chronos-graph}" run python -m mcp_gateway evaluate \
    --json-io \
    --policy-path "${CHRONOS_EVALUATOR_POLICY_PATH:-$HOME/chronos-graph/src/mcp_gateway/policies/intents.yaml}"
  ```
  *(※スクリプト作成後、`chmod +x chronos-evaluator-hook.sh` で実行権限を付与してください)*

##### 2. エージェント側でのフック登録
OpenCode 等の設定で、ラッパースクリプトへの絶対パスを環境変数からロードして参照します。
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "{env:CHRONOS_HOOK_PATH}/chronos-evaluator-hook.sh"
          }
        ]
      }
    ]
  }
}
```

---

#### 📌 設定パターン F：Codex CLI への連携

Codex CLI は Claude Code 互換の hook 仕様を採用しており、`PreToolUse` イベントで `evaluate` ツールを直接呼び出せます。設定ファイルは `~/.codex/hooks.json` または `~/.codex/config.toml` の `[hooks]` セクションを使用します。初回使用時は Codex の `/hooks` コマンドで信頼レビュー (trust) を完了させる必要があります。

##### 1. MCPフック経由での設定 (推奨)

**`hooks.json` 形式:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "mcp",
            "server": "chronos-graph",
            "tool": "evaluate"
          }
        ]
      }
    ]
  }
}
```

**`config.toml` 形式 (同等):**

```toml
[[hooks.PreToolUse]]
matcher = "*"

[[hooks.PreToolUse.hooks]]
type = "mcp"
server = "chronos-graph"
tool = "evaluate"
```

##### 2. コマンド直接指定 (クローン不要・`uvx` 使用)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "uvx --quiet --from \"context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git\" chronos-mcp-gateway evaluate --json-io --policy-path \"$CHRONOS_EVALUATOR_POLICY_PATH\""
          }
        ]
      }
    ]
  }
}
```

ポリシーファイル `intents.yaml` は `~/.codex/intents.yaml` への配置を推奨します。

---

#### 📌 設定パターン G：Cursor への連携

Cursor は **2 つの hook 経路** を提供します。新規プロジェクトでは **方式 1 (Cursor ネイティブ形式)** を、既存の Claude Code 設定を流用したい場合は **方式 2 (Claude Code 互換)** を選んでください。

##### 1. Cursor ネイティブ形式 (`.cursor/hooks.json`)

Cursor 独自の `preToolUse` (小文字) イベントを使います。コマンド直接指定の例:

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "command": "uvx --quiet --from \"context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git\" chronos-mcp-gateway evaluate --json-io --policy-path \"$CHRONOS_EVALUATOR_POLICY_PATH\""
      }
    ]
  }
}
```

ラッパースクリプトを使いたい場合は、**設定パターン E** の `chronos-evaluator-hook.sh` をそのまま流用できます。

##### 2. Claude Code 互換形式 (`.claude/settings.json`)

Cursor は Claude Code 形式の hook を自動的にマッピングします (`PreToolUse` → `preToolUse` など)。Claude Code と同じ設定ファイルを共有したい場合に有効です。**設定パターン A** の JSON をそのまま流用できます。

> [!NOTE]
> Cursor で `chronos-graph` を MCP サーバーとして登録する (`mcp.json`) だけでは PreToolUse hook は起動しません。`mcp.json` は MCP ツールを呼べる状態にするためのもので、自動的な安全評価には別途 `hooks.json` 等の登録が必要です。

ポリシーファイル `intents.yaml` は `.cursor/intents.yaml` への配置を推奨します。





### 起動ログの読み方

`CompositeEvaluator` は起動時に以下を stderr に WARNING で 1 行出力する:

```
evaluator config: llm=enabled memory=enabled fallback_when_llm_not_configured=ask
```

`llm=DISABLED` のときは LLM 評価が完全に無効化されている。`CHRONOS_EVALUATOR_FALLBACK=ask` 設定下では Tier 1 ALLOW でも常に `ask` 判定が返るため、運用者は必ず確認すること。

### 高リスクツール群の hook 構成 (推奨)

機微情報マスキングはキー名ベースのため、`bash` / `curl` / `Write` / `Edit` 等で **値の内部に埋め込まれた秘密** は検出できない。以下のいずれかを必ず適用する:

1. **hook 対象から除外**: クライアント側 `matcher` で対象外にする
2. **前段マスキング hook**: AST 解析 / URL parse / 正規表現スキャンで先にサニタイズ
3. **ツール側で秘密検出**: `truffleHog` / `gitleaks` 等で実行前に拒否

### Devcontainer 内チェック

```bash
# (ホスト) Devcontainer を開く
$ code .       # 「Reopen in Container」を選択
# (Devcontainer 内)
$ bash scripts/check_evaluator.sh
```

devcontainer CLI 利用時は以下のいずれか:

- `.devcontainer/docker-compose.yml` が設定する `DEVCONTAINER=1` を利用
- もしくは手動で `export DEVCONTAINER=1`

---

## 設定リファレンス (環境変数一覧)

ChronosGraph 本体およびセキュリティ判定エンジン（Universal Evaluator）で利用する環境変数の一覧です。

### 1. ChronosGraph コア・ストレージ設定

| 環境変数 | デフォルト | 推奨・必須区分 | 説明 |
|---|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | デフォルト可 | ストレージバックエンド (`sqlite` / `postgres` / `supabase`) |
| `SUPABASE_URL` | `""` | **[Supabase用]** 設定必須 | Supabase プロジェクト URL |
| `SUPABASE_KEY` | `""` | **[Supabase用]** 設定必須 | Supabase Service Role Key (機密情報のため厳重管理) |
| `SUPABASE_REQUEST_TIMEOUT_SECONDS` | `10.0` | デフォルト可 | **[Supabase用]** Supabase Data API 呼び出しのタイムアウト秒数 |
| `EMBEDDING_PROVIDER` | `local-model` | デフォルト可 | 埋め込みプロバイダー (`local-model` / `openai` / `litellm`) |
| `LOCAL_MODEL_NAME` | `cl-nagoya/ruri-v3-310m` | デフォルト可 | ローカルモデル名 (768次元) |
| `EMBEDDING_DIMENSION` | `768` | デフォルト可 | 埋め込みベクトル次元数 (例: 768) |
| `GRAPH_ENABLED` | `false` | デフォルト可 | グラフ関係性機能の有効化。SQLite では内部グラフ、PostgreSQL では Neo4j を使用。Supabase では非対応 |
| `CACHE_BACKEND` | `inmemory` | デフォルト可 | キャッシュバックエンド (`inmemory` / `redis`) |
| `REDIS_URL` | `redis://localhost:6379` | **[Redis用]** 設定必須 | Redis 接続 URL。`CACHE_BACKEND=redis` のときのみ使用し、接続失敗時の暗黙フォールバックは行いません |

### 2. ツール実行前安全評価器 (Universal Evaluator) 設定

| 環境変数 | デフォルト | 推奨設定 | 説明 |
|---|---|---|---|
| `CHRONOS_EVALUATOR_API_KEY` | 未設定 | **LLM使用時必須** | 未設定なら LLM 評価をスキップ。LiteLLM 経由で任意プロバイダの API キーを設定 |
| `CHRONOS_EVALUATOR_MODEL` | `anthropic/claude-haiku-4-5-20251001` | デフォルト可 | LiteLLM model identifier (例: `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku-20241022` のように完全な識別子を指定) |
| `CHRONOS_EVALUATOR_MAX_TOKENS` | `1536` | デフォルト可 | 出力 token 上限。不正値・非正値は警告 + デフォルトへフォールバック (fail-soft) |
| `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` | `10.0` | デフォルト可 | LLM タイムアウト。不正値・非正値は警告 + デフォルトへフォールバック (fail-soft) |
| `CHRONOS_EVALUATOR_FALLBACK` | `allow` | **`ask` を強く推奨** | LLM 未構成時の挙動。未設定時のリスク防止のため、本番環境では `ask` 推奨 |
| `CHRONOS_EVALUATOR_POLICY_PATH` | (必須) | **設定必須** | intents.yaml のパス |
| `CHRONOS_EVALUATOR_DEFAULT_INTENT` | `default` | 環境次第 | intent 未指定時の既定 |
| `CHRONOS_EVALUATOR_DEFAULT_AGENT_ID` | `claude-code` | 環境次第 | agent_id 未指定時の既定 |
| `CHRONOS_EVALUATOR_LOG_LEVEL` | `WARNING` | デフォルト可 | stderr ログレベル |
| `CHRONOS_DASHBOARD_URL` | 未設定 | 任意（retrieval使用時） | 未設定なら memory 取得をスキップ (Universal Evaluator の retrieval base) |
| `CHRONOS_DASHBOARD_API_KEY` | 未設定 | **`--auth` 起動時必須** | dashboard 認証キー |

### 2.1 MCP Gateway / Turn-End Hook 設定

| 環境変数 | デフォルト | 推奨設定 | 説明 |
|---|---|---|---|
| `MCP_GATEWAY_API_KEYS_JSON` | 未設定 | Gateway 認証使用時必須 | Gateway サーバー側の API キーマップ。例: `{"claude-code":"raw-api-key"}` |
| `MCP_GATEWAY_API_KEY` | 未設定 | turn-end hook 使用時必須 | `agent_turn_hook.py` が Gateway へ送る Bearer 相当の API キー。`MCP_GATEWAY_API_KEYS_JSON` のいずれかの値と一致させる |
| `MCP_GATEWAY_URL` | `http://127.0.0.1:9100` | デフォルト可 | `agent_turn_hook.py` から到達する Gateway URL |

> ⚠️ **セキュリティ警告:** `CHRONOS_EVALUATOR_FALLBACK` のデフォルトは `allow` です。`CHRONOS_EVALUATOR_API_KEY` 未設定の環境でそのままデプロイすると、deterministic 判定が不明瞭なツール呼び出しも**自動的に許可**されます。本番環境では必ず `ask` に設定してください。
> 
> 🔄 **移行ノート (v2.x → v3.0):**
> - `ANTHROPIC_API_KEY` は使用しません。代わりに `CHRONOS_EVALUATOR_API_KEY` を設定してください。
> - `CHRONOS_EVALUATOR_THINKING_BUDGET` は削除されました。Anthropic Extended Thinking を使いたい場合は LiteLLM `extra_body` 経由で再構成してください（本リファクタのスコープ外）。
> - `CHRONOS_EVALUATOR_MAX_TOKENS` / `CHRONOS_EVALUATOR_TIMEOUT_SECONDS` の解釈 (不正値・非正値は警告 + デフォルト) は **v2.x と同一** です。設定バリデーション厳格化は別 PR で予定。

### 3. Ingestion & フック (Hybrid Ingestion Mode) 設定

| 環境変数 | デフォルト | 推奨設定 | 説明 |
|---|---|---|---|
| `CHRONOS_INGESTION_MODE` | `selective` | 運用次第 | `selective`: エージェント自律のツール呼び出しベース。<br>`all`: ターン毎の全量保存（`memory_save` ツールが隠蔽され見えなくなります） |
| `MCP_HOOK_TIMEOUT_SECONDS` | `2.0` | デフォルト可 | `agent_turn_hook.py` の全体ハードリミットタイムアウト（秒） |
| `MCP_HOOK_SSE_TIMEOUT_SECONDS` | `1.0` | デフォルト可 | `agent_turn_hook.py` の SSE ハンドシェイクタイムアウト（秒） |
| `MCP_HOOK_MAX_LOG_BYTES` | `8388608` (8MB) | デフォルト可 | フック経由送信の最大ログサイズ（超過時は末尾保持で切り詰め） |

**ターン終了フック (`agent_turn_hook.py`)**
`CHRONOS_INGESTION_MODE=all` 設定下において、エージェントのターン終了時に会話ログをバックグラウンドで（Fire-and-forget）保存するためのスクリプトです。いかなるエラー（タイムアウト・認証失敗・Gateway到達不可）が発生しても `exit 0` で終了し、メインのエージェントプロセスをクラッシュさせないフェイルソフト設計となっています。

```bash
echo "$CONVERSATION_LOG" | uv run python scripts/agent_turn_hook.py &
```

#### `CHRONOS_INGESTION_MODE=all` を選ぶ場合のクライアント別セットアップ

> [!WARNING]
> `CHRONOS_INGESTION_MODE=all` を **環境変数として設定するだけでは全量保存は機能しません。** Gateway 側ではエージェントから `memory_save` ツールを隠蔽するだけで、自動保存の経路はクライアント側 hook の責務です。Gateway 起動時には `ingestion mode: all - 'memory_save' tool is HIDDEN from agents. Client-side hook ... MUST be configured` という WARNING が stderr に出力されます。

**前提条件 (全クライアント共通)**

1. `MCP_GATEWAY_API_KEY` 環境変数を hook プロセスに渡す (未設定時は no-op)。
2. `MCP_GATEWAY_URL` を hook プロセスから到達可能にする (デフォルト `http://127.0.0.1:9100`)。
3. Gateway サーバー側の `MCP_GATEWAY_API_KEYS_JSON` に、hook 側の `MCP_GATEWAY_API_KEY` と一致する値を登録しておく。
4. Gateway のポリシーファイル (`intents.yaml`) で intent `memory.ingest` を許可しておく。
5. 以下の例はローカルリポジトリから実行する前提のため、`uv` が利用可能であること。

##### 🟦 Claude Code (`~/.claude/settings.json` または `.claude/settings.json`)

Claude Code の `Stop` event は `transcript_path` を含む JSON を stdin に渡します。`--client claude-code` がこれを自動解釈し、JSONL transcript を `User: ...` / `Assistant: ...` 形式に整形してからGateway に送信します。

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv --directory ${CLAUDE_PROJECT_DIR} run python scripts/agent_turn_hook.py --client claude-code &"
          }
        ]
      }
    ]
  }
}
```

##### 🟪 Codex CLI (`hooks.json` または `config.toml` の `[hooks]`)

Codex CLI は Claude Code 互換の hook 仕様を採用しています。設定例は Claude Code とほぼ同一で、`--client codex` を指定します。`/hooks` コマンドで初回信頼レビューを完了させる必要があります。

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run python scripts/agent_turn_hook.py --client codex &"
          }
        ]
      }
    ]
  }
}
```

##### 🟧 Cursor (`.cursor/hooks.json`)

Cursor 独自の小文字イベント名 (`stop`) を使います。Cursor は Claude Code 形式の `.claude/settings.json` も自動的に読むので、Claude Code と同一の `.claude/settings.json` を共有することも可能です。

```json
{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "uv run python scripts/agent_turn_hook.py --client cursor &"
      }
    ]
  }
}
```

##### 🟩 Antigravity CLI (`.agents/hooks.json` または `~/.gemini/config/hooks.json`)

Antigravity は payload に `transcriptPath` (キャメルケース) を含めます。`--client antigravity` がこれも解釈します。

```json
{
  "chronos-ingestion": {
    "Stop": [
      {
        "type": "command",
        "command": "uv run python scripts/agent_turn_hook.py --client antigravity &",
        "timeout": 5
      }
    ]
  }
}
```

##### 🟨 OpenCode (`.opencode/plugins/chronos-turn-end.ts`)

OpenCode は hook 機構を持たず、代わりに TypeScript プラグインで `session.idle` イベントを購読します。以下は概念例です。プラグイン側で会話履歴を取得し、子プロセスとして `agent_turn_hook.py --content "..."` を spawn します。

```typescript
import { spawn } from "node:child_process";
import path from "node:path";

export const ChronosTurnEnd = async ({ client, directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      const messages = await client.session.messages.list({ path: { id: sessionId } });
      const text = messages.data
        .map((m: any) => {
          const parts = (m.parts ?? [])
            .map((p: any) => p.type === "text" ? p.text : "")
            .filter(Boolean)
            .join("\n");
          return `${m.role}: ${parts}`;
        })
        .join("\n\n");

      const child = spawn("uv", ["--directory", directory, "run", "python", "scripts/agent_turn_hook.py", "--content", text], {
        detached: true,
        stdio: "ignore",
        env: { ...process.env },
      });
      child.unref();
    },
  };
};
```

##### 🔧 動作確認用の手動実行 (任意)

Hook を仕込まずに動作確認だけしたい場合は、生のテキストを stdin で渡します。

```bash
echo "User: hello\nAssistant: hi" | uv run python scripts/agent_turn_hook.py &
```

詳細仕様は [`docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md`](docs/superpowers/specs/2026-05-27-hybrid-ingestion-mode-design.md) を参照してください。


### 4. Phase 2: タイムアウト・遅延最適化 (Phase 2 Timeout & Latency Improvements)

MCP 経由のツール呼び出しや埋め込み API のハング・長期リトライを防止し、総レイテンシを予測可能に bound するための設定群です。設計背景は [SPEC.md §16.5](SPEC.md) を参照してください。

| 環境変数 | デフォルト | 範囲 / 上限 | 説明 |
|---|---|---|---|
| `MCP_GATEWAY_TOOL_TIMEOUT_SECONDS` | `30.0` | > 0 | **(D-1)** Upstream MCP ツール呼び出しのデフォルトタイムアウト秒数。`MCP_TOOL_TIMEOUT_SECONDS` を fallback 名として参照可。 |
| `MCP_GATEWAY_MAX_TOOL_TIMEOUT_SECONDS` | `300.0` | > 0 | **(D-1)** ツール固有タイムアウトを含めた絶対上限秒数。 |
| `MCP_GATEWAY_APPROVAL_TIMEOUT_SECONDS` | `30.0` | (0, 600] | **(D-3)** 人間承認の待機タイムアウト秒数。経過後は `approval_timeout` decision で fail-soft にクローズ。 |
| `CHUNK_PARALLEL_SEMAPHORE_SIZE` | `10` | > 0 | **(E-1)** Ingestion 並列モード (`GRAPH_ENABLED=false` 時) でのチャンク同時処理の最大同時実行数。 |
| `EMBEDDING_MAX_RETRIES` | `3` | > 0 | **(E-2)** OpenAI / LiteLLM 埋め込み API リトライの最大試行回数 (旧 5 → 3)。 |
| `EMBEDDING_MIN_WAIT` | `1.0` | > 0 | **(E-2)** 指数バックオフの最小待機秒数。 |
| `EMBEDDING_MAX_WAIT` | `10.0` | > 0 | **(E-2)** 指数バックオフの最大待機秒数 (旧 60s → 10s)。`Retry-After` ヘッダを尊重する際もこの値でクランプ。 |
| `EMBEDDING_PER_ATTEMPT_TIMEOUT` | `10.0` | > 0 | **(E-2)** 1 リトライ試行あたりの HTTP タイムアウト秒数。 |

> 💡 **レイテンシ設計:** Embedding API 経由の総レイテンシは **最大 ~50 秒** (3 試行 × 10s + 2 待機 × 10s) と見積もられます。これに対し MCP Gateway のデフォルトタイムアウトは 30s ですが、リトライが長期化する `memory_save_url` ツールには個別で 40s の上限が設定されています。最悪ケースでは Gateway 側が先にタイムアウトし fail-soft に処理を打ち切ることで、リソースの占有を防ぐ設計となっています。`CHUNK_PARALLEL_SEMAPHORE_SIZE` および `EMBEDDING_*` の不正値・非正値は警告ログ + デフォルト値へフォールバック (fail-soft) します。

**実装参照:**

- **D-1** Upstream timeout: [`src/mcp_gateway/upstream/timeout_client.py`](src/mcp_gateway/upstream/timeout_client.py) `TimeoutConfig`
- **D-3** Approval timeout: [`src/mcp_gateway/config.py`](src/mcp_gateway/config.py) `GatewaySettings.approval_timeout_seconds`
- **E-1** Chunk 並列化: [`src/context_store/ingestion/pipeline.py`](src/context_store/ingestion/pipeline.py) `CHUNK_PARALLEL_SEMAPHORE_SIZE`
- **E-2** Embedding retry: [`src/context_store/embedding/retry_config.py`](src/context_store/embedding/retry_config.py) `EmbeddingRetryPolicy`

### 💡 カスタムエンドポイント (ローカルLLM / vLLM / Azure 等) の設定

Universal Evaluator はバックエンドに [LiteLLM](https://github.com/BerriAI/litellm) を使用しています。そのため、専用の環境変数を追加しなくても、LiteLLM が標準でサポートする環境変数（`OPENAI_API_BASE` など）を利用してあらゆるカスタムエンドポイントにルーティングできます。

> 🔗 **対応プロバイダー一覧:** AWS, Azure, Google Vertex AI, Huggingface などを含む140以上のサポート対象プロバイダーと、それぞれの詳細なプレフィックス・環境変数設定については、公式の [LiteLLM Providers ドキュメント](https://docs.litellm.ai/docs/providers) をご参照ください。

**OpenAI 互換サーバー (vLLM, LM Studio など) の例:**
```bash
# LiteLLMのOpenAIプロバイダ用エンドポイントを上書き
OPENAI_API_BASE="http://localhost:8000/v1"

# ※LiteLLMがAuthorizationヘッダーを構築する際の内部チェックを通過するため、ダミーでもAPIキーの設定が必要です
CHRONOS_EVALUATOR_API_KEY="sk-dummy"

# openai/ プレフィックスをつけてモデルを指定
CHRONOS_EVALUATOR_MODEL="openai/meta-llama/Meta-Llama-3-8B-Instruct"
```

**Ollama の例:**
```bash
# デフォルト (http://localhost:11434) 以外を使用する場合に指定
OLLAMA_API_BASE="http://192.168.1.100:11434"

# ※LiteLLMがAuthorizationヘッダーを構築する際の内部チェックを通過するため、ダミーでもAPIキーの設定が必要です
CHRONOS_EVALUATOR_API_KEY="sk-dummy"
CHRONOS_EVALUATOR_MODEL="ollama/llama3"
```

---

## ライセンス

MIT License — [LICENSE](LICENSE)
