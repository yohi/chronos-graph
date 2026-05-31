"""Storage → Neo4j リカバリ CLI。

Usage:
    python scripts/sync_storage_to_neo4j.py --catchup
    python scripts/sync_storage_to_neo4j.py --full [--yes]
    python scripts/sync_storage_to_neo4j.py --full --dry-run --chunk-size 500

WARNING — --full モードのダウンタイム:
    --full は Neo4j の全 :Memory ノードを DETACH DELETE してから再構築する。
    実行中はグラフ traversal が空結果を返すため、メンテナンス窓口内でのみ実行。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logger = logging.getLogger(__name__)

_FULL_CONFIRM_PROMPT = (
    "[!] --full は Neo4j の全 :Memory ノードを DETACH DELETE してから再構築します。\n"
    "    実行中はグラフ traversal が空結果を返します。続行しますか? [yes/NO]: "
)


def _confirm_full(assume_yes: bool) -> bool:
    if assume_yes:
        logger.warning("--yes が指定されたため対話確認をスキップして --full を実行")
        return True
    if not sys.stdin.isatty():
        logger.error(
            "--full は TTY 経由か --yes 明示が必要です。バッチ実行時は --yes を付与してください。"
        )
        return False
    answer = input(_FULL_CONFIRM_PROMPT).strip().lower()
    return answer == "yes"


async def _run_full(chunk_size: int, dry_run: bool) -> int:
    from context_store.config import Settings

    settings = Settings()
    if dry_run:
        logger.info("Dry run: full sync would process chunks of %d", chunk_size)
        return 0
    from context_store.storage.factory import create_storage_with_outbox
    from context_store.sync.graph_sync import GraphSyncService

    storage, graph, cache, _ = await create_storage_with_outbox(settings)
    try:
        if graph is None:
            raise RuntimeError("graph_enabled=true required for sync")
        svc = GraphSyncService(graph_adapter=graph, storage_adapter=storage)
        logger.warning("Full sync 開始: Neo4j を完全パージします")
        await graph.execute_write("MATCH (m:Memory) DETACH DELETE m", {})
        total = await svc.full_sync_from_storage(chunk_size=chunk_size)
        logger.info("Full sync done: %d memories", total)
        return total
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


async def _run_catchup(dry_run: bool) -> int:
    from context_store.config import Settings

    settings = Settings()
    from context_store.storage.factory import create_storage_with_outbox

    storage, graph, cache, worker = await create_storage_with_outbox(settings)
    try:
        if worker is None:
            raise RuntimeError("graph_sync_mode='async_outbox' required for catchup")
        return await worker.run_catchup(dry_run=dry_run)
    finally:
        await storage.dispose()
        if graph:
            await graph.dispose()
        await cache.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Storage → Neo4j リカバリ CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="全件再同期（ダウンタイムあり）")
    group.add_argument("--catchup", action="store_true", help="Outbox の未処理イベントを処理")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="--full 実行時の対話確認をスキップ",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level)
    if args.full:
        if not args.dry_run and not _confirm_full(assume_yes=args.yes):
            logger.info("--full を中止しました")
            return 1
        asyncio.run(_run_full(args.chunk_size, args.dry_run))
    else:
        asyncio.run(_run_catchup(args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
