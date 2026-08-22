"""LangGraph checkpointer construction shared by the API and worker processes."""

import logging

logger = logging.getLogger(__name__)


async def make_checkpointer(settings):
    """Postgres-backed checkpointer when available; in-memory otherwise."""
    if settings.database_url.startswith("postgresql"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool

        conninfo = settings.database_url.replace("+asyncpg", "")
        # autocommit is required: checkpointer.setup() issues CREATE INDEX CONCURRENTLY
        pool = AsyncConnectionPool(conninfo=conninfo, open=False, max_size=10,
                                   kwargs={"autocommit": True})
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        logger.info("langgraph checkpointer: postgres")
        return saver, pool
    from langgraph.checkpoint.memory import MemorySaver

    logger.warning("langgraph checkpointer: in-memory (interrupts lost on restart)")
    return MemorySaver(), None
