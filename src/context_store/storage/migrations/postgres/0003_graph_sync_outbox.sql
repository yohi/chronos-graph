CREATE TABLE graph_sync_outbox (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type    VARCHAR(20)  NOT NULL CHECK (event_type IN ('SYNC_MEMORY', 'DELETE_MEMORY')),
    memory_id     UUID         NOT NULL,
    payload       JSONB        NOT NULL DEFAULT '{}',
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING'
                               CHECK (status IN ('PENDING', 'PROCESSING', 'FAILED')),
    retry_count   INT          NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    error_message TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_outbox_status_retry ON graph_sync_outbox (status, next_retry_at ASC);
CREATE INDEX idx_outbox_memory_id ON graph_sync_outbox (memory_id);
