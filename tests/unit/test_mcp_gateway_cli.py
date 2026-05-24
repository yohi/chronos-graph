"""Tests for mcp_gateway.cli (stdin / stdout / exit codes)."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.cli import _fallback_mode_from_env, main
from mcp_gateway.policy.models_evaluator import Decision

PatchedComposite = tuple[MagicMock, MagicMock]


def _run_cli_with_input(
    payload: str,
    *,
    argv: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run cli.main with patched stdin/stdout/stderr/env; return (code, stdout, stderr)."""
    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        patch("sys.stdin", stdin),
        patch("sys.stdout", stdout),
        patch("sys.stderr", stderr),
        patch.dict("os.environ", env or {}, clear=False),
    ):
        code = main(["--json-io"] if argv is None else argv)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture(autouse=True)
def _patch_composite() -> Iterator[PatchedComposite]:
    """Patch CompositeEvaluator.from_env to return a mock by default."""
    fake = MagicMock()
    fake.evaluate = AsyncMock(return_value=Decision(decision="allow"))
    with patch("mcp_gateway.cli._build_composite_evaluator", return_value=fake) as m:
        yield m, fake


def _loads_json_object(text: str) -> dict[str, object]:
    parsed = cast(object, json.loads(text))
    assert isinstance(parsed, dict)
    return cast(dict[str, object], parsed)


def test_allow_path_writes_single_line_json_and_exit_0(
    _patch_composite: PatchedComposite,
) -> None:
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    code, out, _ = _run_cli_with_input(payload)
    assert code == 0
    assert out.count("\n") == 1
    assert _loads_json_object(out.strip()) == {"decision": "allow"}


def test_deny_path_includes_reason(_patch_composite: PatchedComposite) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(return_value=Decision(decision="deny", reason="bad"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "rm"}})
    code, out, _ = _run_cli_with_input(payload)
    assert code == 0
    assert _loads_json_object(out.strip()) == {"decision": "deny", "reason": "bad"}


def test_ask_path_includes_message(_patch_composite: PatchedComposite) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(return_value=Decision(decision="ask", ask_message="confirm"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {}})
    code, out, _ = _run_cli_with_input(payload)
    assert code == 0
    assert _loads_json_object(out.strip()) == {"decision": "ask", "ask_message": "confirm"}


def test_empty_stdin_emits_fallback_ask_and_exit_2() -> None:
    code, out, _ = _run_cli_with_input("")
    assert code == 2
    body = _loads_json_object(out.strip())
    assert body["decision"] == "ask"
    assert "System evaluation failed" in str(body["ask_message"])


def test_invalid_json_emits_fallback_ask_and_exit_2() -> None:
    code, out, _ = _run_cli_with_input("not-json")
    assert code == 2
    body = _loads_json_object(out.strip())
    assert body["decision"] == "ask"


def test_unexpected_exception_emits_fallback_ask_and_exit_2(
    _patch_composite: PatchedComposite,
) -> None:
    _, fake = _patch_composite
    fake.evaluate = AsyncMock(side_effect=RuntimeError("boom"))
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    code, out, err = _run_cli_with_input(payload)
    assert code == 2
    body = _loads_json_object(out.strip())
    assert body["decision"] == "ask"
    # traceback must go to stderr, never stdout
    assert "Traceback" in err
    assert "Traceback" not in out


def test_argparse_error_emits_fallback_ask_and_exit_2() -> None:
    # --json-io is required; omitting it triggers argparse error
    code, out, err = _run_cli_with_input('{"tool_name": "bash"}', argv=[])
    # main() must catch SystemExit and return 2 while writing fallback JSON
    assert code == 2
    body = _loads_json_object(out.strip())
    assert body["decision"] == "ask"
    assert "System evaluation failed" in str(body["ask_message"])


def test_logger_output_goes_to_stderr_only(_patch_composite: PatchedComposite) -> None:
    # Use invalid JSON to guarantee a log line on stderr; assert both streams.
    code, out, err = _run_cli_with_input("not-json")
    assert code == 2
    # Single JSON line on stdout (fallback ask)
    assert out.count("\n") == 1
    # Positive assertion: log line goes to stderr
    assert "stdin parse failed" in err
    # Negative assertion: same log line never leaks to stdout
    assert "stdin parse failed" not in out


def test_unknown_fallback_env_warns(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid CHRONOS_EVALUATOR_FALLBACK triggers a logger.warning before defaulting to 'allow'."""
    with caplog.at_level(logging.WARNING, logger="chronos_evaluator.cli"):
        with patch.dict("os.environ", {"CHRONOS_EVALUATOR_FALLBACK": "invalid_value"}):
            result = _fallback_mode_from_env()
    assert result == "allow"
    assert "Unknown CHRONOS_EVALUATOR_FALLBACK='invalid_value'" in caplog.text


def test_invalid_log_level_emits_fallback_and_exit_2() -> None:
    """Invalid CHRONOS_EVALUATOR_LOG_LEVEL must not crash the CLI.
    Fallback ask JSON and exit code 2 are still emitted."""
    with patch.dict("os.environ", {"CHRONOS_EVALUATOR_LOG_LEVEL": "INVALID"}):
        code, out, _ = _run_cli_with_input('{"tool_name":"bash"}', argv=[])
    assert code == 2
    body = _loads_json_object(out.strip())
    assert body["decision"] == "ask"
    assert "System evaluation failed" in str(body["ask_message"])


def test_main_returns_int_not_calls_sys_exit(_patch_composite: PatchedComposite) -> None:
    """main() should *return* the exit code; the __main__ shim invokes sys.exit."""
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "ls"}})
    stdin = io.StringIO(payload)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
        code = main(["--json-io"])
    assert isinstance(code, int)
