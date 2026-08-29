#!/usr/bin/env python3
"""Thin executable entry point for agent asset synchronization."""

from __future__ import annotations

import sys
from pathlib import Path

# noqa: I001

_scripts = Path(__file__).resolve().parent

if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from agent_assets.cli import main  # noqa: E402, I001


if __name__ == "__main__":
    sys.exit(main())
