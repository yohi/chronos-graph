CREATE OR REPLACE FUNCTION get_embedding_dimension()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public
AS $$
    SELECT COALESCE(
        (SELECT vector_dims(embedding) FROM memories WHERE embedding IS NOT NULL ORDER BY id LIMIT 1),
        (SELECT a.atttypmod
         FROM pg_catalog.pg_class c
         JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
         JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relname = 'memories'
           AND n.nspname = 'public'
           AND a.attname = 'embedding'
           AND a.atttypid = (SELECT oid FROM pg_catalog.pg_type WHERE typname = 'vector')
         LIMIT 1)
    );
$$;
