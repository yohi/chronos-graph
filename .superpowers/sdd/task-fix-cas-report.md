# CAS更新バックフィル修正レポート

## 実施内容

- SupabaseのPATCH URLに取得時の`project`条件を追加しました。`None`の場合は`project=is.null`を使用します。
- SupabaseのPATCH返却行数、PostgreSQLの`UPDATE n`、SQLiteの`rowcount`だけを`changed`へ加算するよう変更しました。
- PostgreSQLとSQLiteの更新SQLに取得時の`project`値を追加しました。
- 3つのバックフィルスクリプトのunit testでCAS条件と競合時の未加算を検証しました。

## 検証結果

- `uv run ruff check`: 成功
- `uv run ruff format`: 成功
- `uv run mypy src/`: 成功（81 source files）
- `uv run pytest tests/unit/scripts/ -v`: 成功（6 passed）
- `git diff --check`: 成功

## 注意事項

- 作業開始時点から存在した`uv.lock`の変更は、今回の作業対象外としてコミットしません。
- LSPはbasedpyright未導入かつ過去にインストール拒否済みのため実行できませんでした。
