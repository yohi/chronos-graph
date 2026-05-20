-- ============================================================
-- vector_search: pgvector の <=> (cosine distance) を使って
-- 上位 K 件取得。score = 1 - distance でコサイン類似度を返す。
-- p_project が NULL なら全プロジェクト対象。
-- ============================================================
CREATE OR REPLACE FUNCTION vector_search(
    query_embedding vector(768),
    match_count     integer,
    p_project       text DEFAULT NULL
)
RETURNS TABLE (
    id                 uuid,
    content            text,
    memory_type        varchar,
    source_type        varchar,
    source_metadata    jsonb,
    embedding          vector(768),
    semantic_relevance float,
    importance_score   float,
    access_count       integer,
    last_accessed_at   timestamptz,
    created_at         timestamptz,
    updated_at         timestamptz,
    archived_at        timestamptz,
    tags               text[],
    project            text,
    content_hash       text,
    score              float
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT
        m.id, m.content, m.memory_type, m.source_type, m.source_metadata,
        m.embedding, m.semantic_relevance, m.importance_score, m.access_count,
        m.last_accessed_at, m.created_at, m.updated_at, m.archived_at,
        m.tags, m.project, m.content_hash,
        (1 - (m.embedding <=> query_embedding))::float AS score
    FROM memories m
    WHERE m.archived_at IS NULL
      AND m.embedding IS NOT NULL
      AND (p_project IS NULL OR m.project = p_project)
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ============================================================
-- list_projects: DISTINCT project をサーバサイドで取得。
-- ============================================================
CREATE OR REPLACE FUNCTION list_projects()
RETURNS TABLE (project text)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT DISTINCT m.project
    FROM memories m
    WHERE m.project IS NOT NULL AND m.project <> '';
$$;

-- ============================================================
-- increment_memory_access_count: アトミック increment + 時刻更新
-- ============================================================
CREATE OR REPLACE FUNCTION increment_memory_access_count(
    p_memory_id uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    affected integer;
BEGIN
    UPDATE memories
       SET access_count     = access_count + 1,
           last_accessed_at = NOW(),
           updated_at       = NOW()
     WHERE id = p_memory_id;

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected > 0;
END;
$$;

-- 権限付与: RLS 未適用のため service_role のみ
GRANT EXECUTE ON FUNCTION vector_search(vector, integer, text)   TO service_role;
GRANT EXECUTE ON FUNCTION list_projects()                         TO service_role;
GRANT EXECUTE ON FUNCTION increment_memory_access_count(uuid)    TO service_role;
