"""Ensure RetrievalPipeline.create_for_dashboard wires the minimal stack."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from context_store.retrieval.pipeline import RetrievalPipeline


def test_create_for_dashboard_returns_pipeline_with_search() -> None:
    storage = MagicMock(name="StorageAdapter")
    graph = MagicMock(name="GraphAdapter")
    settings = MagicMock(
        embedding_provider="openai",
        openai_api_key=MagicMock(get_secret_value=MagicMock(return_value="fake-key")),
        graph_max_logical_depth=2,
        graph_fanout_limit=10,
        graph_max_physical_hops=4,
    )

    with patch("context_store.embedding.create_embedding_provider") as mock_create:
        mock_create.return_value = MagicMock()
        pipeline = RetrievalPipeline.create_for_dashboard(
            storage=storage, graph=graph, settings=settings
        )

    assert isinstance(pipeline, RetrievalPipeline)
    assert hasattr(pipeline, "search")
