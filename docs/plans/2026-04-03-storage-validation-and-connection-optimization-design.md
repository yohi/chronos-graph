# Storage Validation and Connection Optimization Design

## 1. Introduction
ストレージアダプター（Postgres および SQLite）における入力バリデーションの強化と、SQLite バッチ取得時の接続オーバーヘッドの削減を目的とします。

## 2. Components and Logic

### 2.1. PostgresStorageAdapter.get_memories
- **`filters.order_by` のバリデーション**:
    - `ALLOWED_SORT_COLUMNS` に含まれないカラム名が指定された場合、`StorageError(code="INVALID_PARAMETER")` を送出します。
    - ソート方向（ASC/DESC）以外のトークンが指定された場合、`StorageError(code="INVALID_PARAMETER")` を送出します。
- **`filters.limit` のバリデーション**:
    - `int` への変換に失敗するか、負の値が指定された場合、`StorageError(code="INVALID_PARAMETER")` を送出します。

### 2.2. SQLiteStorageAdapter.update_memory
- **JSON カラム (`tags`, `source_metadata`) のバリデーション**:
    - 入力が `str` の場合:
        - `json.loads()` でパース可能かを確認。
        - `tags` は `list` であること、`source_metadata` は `dict` であることを検証。
    - 入力が `str` 以外の場合:
        - `json.dumps()` でシリアライズ可能かを確認。
    - 上記のいずれかに失敗した場合、`StorageError(code="INVALID_PARAMETER")` を送出します。

### 2.3. SQLiteStorageAdapter.get_memories_batch
- **接続の再利用**:
    - `async with self._db() as conn:` ブロックをチャンクループの外側に移動し、バッチ全体の処理で単一の接続を保持するように改善します。

## 3. Error Handling
- 無効なパラメータに対しては、一貫して `StorageError(code="INVALID_PARAMETER")` を使用します。

## 4. Testing Strategy
- `tests/unit/test_postgres_storage.py` および `tests/unit/test_sqlite_storage.py` に、不正なパラメータ（無効なソートカラム、負のリミット、不正な形式の JSON 文字列など）を渡した際に `StorageError` が発生することを確認するテストケースを追加します。
- `get_memories_batch` の修正により、既存の機能が壊れていないことを既存のテストで確認します。
