"""Tests for chronos_shared.ingestion_mode constants."""

from chronos_shared.ingestion_mode import (
    CHRONOS_INGESTION_MODE_ENV,
    DEFAULT_INGESTION_MODE,
    IngestionMode,
)


def test_default_ingestion_mode() -> None:
    assert DEFAULT_INGESTION_MODE == "selective"
    assert DEFAULT_INGESTION_MODE in ("all", "selective")


def test_env_name() -> None:
    assert CHRONOS_INGESTION_MODE_ENV == "CHRONOS_INGESTION_MODE"


def test_ingestion_mode_literal() -> None:
    value: IngestionMode = "all"
    assert value in ("all", "selective")
