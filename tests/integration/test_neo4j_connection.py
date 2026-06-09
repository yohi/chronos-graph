"""Minimal connectivity test for Neo4j."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_neo4j_connectivity(neo4j_driver):
    try:
        await neo4j_driver.verify_connectivity()
    except Exception as exc:
        pytest.skip(f"Neo4j not reachable: {exc}")
