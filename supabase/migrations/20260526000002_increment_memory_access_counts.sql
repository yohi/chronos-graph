-- ============================================================
-- increment_memory_access_counts: bulk variant of
-- increment_memory_access_count. Avoids N HTTPS round trips
-- after every search by accepting an array of UUIDs.
-- Returns the number of rows actually updated.
-- ============================================================
CREATE OR REPLACE FUNCTION increment_memory_access_counts(
    p_memory_ids uuid[]
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    affected integer;
BEGIN
    IF p_memory_ids IS NULL OR array_length(p_memory_ids, 1) IS NULL THEN
        RETURN 0;
    END IF;

    UPDATE memories
       SET access_count     = access_count + 1,
           last_accessed_at = NOW(),
           updated_at       = NOW()
     WHERE id = ANY(p_memory_ids);

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END;
$$;

GRANT EXECUTE ON FUNCTION increment_memory_access_counts(uuid[]) TO service_role;
