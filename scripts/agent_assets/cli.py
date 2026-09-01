# mypy: disable-error-code=import-not-found

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_assets.bundle import build_bundle
from agent_assets.hooks import PluginRegistryPrerequisiteError
from agent_assets.models import (
    AgentId,
    ExecutionMode,
    IngestionMode,
    SyncPlan,
    SyncRequest,
    parse_agent_csv,
    resolve_codex_home,
    validate_command,
)
from agent_assets.transaction import ApplyError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sync_agent_assets.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    canonicalize = subparsers.add_parser("canonicalize")
    canonicalize.add_argument(
        "--agents",
        required=True,
        help="Comma-separated supported Agent IDs",
    )

    sync = subparsers.add_parser("sync")
    sync.add_argument("--repo-root", required=True, type=Path)
    sync.add_argument("--mode", required=True, choices=["production", "dry-run"])
    sync.add_argument(
        "--ingestion-mode",
        required=True,
        choices=["selective", "all"],
    )
    sync.add_argument(
        "--agent",
        required=True,
        action="append",
        choices=[AgentId.CLAUDECODE, AgentId.CODEX, AgentId.OPENCODE],
        help="Canonical Agent ID (repeat for each agent)",
    )
    return parser


def _parse_sync_args(raw: list[str] | None = None) -> SyncRequest:
    args = _build_parser().parse_args(raw)
    home = Path.home()
    if args.command == "canonicalize":
        return SyncRequest(
            command=validate_command(args.command),
            repo_root=Path.cwd(),
            home=home,
            mode=ExecutionMode.DRY_RUN,
            ingestion_mode=IngestionMode.SELECTIVE,
            agent_ids=parse_agent_csv(args.agents),
            codex_home=resolve_codex_home(home),
        )

    agent_ids = tuple(AgentId(value) for value in args.agent)
    return SyncRequest(
        command=validate_command(args.command),
        repo_root=args.repo_root.resolve(),
        home=home,
        mode=ExecutionMode(args.mode),
        ingestion_mode=IngestionMode(args.ingestion_mode),
        agent_ids=agent_ids,
        codex_home=resolve_codex_home(home),
    )


def _print_canonical_agents(request: SyncRequest) -> int:
    for agent_id in request.agent_ids:
        print(agent_id.value)
    return 0


def _print_plan(plan: SyncPlan) -> None:
    print(f"bundle-digest:{plan.bundle.digest}")
    for target in sorted(plan.targets, key=lambda item: item.path.as_posix()):
        print(f"{target.path}:{target.action.value}:sha256={plan.bundle.digest}")
    for diagnostic in sorted(plan.diagnostics, key=lambda item: item.render()):
        print(diagnostic.render())


def run_sync(request: SyncRequest) -> int:
    """Run the entire selected-Agent synchronization lifecycle."""
    from agent_assets.preflight import preflight

    bundle = build_bundle(request.repo_root / "agent-assets")
    plan = preflight(request, bundle)
    if request.mode is ExecutionMode.DRY_RUN:
        _print_plan(plan)
        return 0

    from agent_assets.transaction import SystemFileOperations, apply_sync

    apply_sync(plan, SystemFileOperations())
    _print_plan(plan)
    return 0


def main(raw: list[str] | None = None) -> int:
    from agent_assets.models import AgentSelectionError
    from agent_assets.preflight import MarkerError, PreflightCollisionError

    try:
        request = _parse_sync_args(raw)
    except AgentSelectionError as error:
        print(f"canonicalize:reject:.:{error}", file=sys.stderr)
        return 2

    if request.command == "canonicalize":
        return _print_canonical_agents(request)
    try:
        return run_sync(request)
    except PreflightCollisionError as error:
        print(error.diagnostic().render(), file=sys.stderr)
        return 2
    except PluginRegistryPrerequisiteError as error:
        print(f"preflight:reject:.:{error.category}", file=sys.stderr)
        return 2
    except MarkerError as error:
        print(f"preflight:reject:.:{error.code}", file=sys.stderr)
        return 2
    except ApplyError as error:
        print(
            f"apply:reject:.:{error.category}:rollback={error.rollback.category}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
