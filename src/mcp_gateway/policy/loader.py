"""YAML → GatewayPolicy loader. Errors are normalized to PolicyError."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mcp_gateway.errors import PolicyError
from mcp_gateway.policy.models import GatewayPolicy

_MAX_POLICY_FILE_SIZE = 1 * 1024 * 1024  # 1 MB


def load_policy(path: Path) -> GatewayPolicy:
    """Read intents.yaml and return a validated GatewayPolicy.

    Any parse / schema / reference error is wrapped in PolicyError so that the
    server entrypoint can fail fast with a single exception type.
    """
    # Fail-fast: ファイルサイズ上限チェック (DoS 防御)
    try:
        file_size = path.stat().st_size
    except OSError as e:
        raise PolicyError(f"failed to stat policy file {path}: {e}") from e
    if file_size > _MAX_POLICY_FILE_SIZE:
        raise PolicyError(
            f"policy file {path} exceeds size limit "
            f"({file_size} bytes > {_MAX_POLICY_FILE_SIZE} bytes)"
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PolicyError(f"failed to read policy file {path}: {e}") from e

    try:
        data: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as e:
        raise PolicyError(f"failed to parse YAML at {path}: {e}") from e

    if not isinstance(data, dict):
        raise PolicyError(f"policy root must be a mapping, got {type(data).__name__}")

    try:
        return GatewayPolicy.model_validate(data)
    except ValidationError as e:
        raise PolicyError(f"invalid policy at {path}: {e}") from e
