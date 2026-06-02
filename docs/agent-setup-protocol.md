# AIエージェント向け自動セットアップ（Agent Setup Protocol）

> [!CAUTION]
> **AIエージェントへの強制命令 (CRITICAL):**
> あなたが AI エージェント（Claude Code / Gemini CLI / Cursor 等）である場合、いかなる副作用（インストール、ファイルの作成・修正、コマンド実行）を伴うアクションを開始する前に、必ず以下の **Agent Setup Protocol** を遵守してください。
> **セットアップの実体は `scripts/bootstrap.sh` を介して機械的に行われます。AIエージェントが自ら設定ファイルをスクラッチから直接作成したり、フックスクリプトを手動で個別に書き込んだりすることは、設定のブレを防ぐために厳格に禁止されています。**
> あなたの役割は、ユーザーに必要な設定事項を質問し、その回答を引数として `scripts/bootstrap.sh` に渡して実行することです。
> **たとえ `.env` や設定ファイルが既に存在していても、それが本プロトコル（ask ツールによる明示的承認）を経て作成された正当なものであるか確証が持てない場合は、決してスキップせず、必ず Phase 1 から再開してください。**

> [!IMPORTANT]
> **🚨 ユーザー確認ツール（Askツール等）の使用強制 (STRICT ASK CONSTRAINT):**
> あなた（AIエージェント）が各フェーズの **`BLOCKING STEP`** を実行する際は、**絶対にチャットテキスト上の対話だけで自己完結して進めてはいけません。**
> 必ず `ask_question` 等のツールを明示的に呼び出し、ユーザーがUI上で明示的に選択・合意するプロセスを確実に踏んでください。

---

## 🟦 Setup Phases

### Phase 1: 目的の確定と実行モードの選択 (BLOCKING STEP)
いかなる変更を伴うツールを呼び出す前に、必ずユーザーに以下の質問を提示し、セットアップ目的および **実行モード** を確定させてください。

1. **セットアップ対象の選択**:
   * `mcp` (長期記憶MCP: MCPサーバーとしての起動・登録)
   * `hook` (安全評価Hook: ツール実行前保護フックの登録)
2. **実行モードの選択**:
   * `production` (本番モード: 実際に環境構築・ファイルの変更を行う)
   * `dry-run` (デバッグモード: ファイルを一切変更せず、シミュレーションと解説のみを行う)
   * **判定条件**: 
     - ローカルの `@README.md` などの参照から実行している場合は、必ず本質問で「本番かDry-runか」を確認・選択させてください。
     - `https://raw.githubusercontent.com/...` 等のリモートファイルから直接ロードされている場合は、質問をスキップし、デフォルトで「本番モード（`production`）」として進行して構いません。

---

### Phase 2: 詳細設定の確認とロックイン (BLOCKING STEP)

#### 【ケース A】長期記憶MCPの場合
以下の項目を `ask_question` 等を用いて一括でユーザーに提示し、回答を確定させてください。
*(※長期記憶MCPの場合、LLM評価（Evaluator）の設定は不要です)*

1. **配置・起動方法 (Source)**:
   * `remote` (🌟推奨: リポジトリをクローンせず `uvx` を用いてオンザフライで起動・実行する)
   * `local` (ローカルにクローン済みの本リポジトリ内で直接実行する)
2. **保存モード (Ingestion Mode)**:
   * `all` (全量保存モード: エージェントのターン終了時に会話ログをバックグラウンドで全量自動保存。フックスクリプトが必要です)
   * `selective` (自律判断保存モード: AIが重要と判断した情報のみを `memory_save` ツール経由で保存。フックスクリプトは不要です)
3. **ストレージ (Storage Backend)**:
   * `sqlite` (🌟推奨: ゼロ設定かつ軽量に動作)
   * `postgres` (本番用: pgvector が必要)
   * `supabase` (本番用: クラウドベースの Supabase Data API を経由)
4. **PostgreSQL ベクトル検索前提確認 (PostgreSQL選択時のみ)**:
   * `確認した` (pgvector拡張が有効であることを確認します)
   * `該当なし` (PostgreSQLを選択していない場合)
5. **Neo4j接続（グラフ関係性機能）**:
   * `有効` (SQLiteは内部グラフ、Postgresは外部Neo4jを使用)
   * `無効` (🌟推奨: 高速かつシンプルな軽量構成)
6. **キャッシュ**:
   * `inmemory` (🌟推奨: プロセス内メモリで管理)
   * `redis` (本番用: 外部の Redis キャッシュサーバーを使用)
7. **埋め込みベクトルモデル**:
   * `cl-nagoya/ruri-v3-310m` (🌟推奨: 日本語に優れる標準モデル)
   * `OpenAI` (OpenAI の Embedding API を利用)
8. **OpenAIのモデル確認 (EmbeddingがOpenAIのときのみ)**:
   * `text-embedding-3-small` / `text-embedding-3-large` / `text-embedding-ada-002` からモデル名を確認。

#### 【ケース B】安全評価Hookの場合
以下の項目を `ask_question` 等を用いて一括でユーザーに提示し、回答を確定させてください。

1. **安全評価を行うLLMモデル**:
   * 使用する LLM モデル（例: `anthropic/claude-3-5-haiku-20241022` 等）を入力・確認。
2. **起動方法 (Source)**:
   * `remote` (🌟推奨: リモートの GitHub から uvx 経由で評価コマンドを実行する)
   * `local` (ローカルのリポジトリを Python 経由で呼び出す)

---

### Phase 3: パラメータの収集 (BLOCKING STEP)
上記の回答結果に基づいて、**機密情報に該当しない追加のパラメータ** の入力を `ask_question` 等の入力ツールを用いてユーザーに求めてください。

* **PostgreSQL選択時**: `ホスト名`、`ポート番号`、`データベース名`、`ユーザー名` の入力を求めます。（パスワードは機密情報のため収集しません）
* **Neo4j接続（グラフ有効時）**: `Neo4j URI`、`ユーザー名` の入力を求めます。（パスワードは機密情報のため収集しません）
* **Redis選択時**: `Redis 接続URL`（例: `redis://localhost:6379/0`）の入力を求めます。
* **LiteLLM/Custom API選択時**: 埋め込みモデル名（`embedding-model`）の入力を求めます。

---

### Phase 4: 対象AIエージェントの選択 (BLOCKING STEP)
必ず `ask_question` 等のツールを使用して、複数選択可能な形式でフックを適用する対象エージェントを提示し、ユーザーに選択させてください。

* `[ ] claudecode`
* `[ ] codex`
* `[ ] antigravitycl`
* `[ ] opencode`
* `[ ] cursorcli`

---

### Phase 5: scripts/bootstrap.sh の実行と検証

収集したパラメータに基づいて、`scripts/bootstrap.sh` を引数付きで呼び出します。AIエージェント自身でファイルを直接編集したり作成したりすることはせず、必ずこのスクリプトに実行を委ねてください。

#### コマンド生成例：
```bash
./scripts/bootstrap.sh \
  --type <type> \
  --mode <mode> \
  --backend <backend> \
  --embedding <embedding> \
  --cache <cache> \
  --graph <graph> \
  --source <source> \
  --ingestion-mode <ingestion-mode> \
  --agents <comma_separated_agents> \
  [--graph-sync-mode <sync|async_outbox>] \
  [--evaluator-model <evaluator_model>] \
  [--db-host <db_host>] [--db-port <db_port>] [--db-name <db_name>] [--db-user <db_user>] \
  [--neo4j-uri <neo4j_uri>] [--neo4j-user <neo4j_user>] \
  [--redis-url <redis_url>] \
  [--embedding-model <embedding_model>]
```
*(※ `storage_backend == "supabase"` かつ `graph_enabled == true` の場合は、`graph_sync_mode` は自動的に `async_outbox` に補正・設定されます)*

このスクリプトを実行すると、自動的に以下の処理が機械的に行われます。
1. 依存関係の解決 (`uv sync --all-extras`)
2. `.env` の自動生成と、各ブロックのコメントアウト/アンコメントの制御 (不要設定のコメントアウトの自動徹底)
3. テストの実行による整合性チェック
4. `mcp_config.json` の生成 (mcp時)
5. 接続確認疎通テストの実行 (mcp かつ local 時)
6. 各エージェント用フックスクリプトの自動生成・配置、および OpenCode のプラグイン自動登録
7. 安全評価テストの実行 (hook時)

---

### Phase 6: 機密情報の入力と最終案内
1. スクリプトの実行後、ユーザーに対し「`.env` ファイルにパスワードやAPIキーなどの機密情報を直接手動で入力してください」と求めてください。
2. ユーザーから入力完了の報告を受けたら、自動セットアップは完了です。必要に応じてエージェントごとの追加手順（OpenCodeの npmrc 設定等）を表示して終了します。
