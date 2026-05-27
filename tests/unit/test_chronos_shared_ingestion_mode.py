"""chronos_shared.ingestion_mode の SSOT 契約検証。"""

from __future__ import annotations

from typing import get_args


def test_default_ingestion_mode_is_selective() -> None:
    from chronos_shared.ingestion_mode import DEFAULT_INGESTION_MODE

    assert DEFAULT_INGESTION_MODE == "selective"


def test_env_var_name_is_chronos_ingestion_mode() -> None:
    from chronos_shared.ingestion_mode import CHRONOS_INGESTION_MODE_ENV

    assert CHRONOS_INGESTION_MODE_ENV == "CHRONOS_INGESTION_MODE"


def test_ingestion_mode_literal_has_exactly_two_values() -> None:
    """`IngestionMode` は Literal["all", "selective"] であること。"""
    from chronos_shared.ingestion_mode import IngestionMode

    assert set(get_args(IngestionMode)) == {"all", "selective"}


def test_module_exposes_only_three_public_symbols() -> None:
    """SSOT モジュールは 3 シンボルのみ公開する (それ以外は意図しない拡張)。"""
    import chronos_shared.ingestion_mode as mod

    public = {name for name in dir(mod) if not name.startswith("_")}
    expected = {"CHRONOS_INGESTION_MODE_ENV", "DEFAULT_INGESTION_MODE", "IngestionMode"}
    assert expected.issubset(public)
    allowed = expected | {"annotations", "Final", "Literal"}
    extras = public - allowed
    assert extras == set(), f"unexpected public symbols: {extras}"
