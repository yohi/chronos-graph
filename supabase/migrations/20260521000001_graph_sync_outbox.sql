-- =====================================================================
-- Transactional Outbox Sync (rev.11)
-- =====================================================================

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
CREATE UNIQUE INDEX uq_outbox_pending_processing ON graph_sync_outbox (memory_id) WHERE status IN ('PENDING', 'PROCESSING');

ALTER TABLE graph_sync_outbox ENABLE ROW LEVEL SECURITY;

-- =====================================================================
-- RPC: メモリ UPSERT + Outbox 書き込みをアトミックに実行
-- =====================================================================

CREATE OR REPLACE FUNCTION upsert_memory_with_outbox(
    p_id                  UUID,
    p_content             TEXT,
    p_memory_type         VARCHAR(20),
    p_source_type         VARCHAR(20),
    p_source_metadata     JSONB,
    p_embedding           vector(768),
    p_semantic_relevance  FLOAT,
    p_importance_score    FLOAT,
    p_tags                TEXT[],
    p_project             TEXT,
    p_content_hash        TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_memory_id UUID;
BEGIN
    INSERT INTO memories (
        id, content, memory_type, source_type, source_metadata,
        embedding, semantic_relevance, importance_score,
        tags, project, content_hash
    ) VALUES (
        p_id, p_content, p_memory_type, p_source_type, p_source_metadata,
        p_embedding, p_semantic_relevance, p_importance_score,
        p_tags, p_project, p_content_hash
    )
    ON CONFLICT (id) DO UPDATE SET
        content            = EXCLUDED.content,
        memory_type        = EXCLUDED.memory_type,
        source_type        = EXCLUDED.source_type,
        source_metadata    = EXCLUDED.source_metadata,
        embedding          = EXCLUDED.embedding,
        semantic_relevance = EXCLUDED.semantic_relevance,
        importance_score   = EXCLUDED.importance_score,
        tags               = EXCLUDED.tags,
        project            = EXCLUDED.project,
        content_hash       = EXCLUDED.content_hash,
        updated_at         = NOW()
    WHERE memories.content_hash IS DISTINCT FROM EXCLUDED.content_hash
    RETURNING id INTO v_memory_id;

    IF v_memory_id IS NOT NULL THEN
        INSERT INTO graph_sync_outbox (event_type, memory_id)
        VALUES ('SYNC_MEMORY', v_memory_id)
        ON CONFLICT (memory_id) WHERE status IN ('PENDING', 'PROCESSING') DO NOTHING;
    ELSE
        INSERT INTO graph_sync_outbox (event_type, memory_id)
        VALUES ('SYNC_MEMORY', p_id)
        ON CONFLICT (memory_id) WHERE status IN ('PENDING', 'PROCESSING') DO NOTHING;
    END IF;

    RETURN p_id;
END;
$$;

-- =====================================================================
-- RPC: メモリ削除 + Outbox 書き込みをアトミックに実行
-- =====================================================================

CREATE OR REPLACE FUNCTION delete_memory_with_outbox(
    p_memory_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_meta JSONB;
    affected INTEGER;
BEGIN
    DELETE FROM memories
    WHERE id = p_memory_id
    RETURNING jsonb_build_object(
        'memory_type', memory_type,
        'tags', to_jsonb(tags),
        'project', project
    ) INTO v_meta;
    GET DIAGNOSTICS affected = ROW_COUNT;

    IF affected > 0 THEN
        INSERT INTO graph_sync_outbox (event_type, memory_id, payload)
        VALUES ('DELETE_MEMORY', p_memory_id, COALESCE(v_meta, '{}'));
    END IF;

    RETURN affected > 0;
END;
$$;

GRANT EXECUTE ON FUNCTION upsert_memory_with_outbox(
    UUID, TEXT, VARCHAR, VARCHAR, JSONB, vector, FLOAT, FLOAT,
    TEXT[], TEXT, TEXT
) TO service_role;
GRANT EXECUTE ON FUNCTION delete_memory_with_outbox(UUID) TO service_role;

-- =====================================================================
-- RPC: Worker 側で使用する状態遷移系
-- =====================================================================

CREATE OR REPLACE FUNCTION fetch_pending_outbox(p_limit INT)
RETURNS TABLE (
    id            UUID,
    event_type    VARCHAR(20),
    memory_id     UUID,
    payload       JSONB,
    status        VARCHAR(20),
    retry_count   INT,
    next_retry_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    error_message TEXT
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    IF p_limit IS NULL OR p_limit <= 0 THEN
        RAISE EXCEPTION 'p_limit must be a positive integer';
    END IF;

    RETURN QUERY
    UPDATE graph_sync_outbox o
    SET status = 'PROCESSING', updated_at = NOW()
    WHERE o.id IN (
        SELECT inner_o.id FROM graph_sync_outbox inner_o
        WHERE inner_o.status = 'PENDING'
          AND inner_o.next_retry_at <= NOW()
        ORDER BY inner_o.next_retry_at ASC
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    RETURNING o.id, o.event_type, o.memory_id, o.payload, o.status,
              o.retry_count, o.next_retry_at, o.created_at, o.updated_at, o.error_message;
END;
$$;

CREATE OR REPLACE FUNCTION reset_stuck_processing_outbox(
    p_threshold_seconds INT,
    p_max_retries INT
)
RETURNS INT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    failed_count INT;
    pending_count INT;
BEGIN
    UPDATE graph_sync_outbox
    SET status = 'FAILED',
        error_message = 'Recovered from stuck PROCESSING (max retries)',
        updated_at = NOW()
    WHERE status = 'PROCESSING'
      AND updated_at < NOW() - (p_threshold_seconds || ' seconds')::interval
      AND retry_count + 1 > p_max_retries;
    GET DIAGNOSTICS failed_count = ROW_COUNT;

    UPDATE graph_sync_outbox
    SET status = 'PENDING',
        retry_count = retry_count + 1,
        next_retry_at = NOW() + (POWER(2, retry_count) || ' seconds')::interval,
        updated_at = NOW()
    WHERE status = 'PROCESSING'
      AND updated_at < NOW() - (p_threshold_seconds || ' seconds')::interval;
    GET DIAGNOSTICS pending_count = ROW_COUNT;

    RETURN failed_count + pending_count;
END;
$$;

GRANT EXECUTE ON FUNCTION fetch_pending_outbox(INT) TO service_role;
GRANT EXECUTE ON FUNCTION reset_stuck_processing_outbox(INT, INT) TO service_role;
