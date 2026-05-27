"""SSOT for the ``CHRONOS_INGESTION_MODE`` environment variable.

This module is the single source of truth for the type, default value, and
environment variable name of the hybrid ingestion mode setting. Both
``context_store.config.Settings`` and ``mcp_gateway.config.GatewaySettings``
import from here to guarantee consistency across the two independent
processes.

Placement rationale: ``mcp_gateway/upstream/context_store_client.py`` enforces
"the gateway must NOT import anything from ``context_store``". Placing this
SSOT under either subsystem would force a cross-package import. Hence the
module lives in its own top-level package ``chronos_shared``.
"""

from __future__ import annotations

from typing import Final, Literal

IngestionMode = Literal["all", "selective"]
DEFAULT_INGESTION_MODE: Final[IngestionMode] = "selective"
CHRONOS_INGESTION_MODE_ENV: Final[str] = "CHRONOS_INGESTION_MODE"
