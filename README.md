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
Install and configure ChronosGraph by strictly following the Agent Setup Protocol in docs/agent-setup-protocol.md.
```

---

### 🤖 AIエージェント向け自動セットアップ（Agent Setup Protocol）

AIエージェントにセットアップを依頼する場合の詳細な手順と制約は、[Agent Setup Protocol](docs/agent-setup-protocol.md) を参照してください。
AIエージェントはユーザーに必要な設定事項を質問し、その結果を引数として `scripts/bootstrap.sh` に渡して機械的にセットアップを実行します。これにより、環境依存による設定のブレを防ぎます。

### OpenSandbox（テスト・静的解析サンドボックス）

AIエージェント（Gemini / OpenCode 等）が、テストや静的解析（ruff / mypy / tsc / eslint）を人間の Devcontainer から隔離されたセキュアで使い捨て（Ephemeral）なサンドボックス上で実行するための仕組みです。`scripts/sandbox_runner.py` がタスク種別からプロファイル（`lite` / `integration`）を自動判定し、依存インストール・実行・破棄のライフサイクルを管理します。

> [!NOTE]
> 設計・アーキテクチャの詳細は [SPEC.md §18](SPEC.md) を参照してください。

#### クイックスタート

```bash
# 1. Lite イメージをビルド
docker build -f .devcontainer/opensandbox/lite.Dockerfile -t chronos-graph-sandbox-lite:latest .

# 2. OpenSandbox サーバーを起動（sandbox プロファイル）
docker compose --profile sandbox up opensandbox -d

# 3. サンドボックス内で lint / テストを実行（プロファイルは自動判定）
python scripts/sandbox_runner.py -- uv run ruff check src/
python scripts/sandbox_runner.py -- uv run pytest tests/unit/ -v
python scripts/sandbox_runner.py --profile integration -- uv run pytest tests/integration/ -v

# フロントエンド（pnpm）
python scripts/sandbox_runner.py -- bash -c "cd frontend && pnpm install && pnpm lint"
```

> [!CAUTION]
> `docker compose --profile sandbox up` で起動する OpenSandbox サーバーは、サンドボックス用コンテナを作成するためにホストの Docker ソケット (`/var/run/docker.sock`) をマウントします。このマウントは Docker API への完全アクセスを許可するため、コンテナ内プロセスがホスト上のコンテナを起動・停止・削除でき、実質的にホスト権限へ昇格できるリスクがあります。このプロファイルは信頼できるローカル開発・デバッグ用途に限定し、未検証のイメージや共有環境では有効化しないでください。

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
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応、Supabase Data API による HTTPS 経由のアクセス（Supabase + Neo4j Aura は `async_outbox` モードにより解禁）
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース
- **Dashboard Web UI** — Cytoscape.js グラフ可視化・リアルタイムログストリーミング（React + FastAPI、SQLite read-only 中心）

- **ChronosGate 連携** — ツール実行前の安全評価は独立リポジトリ [ChronosGate](https://github.com/yohi/chronos-gate) として提供

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
*💡 **環境変数について**: この Quick Start は長期記憶 MCP サーバー (`context-store`) の最小構成例です。ツール実行前の安全評価を利用する場合は、独立リポジトリ [ChronosGate](https://github.com/yohi/chronos-gate) を追加セットアップしてください。また、Claude Desktop は JSON 設定ファイル内の `${VAR}` 構文を展開しません。機密情報を渡す場合は、環境変数をエクスポートしてから起動するラッパースクリプトを指定することを推奨します。*

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

<a id="universal-evaluator-mcp-gateway"></a>
## 🛡️ Universal Evaluator (ChronosGate)

ツール実行前のセキュリティ評価機能（Universal Evaluator）は、独立リポジトリ **[ChronosGate](https://github.com/yohi/chronos-gate)** として提供されています。

```bash
uv pip install "chronos-gate @ git+https://github.com/yohi/chronos-gate.git"
```

ChronosGate の詳細なセットアップ手順（CLI Hook、HTTP サーバー、OpenCode プラグイン）は、[chronos-gate/README.md](https://github.com/yohi/chronos-gate/blob/master/README.md) を参照してください。

ChronosGraph 本体は長期記憶サーバーとして動作し、ChronosGate からのメモリ検索リクエスト（`POST /api/memories/semantic-search`）に応答します。

---

## 設定リファレンス (環境変数一覧)

ChronosGraph 本体で利用する環境変数の一覧です。ツール実行前安全評価（Universal Evaluator / ChronosGate）の環境変数は [ChronosGate](https://github.com/yohi/chronos-gate) 側の README を参照してください。

### 1. ChronosGraph コア・ストレージ設定

| 環境変数 | デフォルト | 推奨・必須区分 | 説明 |
|---|---|---|---|
| `STORAGE_BACKEND` | `sqlite` | デフォルト可 | ストレージバックエンド (`sqlite` / `postgres` / `supabase`) |
| `SUPABASE_URL` | `""` | **[Supabase用]** 設定必須 | Supabase プロジェクト URL |
| `SUPABASE_KEY` | `""` | **[Supabase用]** 設定必須 | Supabase Service Role Key (機密情報のため厳重管理) |
| `SUPABASE_REQUEST_TIMEOUT_SECONDS` | `10.0` | デフォルト可 | **[Supabase用]** Supabase Data API 呼び出しのタイムアウト秒数 |
| `EMBEDDING_PROVIDER` | `local-model` | デフォルト可 | 埋め込みプロバイダー (`local-model` / `openai` / `litellm` / `custom-api`) |
| `LOCAL_MODEL_NAME` | `cl-nagoya/ruri-v3-310m` | デフォルト可 | ローカルモデル名 (768次元) |
| `EMBEDDING_DIMENSION` | `768` | デフォルト可 | 埋め込みベクトル次元数 (例: 768) |
| `GRAPH_ENABLED` | `false` | デフォルト可 | グラフ関係性機能の有効化。SQLite では内部グラフ、PostgreSQL では Neo4j を使用。Supabase では `graph_sync_mode=async_outbox` のみ対応 |
| `GRAPH_SYNC_MODE` | `sync` | デフォルト可 | グラフの同期モード (`sync` = 直接同期 / `async_outbox` = Outbox を介した非同期同期) |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `5.0` | デフォルト可 | **[async_outbox用]** Outbox ワーカーのポーリング間隔秒数 |
| `OUTBOX_BATCH_SIZE` | `100` | デフォルト可 | **[async_outbox用]** 1回のポーリングで処理する最大イベント数 |
| `OUTBOX_MAX_RETRIES` | `10` | デフォルト可 | **[async_outbox用]** Neo4j 同期失敗時の最大リトライ回数 |
| `OUTBOX_BACKOFF_BASE_SECONDS` | `1.0` | デフォルト可 | **[async_outbox用]** Exponential Backoff のベース待機秒数 |
| `OUTBOX_BACKOFF_MAX_SECONDS` | `60.0` | デフォルト可 | **[async_outbox用]** Exponential Backoff の最大待機秒数 |
| `CACHE_BACKEND` | `inmemory` | デフォルト可 | キャッシュバックエンド (`inmemory` / `redis`) |
| `REDIS_URL` | `redis://localhost:6379` | **[Redis用]** 設定必須 | Redis 接続 URL。`CACHE_BACKEND=redis` のときのみ使用し、接続失敗時の暗黙フォールバックは行いません |

### 2. ChronosGate 連携 / Turn-End Hook 設定

| 環境変数 | デフォルト | 推奨設定 | 説明 |
|---|---|---|---|
| `MCP_GATEWAY_API_KEY` | 未設定 | turn-end hook 使用時必須 | `agent_turn_hook.py` が ChronosGate へ送る Bearer 相当の API キー |
| `MCP_GATEWAY_URL` | `http://127.0.0.1:9100` | デフォルト可 | `agent_turn_hook.py` から到達する ChronosGate URL |

> [!NOTE]
> ツール実行前安全評価と Gateway 認証キーの詳細は ChronosGate 側で管理します。ChronosGraph 側では turn-end ingestion のクライアントフック設定のみを扱います。

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
> `CHRONOS_INGESTION_MODE=all` を **環境変数として設定するだけでは全量保存は機能しません。** 自動保存の経路はクライアント側 hook の責務です。ChronosGate を併用する場合は、Gateway 側の `memory.ingest` intent も許可してください。

**前提条件 (全クライアント共通)**

1. `MCP_GATEWAY_API_KEY` 環境変数を hook プロセスに渡す (未設定時は no-op)。
2. `MCP_GATEWAY_URL` を hook プロセスから到達可能にする (デフォルト `http://127.0.0.1:9100`)。
3. ChronosGate を併用する場合は、Gateway 側の API キー設定と `memory.ingest` intent を許可しておく。
4. 以下の例はローカルリポジトリから実行する前提のため、`uv` が利用可能であること。

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
| `CHUNK_PARALLEL_SEMAPHORE_SIZE` | `10` | > 0 | **(E-1)** Ingestion 並列モード (`GRAPH_ENABLED=false` 時) でのチャンク同時処理の最大同時実行数。 |
| `EMBEDDING_MAX_RETRIES` | `3` | > 0 | **(E-2)** OpenAI / LiteLLM 埋め込み API リトライの最大試行回数 (旧 5 → 3)。 |
| `EMBEDDING_MIN_WAIT` | `1.0` | > 0 | **(E-2)** 指数バックオフの最小待機秒数。 |
| `EMBEDDING_MAX_WAIT` | `10.0` | > 0 | **(E-2)** 指数バックオフの最大待機秒数 (旧 60s → 10s)。`Retry-After` ヘッダを尊重する際もこの値でクランプ。 |
| `EMBEDDING_PER_ATTEMPT_TIMEOUT` | `10.0` | > 0 | **(E-2)** 1 リトライ試行あたりの HTTP タイムアウト秒数。 |

> 💡 **レイテンシ設計:** Embedding API 経由の総レイテンシは **最大 ~50 秒** (3 試行 × 10s + 2 待機 × 10s) と見積もられます。`CHUNK_PARALLEL_SEMAPHORE_SIZE` および `EMBEDDING_*` の不正値・非正値は警告ログ + デフォルト値へフォールバック (fail-soft) します。Gateway 側のタイムアウト設計は ChronosGate リポジトリを参照してください。

**実装参照:**

- **E-1** Chunk 並列化: [`src/context_store/ingestion/pipeline.py`](src/context_store/ingestion/pipeline.py) `CHUNK_PARALLEL_SEMAPHORE_SIZE`
- **E-2** Embedding retry: [`src/context_store/embedding/retry_config.py`](src/context_store/embedding/retry_config.py) `EmbeddingRetryPolicy`

### 💡 ChronosGate / LiteLLM 設定

ツール実行前安全評価で利用する LiteLLM プロバイダ設定、カスタムエンドポイント、Gateway タイムアウト、承認フローの詳細は [ChronosGate](https://github.com/yohi/chronos-gate) 側の README を参照してください。

---

---

## 🛠 トラブルシューティング

- [LiteLLM Cloudflare 接続エラー (Typo Bug) の修正方法](docs/troubleshooting/litellm-cloudflare-typo.md)

## ライセンス

MIT License — [LICENSE](LICENSE)
