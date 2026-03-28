# 2026-03-28 SQLite ストレージの堅牢化と仕様整合の設計

## 1. 背景と目的
現在の設計では、SQLite ストレージの並行制御（バックプレッシャー）やエラーハンドリング、および環境変数の単位設定において、ドキュメント間（`SPEC.md` と `docs/plans/`）の不整合や、実行時の堅牢性に関する考慮不足が指摘されています。本設計では、これらの不整合を解消し、高負荷時やロック競合時でもシステムが安全に動作・回復できる仕組みを定義します。

## 2. アーキテクチャと詳細設計

### 2.1 環境変数の単位統一 (Source of Truth)
環境変数の解釈における曖昧さを排除し、Python の標準的な非同期ライブラリ（`asyncio`）との親和性を高めるため、以下の単位に統一します。

*   **`SQLITE_ACQUIRE_TIMEOUT`**: 単位を「**秒 (seconds)**」に変更。
    *   `SPEC.md` (L1046) の `2000` (ms) を `2.0` (秒) に修正。
    *   `.env.example` および実装コードにおいて、`float` 型として直接 `asyncio.wait_for` の `timeout` 引数に渡す。
    *   コード内でのミリ秒→秒への変換処理は行わず、環境変数の値をそのまま利用する。

### 2.2 SQLite エラーハンドリングと `STORAGE_BUSY` への変換
SQLite のロック競合やセマフォ取得待ちを、MCP クライアントが解釈可能な回復可能なエラーに集約します。

*   **事前キュー長チェック (Queue-length guard)**:
    *   `asyncio.wait_for(semaphore.acquire(), timeout=Settings.sqlite_acquire_timeout)` を呼び出す前に、実装は必ずセマフォの待機タスク数（例: 非プライベートな代替APIや安全な方法での待機長チェック、あるいは必要に応じて `len(semaphore._waiters)` 等）を検証し、`Settings.sqlite_max_queued_requests` 以上である場合は即座に `StorageError(code="STORAGE_BUSY", recoverable=True, message="Too many queued requests")` を送出する。これによりタイムアウトを待たずにフェイルファストする。
*   **エラーコードのマッピング**:
    *   `aiosqlite.OperationalError` (または `sqlite3.OperationalError`) をキャッチした際、以下の条件に合致する場合は `StorageError(code="STORAGE_BUSY", recoverable=True, ...)` に変換して再送出する。
        *   エラーメッセージに `"database is locked"` または `"database is busy"` が含まれる。
        *   SQLite エラーコードが `SQLITE_BUSY`, `SQLITE_LOCKED`, `SQLITE_BUSY_SNAPSHOT` 等に該当する。
    *   それ以外の `OperationalError` はそのまま再送出（または適切なエラーに変換）する。
*   **タイムアウトのエラーマッピング**:
    *   `asyncio.wait_for(semaphore.acquire(), ...)` による `asyncio.TimeoutError` をキャッチし、`StorageError(code="STORAGE_BUSY", recoverable=True, message="Semaphore acquisition timeout")` を送出する。

以上の「事前キュー長チェック（即時エラー送出）」と「タイムアウト・DBロック時のエラーマッピング」を併用することで、`SQLiteStorageAdapter.save_memory` や `vector_search` 等のすべての DB 操作関数において一貫したバックプレッシャー制御が適用されるようにする。

### 2.3 リソース管理の徹底
セマフォの解放漏れ（リソースリーク）を防ぐため、以下の実装パターンを義務付けます。

*   **確実な解放**: 全ての DB 操作メソッド（`save_memory`, `vector_search` 等）において、`async with self._semaphore:` または `try/finally` ブロックを用い、例外発生時やタイムアウト時でも確実に `release()` が実行されるようにする。

### 2.4 可観測性の向上
デバッグと運用の利便性を高めるため、ログ出力を改善します。

*   **`SUPERSEDES` チェーン解決ログ**:
    *   `SPEC.md` L816 の警告ログを以下のように変更する。
    *   `logging.warning(f"Physical hops limit ({Settings.graph_max_physical_hops}) reached while resolving SUPERSEDES chain for node {node_id}. Returning last reachable node (may not be the latest active version).")`
    *   これにより、エラーの発生箇所（ノードID）と原因（SUPERSEDES 解決中の物理ホップ制限）が明確になる。

## 3. テスト設計と検証要件

### 3.1 SQLite バックプレッシャーテストの具体化
並行制御機能が期待通りに動作することを、以下の項目でアサーションする。

1.  **成功ケース**: 同時接続制限（`sqlite_max_concurrent_connections`）以下のリクエストが正常に完了し、結果が正しいこと。
2.  **即時拒否ケース**: 待ち行列制限（`sqlite_max_queued_requests`）を超えたリクエストが、待機することなく即座に `StorageError(code="STORAGE_BUSY")` を送出すること。
3.  **タイムアウトケース**: セマフォ取得待ちが `sqlite_acquire_timeout` を超えたリクエストが、適切に `STORAGE_BUSY` エラーを返すこと。
4.  **不変条件（リソースリーク）検証**: テスト完了後、セマフォの内部カウンタ（`_value`）が初期値に戻っていることを確認し、リークがないことを証明する。

### 3.2 統合テスト
`aiosqlite` を用いた実際の DB 接続環境下で、上記のバックプレッシャーとエラーハンドリングが機能することを検証する。

## 4. 影響範囲
*   `SPEC.md`: 環境変数の定義と警告ログのメッセージ。
*   `docs/plans/2026-03-26-implementation-plan.md`: 実装手順とテスト要件の記述。
*   `src/context_store/config.py`: 環境変数のパース。
*   `src/context_store/storage/sqlite.py`: アダプターの実装ロジック。
*   `.env.example`: 設定サンプルの更新。
