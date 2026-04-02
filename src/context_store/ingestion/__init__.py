"""Ingestion Pipeline: コンテンツの取り込み・変換・保存パイプライン。"""

from __future__ import annotations

from context_store.ingestion.adapters import (
    ConversationAdapter,
    ManualAdapter,
    RawContent,
    SourceAdapter,
    URLAdapter,
)
from context_store.ingestion.chunker import Chunker
from context_store.ingestion.classifier import ClassificationResult, Classifier
from context_store.ingestion.deduplicator import (
    DeduplicationAction,
    DeduplicationResult,
    Deduplicator,
)
from context_store.ingestion.graph_linker import EdgeType, GraphLinker
from context_store.ingestion.pipeline import IngestionPipeline, IngestionResult

__all__ = [
    "RawContent",
    "SourceAdapter",
    "ConversationAdapter",
    "ManualAdapter",
    "URLAdapter",
    "Chunker",
    "ClassificationResult",
    "Classifier",
    "DeduplicationAction",
    "DeduplicationResult",
    "Deduplicator",
    "EdgeType",
    "GraphLinker",
    "IngestionPipeline",
    "IngestionResult",
]
