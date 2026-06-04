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
4. **Neo4j接続（グラフ関係性機能）**:
   * `有効` (SQLiteは内部グラフ、Postgresは外部Neo4jを使用)
   * `無効` (🌟推奨: 高速かつシンプルな軽量構成)
5. **キャッシュ**:
   * `inmemory` (🌟推奨: プロセス内メモリで管理)
   * `redis` (本番用: 外部の Redis キャッシュサーバーを使用)
6. **埋め込みベクトルモデル**:
   * `local-model` (🌟推奨: ローカルのモデル `cl-nagoya/ruri-v3-310m` 等を使用)
   * `openai` (OpenAI の Embedding API を利用)
   * `litellm` (LiteLLM 経由でモデルを利用)
   * `custom-api` (独自のカスタムAPIを利用)

*(※追加情報の入力)*
* **PostgreSQL選択時**: ベクトル検索（pgvector拡張）が有効であることを事前に確認します。
* **local-model選択時**: ローカルモデル名（デフォルト: `cl-nagoya/ruri-v3-310m`）の入力を求めます。
* **openai/litellm/custom-api選択時**: 使用する埋め込みモデル名（例: `text-embedding-3-small`）の入力を求めます。

#### 【ケース B】安全評価Hookの場合
以下の項目を `ask_question` 等を用いて一括でユーザーに提示し、回答を確定させてください。

1. **起動方法 (Source)**:
   * `remote` (🌟推奨: リモートの GitHub から uvx 経由で評価コマンドを実行する)
   * `local` (ローカルのリポジトリを Python 経由で呼び出す)
2. **安全評価を行うLLMモデル**:
   * 使用する LLM モデル（例: `anthropic/claude-3-5-haiku-20241022` 等）を確認。

---

### Phase 3: パラメータの収集 (BLOCKING STEP)
上記の回答結果に基づいて、必要なパラメータの入力を `ask_question` 等の入力ツールを用いてユーザーに求めてください。
**注意**: セキュリティ保護のため、パスワード等の機密情報が含まれるURLを入力する際は、パスワード部分を `[YOUR-PASSWORD]` などのプレースホルダーにした状態で入力してもらい、Phase 6 で直接 `.env` に設定します。

#### 【ケース A】長期記憶MCPの場合
* **Postgres接続URL**: `postgresql://postgres:[YOUR-PASSWORD]@localhost:5432/postgres` 等の形式（パスワードはプレースホルダー）。
* **SupabaseプロジェクトURL**: `https://your-project.supabase.co` 形式の接続先URL（APIキーはPhase 6で設定）。
* **Neo4j接続URI**: `neo4j+s://[YOUR-USER]:[YOUR-PASSWORD]@host` 等の形式。
* **Redis接続URL**: `redis://default:[YOUR-PASSWORD]@host:port` 等の形式。

#### 【ケース B】安全評価Hookの場合
* **LLMアカウントID (オプション)**: Cloudflare Workers AI 等のアカウントIDが必要な LLM プロバイダを利用する場合のみ入力します（`CHRONOS_EVALUATOR_API_ACCOUNT_ID` にマッピングされます）。不要なプロバイダの場合は空のままで進めます。

---

### Phase 4: 対象AIエージェントの選択 (BLOCKING STEP)
必ず `ask_question` 等のツールを使用して、複数選択可能な形式でフックを適用する対象エージェントを提示し、ユーザーに選択させてください。

* `[ ] claudecode`
* `[ ] codex`
* `[ ] antigravitycl`
* `[ ] opencode`
* `[ ] cursorcli`

---

### Phase 5: scripts/bootstrap.sh の実行
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
  [--evaluator-model <evaluator_model>] \
  [--evaluator-api-account-id <api_account_id>] \
  [--db-host <db_host>] [--db-port <db_port>] [--db-name <db_name>] [--db-user <db_user>] \
  [--neo4j-uri <neo4j_uri>] [--neo4j-user <neo4j_user>] \
  [--redis-url <redis_url>] \
  [--embedding-model <embedding_model>]
```

---

### Phase 6: 機密情報の入力
1. スクリプトの実行後、ユーザーに対し「`.env` ファイルを開き、プレースホルダー（`[YOUR-PASSWORD]` 等）になっている部分のパスワードや、APIキー（`OPENAI_API_KEY`, `SUPABASE_KEY` など）を手動で直接入力してください」と求めます。
2. ユーザーから入力完了の報告を受けたら、次のフェーズへ進みます。

---

### Phase 7: 接続テスト
設定完了後、疎通確認と安全評価機能の正常動作を確認します。
1. **MCP 疎通テスト**: MCPサーバーが正常に起動し、設定したデータベースやキャッシュに接続できるかテストします。
2. **安全評価Hookテスト**: 登録したエージェントフックが機能し、評価エンジン（LLM）を通した動作確認テストを自動実行します。
3. すべてクリアになれば、自動セットアップは完了です。
