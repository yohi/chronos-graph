# Design Doc: Storage Layer Robustness and Naming Refinement

Date: 2026-03-26
Status: Approved

## 1. Objective
`SPEC.md` および `2026-03-26-implementation-plan.md` における設計不整合の解消と、ストレージ層（特に SQLite）の堅牢性向上を目的とする。

## 2. Key Changes

### 2.1 Exception Naming Refinement
- **Current:** `MemoryError`
- **Target:** `StorageError`
- **Rationale:** Python 組み込みの `MemoryError` (Out of Memory) との衝突を回避し、ドメイン例外であることを明確にする。

### 2.2 Semaphore with Acquisition Timeout
- **Backpressure Signal:** SQLite への同時接続制限を `asyncio.Semaphore` で管理する際、タイムアウト（`SQLITE_ACQUIRE_TIMEOUT`）を導入する。
- **Behavior:** セマフォ取得待ちがタイムアウトした場合、`StorageError(code="STORAGE_BUSY", recoverable=True)` を送出する。
- **Rationale:** リクエストのバースト時に asyncio イベントループ内での無制限なタスク滞留を防ぎ、呼び出し側にバックプレッシャーを正しく伝える。

### 2.3 Protocol Naming Alignment
- `SQLiteStorageAdapter` 内のメソッド名を `StorageAdapter` Protocol と完全に一致させる。
  - `search` → `vector_search` / `keyword_search`
  - `save_memory` -> `save_*` (Protocol準拠)

## 3. Implementation Details

### 3.1 Settings Update
- `sqlite_acquire_timeout: float = 2.0` (seconds) を追加。

### 3.2 Testing Strategy
- **Concurrency Test:** `sqlite_max_concurrent_connections=2` の状態でバーストアクセスを発生させ、同時実行数が 2 を超えないことを検証。
- **Timeout Test:** タイムアウト発生時に `STORAGE_BUSY` が返ることを検証。

## 4. Documentation Impact
- `SPEC.md`: 例外クラス名の全置換、セマフォ制御の説明更新。
- `2026-03-26-implementation-plan.md`: テスト要件と設計詳細の具体化。
