"""End-to-end subprocess tests for `python -m mcp_gateway evaluate`."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

MINIMAL_POLICY = textwrap.dedent(
    """
    version: 1
    output_filters:
      none:
        type: none
    intents:
      default:
        description: default intent
        allowed_tools: ["bash"]
        output_filter: none
        guardrails:
          bash:
            params:
              command:
                type: string
                max_length: 4000
                pattern: "^(?!rm -rf /).*$"
    agents:
      claude-code:
        allowed_intents: ["default"]
    approvers: []
    """
)


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    path = tmp_path / "intents.yaml"
    _ = path.write_text(MINIMAL_POLICY, encoding="utf-8")
    return path


def _loads_json_object(text: str) -> dict[str, object]:
    parsed = cast(object, json.loads(text))
    assert isinstance(parsed, dict)
    return cast(dict[str, object], parsed)


def _build_env(
    policy: Path | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CHRONOS_EVALUATOR_API_KEY": "",
            "CHRONOS_DASHBOARD_URL": "",
            "CHRONOS_EVALUATOR_FALLBACK": "allow",
            "CHRONOS_EVALUATOR_DEFAULT_INTENT": "default",
            "CHRONOS_EVALUATOR_DEFAULT_AGENT_ID": "claude-code",
        }
    )
    if policy is not None:
        env["CHRONOS_EVALUATOR_POLICY_PATH"] = str(policy)
    env.update(overrides or {})
    return env


def _run_cli(
    policy: Path,
    payload: Mapping[str, object],
    env_overrides: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _build_env(policy, env_overrides)
    command = (
        "uv run python -m mcp_gateway evaluate --json-io --policy-path "
        f"{shlex.quote(str(policy))}"
    )
    return subprocess.run(  # noqa: S603, S607
        ["bash", "-lc", command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def test_cli_evaluate_allow_path(policy_path: Path) -> None:
    result = _run_cli(policy_path, {"tool_name": "bash", "tool_input": {"command": "ls"}})
    assert result.returncode == 0
    assert result.stdout.count("\n") == 1
    body = _loads_json_object(result.stdout.strip())
    assert body["decision"] == "allow"
    assert "evaluator config" not in result.stdout


def test_cli_evaluate_deny_path(policy_path: Path) -> None:
    result = _run_cli(policy_path, {"tool_name": "bash", "tool_input": {"command": "rm -rf /"}})
    assert result.returncode == 0
    body = _loads_json_object(result.stdout.strip())
    assert body["decision"] == "deny"


def test_cli_evaluate_invalid_stdin(policy_path: Path) -> None:
    env = _build_env(policy_path)
    command = (
        "uv run python -m mcp_gateway evaluate --json-io --policy-path "
        f"{shlex.quote(str(policy_path))}"
    )
    result = subprocess.run(  # noqa: S603, S607
        ["bash", "-lc", command],
        input="not-json",
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout.count("\n") == 1
    body = _loads_json_object(result.stdout.strip())
    assert body["decision"] == "ask"


def test_cli_evaluate_missing_json_io_still_emits_single_json_line(policy_path: Path) -> None:
    env = _build_env(policy_path)
    command = f"uv run python -m mcp_gateway evaluate --policy-path {shlex.quote(str(policy_path))}"
    result = subprocess.run(  # noqa: S603, S607
        ["bash", "-lc", command],
        input=json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}}),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout.count("\n") == 1
    body = _loads_json_object(result.stdout.strip())
    assert body["decision"] == "ask"
