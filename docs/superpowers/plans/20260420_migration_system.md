# 作業計画: 自作マイグレーション機能の実装

## 1. 背景と目的
現在、ChronosGraph は SQLite と PostgreSQL をサポートしているが、スキーマの変更を管理する仕組み（マイグレーション）が存在しない。
SQLite はコード内に DDL がハードコードされており、PostgreSQL は外部の SQL ファイルに依存している。
今後の機能拡張に伴うスキーマ変更を安全かつ自動的に行うため、SQL ファイルベースの軽量なマイグレーション機能を自作する。

## 2. 要件
- **マルチ DB 対応**: SQLite と PostgreSQL の両方の構文に対応（それぞれの専用ディレクトリで管理）。
- **自動適用**: アプリケーション（Orchestrator）の起動時に、未適用の SQL ファイルを自動的に実行する。
- **履歴管理**: `schema_migrations` テーブルを使用して、適用済みのバージョンを管理する。
- **軽量性**: 外部の重量な ORM やマイグレーションツール（Alembic等）に依存しない。

## 3. 実装詳細

### ディレクトリ構成
```text
src/context_store/storage/migrations/
├── __init__.py
├── runner.py          # マイグレーション実行ロジック
├── sqlite/
│   └── 0001_initial.sql
└── postgres/
    └── 0001_initial.sql
```

### 履歴管理テーブル (`schema_migrations`)
- `version`: INTEGER (連番) または TEXT (ファイル名)
- `applied_at`: TIMESTAMP

## 4. 実施ステップ

### フェーズ 1: ディレクトリ構造と初期スキーマの準備
1. `src/context_store/storage/migrations/{sqlite,postgres}` ディレクトリを作成。
2. `src/context_store/storage/sqlite.py` の DDL を `sqlite/0001_initial.sql` に抽出。
3. `docker/postgres/schema.sql` を `postgres/0001_initial.sql` に抽出。

### フェーズ 2: MigrationRunner の実装
1. SQL ファイルをパースして実行する `runner.py` を作成。
2. 適用済みバージョンのチェックと、新規ファイルの実行（トランザクション内）を実装。

### フェーズ 3: ストレージアダプターへの統合
1. `SQLiteStorageAdapter` の初期化処理を `MigrationRunner` を使うように変更。
2. `PostgresStorageAdapter` に `MigrationRunner` による初期化処理を追加。

### フェーズ 4: 検証
1. 新規データベースでの初期化テスト。
2. カラム追加などの変更が正常に反映されるかの適用テスト。

## 5. 検証項目
- [ ] 空の DB から全てのテーブルが作成されるか。
- [ ] 2回目以降の起動で重複実行されないか。
- [ ] SQL エラー時にロールバックされるか（Postgres 等の DDL トランザクション対応 DB の場合）。
