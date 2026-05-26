-- ============================================================
-- vector_search_brief: same as vector_search but omits the
-- embedding column from the return row. Reduces per-row payload
-- by ~10KB (768 floats × JSON encoding overhead) for clients
-- that only need the score + memory metadata for display.
-- The original vector_search is kept for backward compatibility.
-- ============================================================
CREATE OR REPLACE FUNCTION vector_search_brief(
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
        m.semantic_relevance, m.importance_score, m.access_count,
        m.last_accessed_at, m.created_at, m.updated_at, m.archived_at,
        m.tags, m.project, m.content_hash,
        (1 - (m.embedding <=> query_embedding))::float AS score
    FROM memories m
    WHERE m.archived_at IS NULL
      AND m.embedding IS NOT NULL
      AND (p_project IS NULL OR m.project = p_project)
    ORDER BY m.embedding <=> query_embedding
    LIMIT COALESCE(GREATEST(match_count, 0), 0);
$$;

GRANT EXECUTE ON FUNCTION vector_search_brief(vector, integer, text) TO service_role;
