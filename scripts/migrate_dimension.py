#!/usr/bin/env python3
"""
Migrate vector dimensions by re-embedding all memories.
Usage: uv run python scripts/migrate_dimension.py
"""
import asyncio
import sys
import logging
import os

# Add src to sys.path to ensure we can import context_store
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from context_store.config import Settings
    from context_store.storage.factory import _create_storage_adapter
    from context_store.storage.protocols import MemoryFilters
    from context_store.embedding import create_embedding_provider
except ImportError as e:
    print(f"Error: Could not import context_store modules. Make sure you are running from the project root. {e}", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

async def migrate() -> None:
    logger.info("Starting dimension migration...")
    settings = Settings()
    
    # We bypass Orchestrator to avoid the dimension check at startup
    storage = await _create_storage_adapter(settings)
    embedding_provider = create_embedding_provider(settings)
    
    try:
        stored_dim = await storage.get_vector_dimension()
        current_dim = embedding_provider.dimension
        logger.info(f"Storage dimension: {stored_dim}")
        logger.info(f"Current provider dimension: {current_dim}")
        
        if stored_dim == current_dim:
            logger.info("Dimensions already match. No migration needed.")
            # Proceed anyway if the user wants to force re-embedding?
        
        logger.info("Fetching all memories (active and archived)...")
        # MemoryFilters(archived=False) returns both active and archived memories.
        all_memories = await storage.list_by_filter(MemoryFilters(archived=False))
        
        if not all_memories:
            logger.info("No memories found in storage.")
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
                    await conn.execute("INSERT INTO vectors_metadata (dimension) VALUES (?)", (current_dim,))
                    await conn.commit()
                logger.info("vectors_metadata updated successfully.")
            except Exception as e:
                logger.error(f"Failed to update vectors_metadata: {e}")
                logger.error("Aborting migration to prevent inconsistent state.")
                sys.exit(1)

        total = len(all_memories)
        logger.info(f"Found {total} memories to migrate.")
        
        for i, memory in enumerate(all_memories):
            if i % 10 == 0 or i == total - 1:
                logger.info(f"Processing {i+1}/{total} (ID: {memory.id})")
            
            try:
                # Re-embed content
                new_embedding = await embedding_provider.embed(memory.content)
                # Update in storage (convert memory.id to string to avoid UUID binding error)
                success = await storage.update_memory(str(memory.id), {"embedding": new_embedding})
                if not success:
                    logger.warning(f"Failed to update memory {memory.id}")
            except Exception as e:
                logger.error(f"Error re-embedding memory {memory.id}: {e}")
        
        logger.info("Migration finished successfully.")
        
    finally:
        await storage.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        logger.info("Migration interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Migration failed with error: {e}")
        sys.exit(1)
