from __future__ import annotations

import re
from pathlib import Path


def test_vector_search_rpc_returns_embedding_column() -> None:
    sql = Path("supabase/migrations/20260518000002_rpc_functions.sql").read_text()

    match = re.search(r"RETURNS TABLE\s*\((?P<columns>.*?)\)\s*LANGUAGE", sql, re.S)
    assert match is not None
    returns_table = match.group("columns")
    function_body = sql.split("AS $$", 1)[1].split("$$;", 1)[0]

    assert re.search(r"\bembedding\s+vector\b", returns_table) is not None
    assert "m.embedding" in function_body


def test_list_projects_rpc_does_not_filter_archived_projects() -> None:
    sql = Path("supabase/migrations/20260518000002_rpc_functions.sql").read_text()

    match = re.search(
        r"CREATE OR REPLACE FUNCTION list_projects\(\).*?AS \$\$(?P<body>.*?)\$\$;",
        sql,
        re.S,
    )
    assert match is not None
    function_body = match.group("body")

    assert "m.project IS NOT NULL" in function_body
    assert "m.project <> ''" in function_body
    assert re.search(r"\bm\.archived_at\s+IS\s+NULL\b", function_body, re.I) is None


def test_get_embedding_dimension_rpc_grants_service_role() -> None:
    sql = Path("supabase/migrations/20260519000001_get_embedding_dimension.sql").read_text()

    assert "CREATE OR REPLACE FUNCTION get_embedding_dimension()" in sql
    assert (
        re.search(
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+get_embedding_dimension\(\)\s+TO\s+service_role",
            sql,
            re.I,
        )
        is not None
    )

    # ロジック骨格の回帰検出: ORDER BY id LIMIT 1、pg_catalog 結合、型フィルタ
    assert re.search(r"ORDER\s+BY\s+id\s+LIMIT\s+1", sql, re.I) is not None
    assert re.search(r"pg_catalog\.pg_class", sql, re.I) is not None
    assert re.search(r"pg_catalog\.pg_attribute", sql, re.I) is not None
    assert re.search(r"pg_catalog\.pg_namespace", sql, re.I) is not None
    assert (
        re.search(
            r"a\.atttypid\s*=\s*\(SELECT\s+oid\s+FROM\s+pg_catalog\.pg_type\s+WHERE\s+typname\s*=\s*'vector'\)",
            sql,
            re.I,
        )
        is not None
    )
