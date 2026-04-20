#!/usr/bin/env python3
"""
Migrate vector dimensions by re-embedding all memories.
Usage: uv run python scripts/migrate_dimension.py [--force]
"""

import argparse
import asyncio
import logging
import os
import sys

# Add src to sys.path to ensure we can import context_store
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from context_store.config import Settings
    from context_store.embedding import create_embedding_provider
    from context_store.storage.factory import _create_storage_adapter
    from context_store.storage.protocols import MemoryFilters
except ImportError as e:
    print(
        f"Error: Could not import context_store modules. "
        f"Make sure you are running from the project root. {e}",
        file=sys.stderr,
    )
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stderr
)
logger = logging.getLogger(__name__)


async def migrate(force: bool = False) -> None:
    logger.info("Starting dimension migration...")
    settings = Settings()

    # We bypass Orchestrator to avoid the dimension check at startup.
    # We use the private _create_storage_adapter because it's a direct way to
    # get a storage instance without triggering the system-wide validation
    # that happens in Orchestrator.initialize().
    storage = await _create_storage_adapter(settings)
    embedding_provider = create_embedding_provider(settings)

    try:
        stored_dim = await storage.get_vector_dimension()
        current_dim = embedding_provider.dimension
        logger.info(f"Storage dimension: {stored_dim}")
        logger.info(f"Current provider dimension: {current_dim}")

        if stored_dim == current_dim and not force:
            logger.info(
                "Dimensions already match. No migration needed. Use --force to re-embed anyway."
            )
            return

        # Update vectors_metadata for SQLite BEFORE processing memories.
        # This is necessary because update_memory checks the stored dimension.
        if settings.storage_backend == "sqlite":
            logger.info(f"Updating vectors_metadata to dimension {current_dim}...")
            try:
                import aiosqlite  # type: ignore

                db_path = os.path.expanduser(settings.sqlite_db_path)
                async with aiosqlite.connect(db_path) as conn:
                    await conn.execute("DELETE FROM vectors_metadata")
                    await conn.execute(
                        "INSERT INTO vectors_metadata (dimension) VALUES (?)", (current_dim,)
                    )
                    await conn.commit()
                logger.info("vectors_metadata updated successfully.")
            except Exception as e:
                logger.error(f"Failed to update vectors_metadata: {e}")
                logger.error("Aborting migration to prevent inconsistent state.")
                sys.exit(1)

        logger.info("Fetching all memories (active and archived)...")
        # MemoryFilters(archived=False) returns both active and archived memories.
        all_memories = await storage.list_by_filter(MemoryFilters(archived=False))

        if not all_memories:
            logger.info("No memories found in storage.")
            return

        total = len(all_memories)
        logger.info(f"Found {total} memories to migrate.")

        success_count = 0
        failed_count = 0
        failed_ids = []

        for i, memory in enumerate(all_memories):
            if i % 10 == 0 or i == total - 1:
                logger.info(f"Processing {i + 1}/{total} (ID: {memory.id})")

            try:
                # Re-embed content
                new_embedding = await embedding_provider.embed(memory.content)
                # Update in storage (convert memory.id to string to avoid UUID binding error)
                success = await storage.update_memory(str(memory.id), {"embedding": new_embedding})
                if success:
                    success_count += 1
                else:
                    logger.warning(f"Failed to update memory {memory.id}")
                    failed_count += 1
                    failed_ids.append(str(memory.id))
            except Exception as e:
                logger.error(f"Error re-embedding memory {memory.id}: {e}")
                failed_count += 1
                failed_ids.append(str(memory.id))

        logger.info("Migration finished.")
        logger.info(f"Total processed: {total}")
        logger.info(f"Successfully migrated: {success_count}")
        if failed_count > 0:
            logger.warning(f"Failed to migrate: {failed_count}")
            sample_size = min(5, len(failed_ids))
            logger.warning(f"Sample failed IDs: {failed_ids[:sample_size]}")

    finally:
        await storage.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate vector dimensions by re-embedding")
    parser.add_argument(
        "--force", action="store_true", help="Force re-embedding even if dimensions match"
    )
    args = parser.parse_args()

    try:
        asyncio.run(migrate(force=args.force))
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Migration failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
