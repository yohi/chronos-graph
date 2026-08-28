from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_assets.bundle import build_bundle
from agent_assets.models import (
    AgentId,
    ExecutionMode,
    IngestionMode,
    SyncRequest,
    parse_agent_csv,
)


def _parse_sync_args(raw: list[str] | None = None) -> SyncRequest:
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

    args = parser.parse_args(raw)
    if args.command == "canonicalize":
        return SyncRequest(
            repo_root=Path.cwd(),
            home=Path.home(),
            mode=ExecutionMode.DRY_RUN,
            ingestion_mode=IngestionMode.SELECTIVE,
            agent_ids=parse_agent_csv(args.agents),
        )

    agent_ids = tuple(AgentId(value) for value in args.agent)
    return SyncRequest(
        repo_root=args.repo_root.resolve(),
        home=Path.home(),
        mode=ExecutionMode(args.mode),
        ingestion_mode=IngestionMode(args.ingestion_mode),
        agent_ids=agent_ids,
    )


def _print_canonical_agents(request: SyncRequest) -> int:
    for agent_id in request.agent_ids:
        print(agent_id.value)
    return 0


def _print_dry_run_plan(request: SyncRequest) -> int:
    bundle = build_bundle(request.repo_root / "agent-assets")
    print(f"bundle-digest:{bundle.digest}")
    for agent_id in request.agent_ids:
        print(f"agent:{agent_id.value}:planned:sync")
    return 0


def run_sync(request: SyncRequest) -> int:
    """Run the entire selected-Agent synchronization lifecycle."""
    from agent_assets.preflight import preflight
    from agent_assets.transaction import SystemFileOperations, apply_sync

    bundle = build_bundle(request.repo_root / "agent-assets")
    plan = preflight(request, bundle)
    if request.mode is ExecutionMode.DRY_RUN:
        print(f"bundle-digest:{bundle.digest}")
        for target in plan.targets:
            print(f"{target.path}:{target.action.value}")
        return 0
    apply_sync(plan, SystemFileOperations())
    print("Synchronization complete")
    return 0


def main(raw: list[str] | None = None) -> int:
    request = _parse_sync_args(raw)
    if len(sys.argv) > 1 and sys.argv[1] == "canonicalize":
        return _print_canonical_agents(request)
    return run_sync(request)


if __name__ == "__main__":
    sys.exit(main())
