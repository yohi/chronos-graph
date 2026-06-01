-- 設計方針:
-- 1. status: 成功したイベントは物理削除される設計(Delete-on-Success)のため、DONE等の成功ステータスは定義していません。
-- 2. updated_at: レコード更新時は、アプリケーション層で明示的に現在時刻をセットして更新する設計です。
CREATE TABLE graph_sync_outbox (
    id            TEXT NOT NULL PRIMARY KEY,
    event_type    TEXT NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INTEGER NOT NULL DEFAULT 0 CONSTRAINT retry_count_nonnegative CHECK (retry_count >= 0),
    next_retry_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    error_message TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);

