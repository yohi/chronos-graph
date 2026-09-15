# AIエージェント向け自動セットアップ（Agent Setup Protocol）

> [!CAUTION]
> **AIエージェントへの強制命令 (CRITICAL):**
> あなたが AI エージェント（Claude Code / Gemini CLI / Cursor 等）である場合、いかなる副作用（インストール、ファイルの作成・修正、コマンド実行）を伴うアクションを開始する前に、必ず以下の **Agent Setup Protocol** を遵守してください。
>
> **セットアップの実体は `scripts/bootstrap.sh` を介して機械的に行われます。AIエージェントが自ら設定ファイルをスクラッチから直接作成したり、フックスクリプトを手動で個別に書き込んだりすることは、設定のブレを防ぐために厳格に禁止されています。**
>
> あなたの役割は、ユーザーに必要な設定事項を質問し、その回答を引数として `scripts/bootstrap.sh` に渡して実行することです。
>
> **たとえ `.env` や設定ファイルが既に存在していても、それが本プロトコル（ask ツールによる明示的承認）を経て作成された正当なものであるか確証が持てない場合は、決してスキップせず、必ず Phase 1 から再開してください。**
<!-- alert boundary -->

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
   * ツール実行前の安全評価Hookを設定したい場合は、このプロトコルではなく独立リポジトリ ChronosGate のセットアップ手順を使用してください。
2. **実行モードの選択**:
   * `production` (本番モード: 実際に環境構築・ファイルの変更を行う)
   * `dry-run` (デバッグモード: ファイルを一切変更せず、シミュレーションと解説のみを行う)

---

### Phase 2: 詳細設定の確認とロックイン (BLOCKING STEP)

#### 【ケース A】長期記憶MCPの場合

以下の項目を `ask_question` 等を用いて一括でユーザーに提示し、回答を確定させてください。
*(※ChronosGraph の長期記憶MCP設定では、LLM評価（Evaluator）の設定は不要です。安全評価は ChronosGate 側で扱います。)*

1. **配置・起動方法 (Source)**:
   * `remote` (🌟推奨: サーバーはリポジトリをクローンせず、リリース済みパッケージを `uvx` で実行する。bootstrap の実行には `scripts/bootstrap.sh` と `agent-assets/` を含むローカル checkout または展開済み release tarball が必要)
   * `local` (ローカルにクローン済みの本リポジトリ内で直接実行する)
2. **保存モード (Ingestion Mode)**:
   * `all` (全量保存モード: エージェントのターン終了時に会話ログをバックグラウンドで全量自動保存。フックスクリプトが必要です)
   * `selective` (自律判断保存モード: AIが重要と判断した情報のみを `memory_save` ツール経由で保存。フックスクリプトは不要です)
3. **ストレージ (Storage Backend)**:
   * `sqlite` (🌟推奨: ゼロ設定かつ軽量に動作)
   * `postgres` (本番用: pgvector が必要)
   * `supabase` (本番用: クラウドベースの Supabase Data API を経由)
4. **Neo4j接続（グラフ関係性機能）**:
   * `有効` (SQLiteは内部グラフ、PostgresとSupabaseは外部Neo4jを使用。Supabaseで有効にする場合は `async_outbox` も必要)
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
* **litellm選択時**: LiteLLMのベースURLの入力を求めます。
* **custom-api選択時**: カスタム埋め込みAPIエンドポイントの入力を求めます。

必要な環境変数の一覧は、[Configuration Reference](https://raw.githubusercontent.com/yohi/chronos-graph/master/docs/configuration.md)を参照してください。

#### 【ケース B】安全評価Hookの場合

ChronosGraph 本体では安全評価Hookをセットアップしません。ユーザーが安全評価Hookを求めている場合は、ChronosGate リポジトリの README / setup protocol を参照するよう案内し、この `scripts/bootstrap.sh` は実行しないでください。

---

### Phase 3: パラメータの収集 (BLOCKING STEP)

上記の回答結果に基づいて、必要なパラメータの入力を `ask_question` 等の入力ツールを用いてユーザーに求めてください。
**注意**: セキュリティ保護のため、パスワード等の機密情報が含まれるURLを入力する際は、パスワード部分を `[YOUR-PASSWORD]` などのプレースホルダーにした状態で入力してもらい、Phase 6 で直接 `.env` に設定します。

#### 【ケース A】長期記憶MCPの場合

* **PostgreSQLホスト**: `localhost` またはデプロイ済みデータベースのホスト名。
* **PostgreSQLポート**: `5432` 等。
* **PostgreSQLデータベース名**: `context_store` 等。
* **PostgreSQLユーザー**: `context_store` 等。
* **SupabaseプロジェクトURL**: `https://your-project.supabase.co` 形式の接続先URL（APIキーはPhase 6で設定）。
* **Neo4j接続URI**: `neo4j+s://[YOUR-USER]:[YOUR-PASSWORD]@host` 等の形式。
* **Redis接続URL**: `redis://default:[YOUR-PASSWORD]@host:port` 等の形式。
* **LiteLLMベースURL**: `litellm` 選択時に必須。
* **カスタム埋め込みAPIエンドポイント**: `custom-api` 選択時に必須。
* **Gateway URL**: `all` モードで必須。ChronosGraphはGatewayをインストールしません。
  `MCP_GATEWAY_URL` として設定し、hook登録前に疎通を確認します。

PostgreSQLのパスワードは `scripts/bootstrap.sh` の引数に渡さず、Phase 6で
`.env` に設定してください。

#### 【ケース B】安全評価Hookの場合

ChronosGate 側の手順に委譲します。このプロトコルでは、ChronosGraph の `.env` に `CHRONOS_EVALUATOR_*` 系の設定を書き込みません。

---

### Phase 4: 対象AIエージェントの選択 (BLOCKING STEP)

必ず `ask_question` 等のツールを使用して、ChronosGraphの対象環境として `claudecode`、`codex`、`opencode` の1つ以上を複数選択可能な形式で提示し、ユーザーに選択させてください。空選択は無効です。
`--non-interactive` でも対象Agentを暗黙選択してはなりません。必ず収集済みの明示選択を `--agents` に渡してください。

* `[ ] claudecode`
* `[ ] codex`
* `[ ] opencode`

---

### Phase 5: scripts/bootstrap.sh の実行

収集したパラメータに基づいて、`scripts/bootstrap.sh` を引数付きで呼び出します。AIエージェント自身でファイルを直接編集したり作成したりすることはせず、必ずこのスクリプトに実行を委ねてください。
`--agents`には1つのCSV値だけを渡します。bootstrapは副作用開始前に値をcanonicalizeし、両方のingestion modeでSkillsとinstructionsをインストールまたは同期します。
`--source=local|remote` は、MCP serverをローカル checkout またはリリース済み
パッケージのどちらで実行するかを宣言します。この指定だけでは bootstrap 用ファイルの
取得・展開や `uvx` の選択は行われません。Agent assetのSSOTは、bootstrapを実行する
checkout 内の `agent-assets/` です。リモートパッケージの起動方式とソースは
`--mcp-method` と `--uv-from` で指定します。

`remote` を選択する場合は、リリースで公開された full commit SHA を使用し、可変なタグを
使用しないでください。リリースと一緒に公開された checksum を取得し、展開前に tarball
を検証してから、検証済み checkout で bootstrap を実行します。例:

```bash
RELEASE_TAG="v<version>"
RELEASE_COMMIT_SHA="<full-40-character-commit-sha>"
RELEASE_TARBALL_NAME="chronos-graph-${RELEASE_COMMIT_SHA}.tar.gz"
RELEASE_TARBALL_URL="https://github.com/yohi/chronos-graph/archive/${RELEASE_COMMIT_SHA}.tar.gz"
RELEASE_CHECKSUM_URL="https://github.com/yohi/chronos-graph/releases/download/${RELEASE_TAG}/${RELEASE_TARBALL_NAME}.sha256"
curl -fL "$RELEASE_TARBALL_URL" -o "$RELEASE_TARBALL_NAME"
curl -fL "$RELEASE_CHECKSUM_URL" -o "$RELEASE_TARBALL_NAME.sha256"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum -c "$RELEASE_TARBALL_NAME.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 -c "$RELEASE_TARBALL_NAME.sha256"
else
  printf '%s\n' "sha256sum or shasum is required to verify the release archive" >&2
  exit 1
fi
tar -xzf "$RELEASE_TARBALL_NAME"
cd <extracted-checkout>

./scripts/bootstrap.sh \
  --type mcp \
  --mode production \
  --backend postgres \
  --embedding local-model \
  --cache inmemory \
  --graph false \
  --source remote \
  --mcp-method uvx \
  --uv-from "$RELEASE_TARBALL_URL" \
  --ingestion-mode selective \
  --agents <comma_separated_agents> \
  --db-host <db_host> \
  --db-port <db_port> \
  --db-name <db_name> \
  --db-user <db_user>
```

他のバックエンドやモードを使う場合は、収集した値に置き換えてください。Phase 6では、
この展開先 checkout 内の `.env` を編集します。Supabaseを選択した場合は、収集した
プロジェクトURLを `.env` の `SUPABASE_URL` として設定してください。`bootstrap.sh` は
Supabase設定を有効化するだけで、このURLを書き込みません。生成された `mcp_config.json`
をMCPクライアントに登録する場合は、URLと機密情報を設定した後、同じbackend、embedding、
cache、method、および不変の `--uv-from` 引数で `scripts/generate_config.py` を再実行するか、
クライアントの環境変数からそれらの値を渡してください。`generate_config.py` は `.env` から
URLを読み取り、bootstrapはPhase 6より前に設定ファイルを生成するためです。
OpenCodeを`all`モードで選択する場合は、実行前にGitHub Packagesの `@yohi` registry mappingと読み取り権限を持つcredential sourceがユーザー管理の `~/.npmrc` にあることを確認してください。Agentは`.npmrc`やtokenを作成・更新・保存してはなりません。

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
  [--db-host <db_host>] [--db-port <db_port>] [--db-name <db_name>] [--db-user <db_user>] \
  [--neo4j-uri <neo4j_uri>] [--neo4j-user <neo4j_user>] \
  [--redis-url <redis_url>] \
  [--embedding-model <embedding_model>] \
  [--litellm-api-base <litellm_api_base>] \
  [--custom-api-endpoint <custom_api_endpoint>]
```

ローカル checkout では `--mcp-method uv` を使用し、生成されるMCP設定が
checkoutのuv環境を使うようにします。`all` モードで Claude Code または Codex
を選択した場合は、生成された `scripts/chronos-turn-hook.sh`（Windowsでは
`.cmd`）をターン終了またはStop hookとして登録します。OpenCodeでは同期処理が
管理するplugin設定を使用し、GitHub Packagesのcredential前提も満たす必要があります。

---

### Phase 6: 機密情報の入力

このフェーズは実行モードが `production` の場合だけ実施します。

* **production**: Phase 5で使用した checkout 内の `.env` を開き、Supabaseを使用する場合は
  収集済みURLを `SUPABASE_URL` に設定し、プレースホルダー（`[YOUR-PASSWORD]` 等）になっている
  パスワードやAPIキー（`OPENAI_API_KEY`, `SUPABASE_KEY` など）を実際の値に置き換えるよう求めます。
  入力完了の報告を受けてから次へ進みます。秘密情報をチャットやコマンド引数に貼り付けてはいけません。
  再生成後の `mcp_config.json` は秘密情報を含む可能性があるため保護し、クライアントが環境変数を
  使える場合は登録後に削除します。
* **dry-run**: `.env` を開いたり編集したりせず、秘密情報の収集・入力も行いません。直接Phase 7へ進みます。

---

### Phase 7: 同期結果の検証

検証内容は選択した実行モードによって分かれます。

* **dry-run**: 同期計画、bundle digest、diagnosticsだけが期待どおり出力されることを確認します。既存のcheckoutを使用し、release archiveの取得・展開、依存関係のインストール、`.env`の編集、クライアント登録、グローバルAgentファイルの変更を行いません。dry-runはtransaction commit、instructionsやSkillsのインストール、保持状態の検証、hook artifactの作成を行わないため、それらを要求してはいけません。
* **production**: 同期が成功した場合は、transaction commit、選択したAgentのinstructions、各選択Agentの両方のSkills、digestの一致、marker外instructionsの保持、他Skillsの保持、許可されたlegacy warningの結果、`all`モードのhook artifact成功を検証してください。生成されたMCP設定を登録または明示的にユーザーへ引き渡し、クライアントをreloadし、MCP初期化と `memory_search` / `memory_save` のsmoke testを実行します。`all` モードではGatewayへの疎通と実際のターン終了イベントの到達も確認し、確認できなければ未完了として報告します。

dimension mismatch がある場合は、[Migration Guide](https://raw.githubusercontent.com/yohi/chronos-graph/master/docs/migration.md)を参照し、再埋め込みと検証が完了するまで旧ベクトルを保持します。

`all`モードで旧Save promptが検出されてpreflight collisionとして同期が拒否された場合は、検出された旧Save promptをユーザーが手動で削除してからbootstrapを再実行してください。この拒否はwriteとhook setupの前に発生し、bootstrapは旧promptやユーザーが複製したpromptを自動削除しません。

`selective`モード、または`all`モードで旧Recall promptが検出された場合は、warningを確認し、必要に応じて手動削除後に再実行してください。
