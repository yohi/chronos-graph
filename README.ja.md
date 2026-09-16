# ChronosGraph

[English](README.md)

> MCP-based long-term memory system for AI agents using temporal knowledge graphs.

---

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> [!NOTE]
> このドキュメントは [英語版](README.md) の日本語訳です。内容に相違がある場合は英語版が正規の情報源です。

ChronosGraph は、AIエージェント（Claude Code / Gemini CLI / Cursor 等）に
[Model Context Protocol](https://modelcontextprotocol.io/) (MCP) サーバーとして、
セッションを跨いだ永続的な長期記憶を提供します。

情報は孤立したベクトルではなく、時間軸を伴う多層グラフとして保存されます。
これにより、**エピソード記憶**（経験）、**セマンティック記憶**（事実）、
**手続き記憶**（ワークフロー）の各層を追跡できます。
減衰モデルと重要度スコアにより、記憶の肥大化を防ぎながら有用な知識を保持します。

> [!NOTE]
>
> 現行実装上の注意:
>
> - `memory_search` は API 互換性のために `memory_type` フィルタを受け取りますが、
>   検索結果への反映は未実装です。
>
> - `memory_search_graph` は `edge_types` と `depth` を受け取りますが、
>   専用のグラフ走査経路は未実装で、標準のハイブリッド検索へフォールバックします。
>
> - `memory_save` / `memory_search` などで渡す `project` は自動的に正規化されます
>   （前後空白除去、小文字化、basename）。`.` のみ指定された場合は、
>   現在の git リポジトリルート名に置き換わります。正規化時に filesystem へはアクセスしません。

---

## はじめ方

| したいこと | 参照先 |
| --- | --- |
| MCP 長期記憶サーバーとして使う | [Quick Start](#quick-start) |
| AIエージェントに設定させる | [Agent Setup Protocol](docs/agent-setup-protocol.ja.md) または [AGENTS.md](AGENTS.md) |
| ローカル開発環境を整える | [Development](#development) |
| 設定項目をすべて確認する | [Configuration Reference](docs/configuration.md) |
| 古いバージョンから移行する | [Migration Guide](docs/migration.md) |
| トラブルを解決する | [Troubleshooting guides](docs/troubleshooting/) |

---

## Quick Start

リポジトリをクローンせず、`uvx` で即座に実行するのが最も簡単です。
タグ付きリリースは [release-please](https://github.com/googleapis/release-please) によって作成され、
GitHub tarball から直接インストールできます。

### Claude Desktop（リリース tarball 版）

`~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）または
`%APPDATA%\Claude\claude_desktop_config.json`（Windows）に以下を追加します。
リリースで公開された full commit SHA を使用し、セットアップ手順に従って
source archive の checksum を検証してください。

```json
{
  "mcpServers": {
    "chronos-graph": {
      "command": "uvx",
      "args": [
        "--from",
        "context-store-mcp[all] @ https://github.com/yohi/chronos-graph/archive/<full-commit-sha>.tar.gz",
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

本番環境では `<full-commit-sha>` をリリースで公開された full commit SHA に置き換え、
対応する source archive の checksum を設定登録前に検証してください。詳細は
[AIエージェント向け自動セットアップ](docs/agent-setup-protocol.ja.md) を参照してください。

### 開発用 checkout

開発時は検証済みのローカル checkout と Agent Setup Protocol を使用します。
mutableなブランチやタグをクライアント設定へ直接指定せず、リモート実行では
full commit SHAを使い、source archiveのchecksumを検証してください。

> 💡 **環境変数について**: この Quick Start は長期記憶 MCP サーバー (`context-store`)
> の最小構成例です。Claude Desktop は JSON 設定ファイル内の `${VAR}` 構文を展開しません。
> 機密情報を渡す場合は、環境変数をエクスポートしてから起動するラッパースクリプトを
> 指定することを推奨します。

---

## 特徴

- **ハイブリッド検索** — ベクトル検索 + キーワード検索 + グラフ結果を RRF で融合
  （グラフ有効時）
- **多層記憶モデル** — エピソード / セマンティック / 手続き の3層
- **時間的減衰** — 指数関数的減衰スコアで古い記憶を整理
  （明示的な `memory_prune` は現行実装では SQLite バックエンドのみ実行）
- **重複排除** — Append-only 置換 + SUPERSEDES グラフエッジで変遷を追跡
- **ライトウェイトモード** — SQLite + sqlite-vec でゼロ設定で起動
- **スケーラブル** — PostgreSQL + Neo4j + Redis への切り替え対応、
  Supabase Data API による HTTPS 経由のアクセス
  （Supabase + Neo4j Aura は `async_outbox` モードにより解禁）
- **RL 拡張ポイント** — ActionLogger / RewardSignal / PolicyHook インターフェース
- **Dashboard Web UI** — React + FastAPI のダッシュボード、
  Cytoscape.js によるグラフ可視化とリアルタイムログストリーミング
- **ChronosGate 連携** — ツール実行前の安全評価は独立リポジトリ
  [ChronosGate](https://github.com/yohi/chronos-gate) として提供

---

## 仕組み

ChronosGraph は Python 3.12+ の FastMCP サーバーとして動作します。
エージェントは MCP 越しに `memory_save`、`memory_search`、
`memory_search_graph` などのツールを呼び出します。
保存された記憶はチャンク化・埋め込み・保存され、
グラフモード有効時には時間的グラフへリンクされます。
検索ではベクトル類似度、全文検索ランキング、グラフ走査結果を
単一のランキングリストに統合します。

厳密なツール契約、状態遷移、設計不変条件については [SPEC.md](SPEC.md) を参照してください。
埋め込みモデルの選定ガイドは [docs/embedding-models.ja.md](docs/embedding-models.ja.md)、
運用上の問題解決は [docs/troubleshooting/](docs/troubleshooting/) を参照してください。

---

## 使い方

MCP サーバーの登録後、エージェントは以下のようなツールを呼び出せます:

```json
{
  "tool": "memory_save",
  "params": {
    "content": "User prefers concise answers with concrete examples.",
    "project": "my-project",
    "tags": ["preference"]
  }
}
```

```json
{
  "tool": "memory_search",
  "params": {
    "query": "What does the user prefer?",
    "project": "my-project",
    "top_k": 5
  }
}
```

正確なリクエスト / レスポンススキーマとエラー意味論は [SPEC.md](SPEC.md) で定義されています。

---

## 設定

特に重要な変数は以下の通りです:

- `STORAGE_BACKEND` — `sqlite`、`postgres`、`supabase`
- `GRAPH_ENABLED` — `true` または `false`
- `CACHE_BACKEND` — `inmemory` または `redis`
- `EMBEDDING_PROVIDER` — `local-model`、`openai`、`litellm`、`custom-api`
- `EMBEDDING_DIMENSION` — ストレージスキーマと一致させる必要があります（デフォルト `768`）
- `CHRONOS_INGESTION_MODE` — `selective`（エージェント主導のツール呼び出し）または
  `all`（フックによるターン終了自動保存）

完全な設定リファレンス、デフォルト値、必須項目、セキュリティ上の注意については
[docs/configuration.md](docs/configuration.md) を参照してください。
モデル固有のガイドは [docs/embedding-models.ja.md](docs/embedding-models.ja.md) を参照してください。

---

## ドキュメント

- [Agent Setup Protocol](docs/agent-setup-protocol.ja.md) — AIエージェント向け長期記憶 MCP の
  インストール・設定手順
- [AGENTS.md](AGENTS.md) — 本リポジトリで作業する AI コーディングエージェント向けの
  正規指示書
- [Configuration Reference](docs/configuration.md) — 環境変数の完全な一覧
- [Migration Guide](docs/migration.md) — バージョン間の移行手順
- [Embedding Models Guide](docs/embedding-models.ja.md) — 埋め込みモデルの選定・切り替えガイド
- [Troubleshooting](docs/troubleshooting/) — 運用上の問題解決
- [SPEC.md](SPEC.md) — 正規の技術仕様書

---

## Development

Python コマンドはすべて `uv` を通して実行してください。

```bash
# 依存関係のインストール
uv sync --all-extras

# テスト
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v

# Lint / format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# 型チェック
uv run mypy src/
```

フロントエンド (`frontend/`):

```bash
pnpm install
pnpm run lint
pnpm run test:unit
```

隔離されたテスト・静的解析サンドボックスについては [SPEC.md §18](SPEC.md) を参照してください。

## AI コーディングエージェントでセットアップする

セットアップしたい用途に応じて、以下のプロンプトのいずれかを AI コーディングエージェント
（Claude Code、Cursor、OpenCode など）に貼り付けると、このリポジトリのセットアップを任せることができます。

### ChronosGraph を長期記憶 MCP サーバーとして利用する

```text
Set up https://github.com/yohi/chronos-graph as a long-term-memory MCP server
for an AI agent. First read the canonical setup source at
https://raw.githubusercontent.com/yohi/chronos-graph/master/docs/agent-setup-protocol.md.
Use a structured question tool for every blocking step and before any side
effect. Follow the protocol, register the generated MCP configuration only
after approval, reload the client, and verify MCP initialization plus a
mode-appropriate memory tool smoke test. In selective mode, use
memory_search/memory_save; in all mode, verify the turn-end hook/plugin and
read back the stored memory instead of calling memory_save directly. Do not
create configuration or hook files manually.
```

### リポジトリをローカル開発環境としてセットアップする

```text
Set up this repository (https://github.com/yohi/chronos-graph) for local
development. First read the canonical setup source at
https://raw.githubusercontent.com/yohi/chronos-graph/master/AGENTS.md.
Use a structured question tool for every blocking step and before any side
effect. Follow its installation and verification instructions, and report
the exact commands and results without committing or pushing changes.
```
---

## マイグレーション

デフォルトの埋め込み次元数が **1024** から **768** に変更されました。
古いスキーマから再埋め込みまたはストレージカラムの更新を行わずにアップグレードすると、
起動時に `ConfigurationError` が発生します。
再埋め込みスクリプトとスキーマ更新 SQL については
[docs/migration.md](docs/migration.md) を参照してください。

---

## ライセンス

MIT License — [LICENSE](LICENSE)
