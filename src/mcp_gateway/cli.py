"""Universal Evaluator CLI: `python -m mcp_gateway evaluate --json-io`.

stdin から JSON を読み、CompositeEvaluator で評価し、stdout にちょうど 1 行の
Decision JSON を書く。例外時も stdout には fallback ask JSON を必ず吐く。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Literal, NoReturn, cast, override

from mcp_gateway.policy.composite import CompositeEvaluator
from mcp_gateway.policy.engine import PolicyEngine
from mcp_gateway.policy.llm_evaluator import LlmEvaluator
from mcp_gateway.policy.loader import load_policy
from mcp_gateway.policy.memory_client import MemoryClient
from mcp_gateway.policy.models_evaluator import Decision, ToolCallInput

logger = logging.getLogger("chronos_evaluator.cli")

_FALLBACK_ASK = Decision(
    decision="ask",
    ask_message="System evaluation failed. Human confirmation required.",
)


class _JsonIoArgumentParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _configure_stderr_logging(level: str = "WARNING") -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root.addHandler(handler)
    try:
        root.setLevel(level)
    except ValueError:
        root.setLevel("WARNING")
        logger.warning("Invalid log level %r, falling back to WARNING", level)
    for name in ("httpx", "httpcore", "anthropic", "asyncio"):
        logging.getLogger(name).setLevel("WARNING")


def _read_input(stream: IO[str]) -> ToolCallInput:
    raw = stream.read()
    if not raw or not raw.strip():
        raise ValueError("empty stdin")
    parsed = cast(object, json.loads(raw))
    if not isinstance(parsed, Mapping):
        raise ValueError(f"top-level must be object, got {type(parsed).__name__}")
    data = cast(Mapping[str, object], parsed)
    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    context = data.get("context", {})
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("tool_name is required")
    if not isinstance(tool_input, dict):
        raise ValueError("tool_input must be object")
    if not isinstance(context, dict):
        raise ValueError("context must be object")
    return ToolCallInput(
        tool_name=tool_name,
        tool_input=dict(cast(Mapping[str, object], tool_input)),
        context=dict(cast(Mapping[str, object], context)),
    )


def _write_decision(decision: Decision, stream: IO[str]) -> None:
    json.dump(decision.to_dict(), stream, ensure_ascii=False)
    _ = stream.write("\n")
    stream.flush()


def _emit_fallback_ask(stream: IO[str]) -> None:
    _write_decision(_FALLBACK_ASK, stream)


def _fallback_mode_from_env() -> Literal["allow", "ask"]:
    value = os.getenv("CHRONOS_EVALUATOR_FALLBACK", "allow")
    if value == "ask":
        return "ask"
    if value == "allow":
        return "allow"
    logger.warning("Unknown CHRONOS_EVALUATOR_FALLBACK=%r, defaulting to 'allow'", value)
    return "allow"


def _build_composite_evaluator(policy_path: Path) -> CompositeEvaluator:
    policy = load_policy(policy_path)
    engine = PolicyEngine(policy)
    return CompositeEvaluator(
        engine=engine,
        memory_client=MemoryClient.from_env(),
        llm_evaluator=LlmEvaluator.from_env(),
        default_intent=os.getenv("CHRONOS_EVALUATOR_DEFAULT_INTENT", "default"),
        default_agent_id=os.getenv("CHRONOS_EVALUATOR_DEFAULT_AGENT_ID", "claude-code"),
        fallback_when_llm_not_configured=_fallback_mode_from_env(),
    )


def main(argv: list[str] | None = None) -> int:
    _configure_stderr_logging(os.getenv("CHRONOS_EVALUATOR_LOG_LEVEL", "WARNING"))

    parser = _JsonIoArgumentParser(prog="mcp_gateway evaluate")
    _ = parser.add_argument(
        "--json-io",
        action="store_true",
        required=True,
        help="enable JSON I/O mode (currently the only supported mode)",
    )
    _ = parser.add_argument(
        "--policy-path",
        type=Path,
        default=Path(os.getenv("CHRONOS_EVALUATOR_POLICY_PATH", "intents.yaml")),
    )
    try:
        args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    except ValueError:
        # Our custom parser raises ValueError instead of SystemExit
        _emit_fallback_ask(sys.stdout)
        return 2

    arg_values = cast(dict[str, object], vars(args))
    policy_path = arg_values["policy_path"]
    if not isinstance(policy_path, Path):
        raise TypeError("--policy-path must parse to pathlib.Path")

    try:
        input_ = _read_input(sys.stdin)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("stdin parse failed: %s", exc)
        _emit_fallback_ask(sys.stdout)
        return 2
    except (Exception, KeyboardInterrupt):
        traceback.print_exc(file=sys.stderr)
        _emit_fallback_ask(sys.stdout)
        return 2

    try:
        evaluator = _build_composite_evaluator(policy_path)
        decision = asyncio.run(evaluator.evaluate(input_))
        _write_decision(decision, sys.stdout)
        return 0
    except (Exception, asyncio.CancelledError, KeyboardInterrupt):
        traceback.print_exc(file=sys.stderr)
        _emit_fallback_ask(sys.stdout)
        return 2
