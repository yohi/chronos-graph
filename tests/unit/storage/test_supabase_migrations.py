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
