-- 設計方針:
-- 1. status: 成功したイベントは物理削除される設計(Delete-on-Success)のため、DONE等の成功ステータスは定義していません。
-- 2. updated_at: レコード更新時は、アプリケーション層で明示的に NOW() をセットして更新する設計です。
CREATE TABLE graph_sync_outbox (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    VARCHAR(20)  NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     UUID         NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}',
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                               CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INT          NOT NULL DEFAULT 0 CONSTRAINT retry_count_nonnegative CHECK (retry_count >= 0),
    next_retry_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    error_message TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at ASC);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);

ALTER TABLE graph_sync_outbox ENABLE ROW LEVEL SECURITY;
