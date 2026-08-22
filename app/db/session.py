"""Async engine/session management."""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings
from app.db.base import Base

logger = logging.getLogger(__name__)


@lru_cache
def get_engine(database_url: str, echo: bool = False,
               *, pool_size: int = 10, max_overflow: int = 20) -> AsyncEngine:
    # Pool sizing only applies to pooled dialects; sqlite/aiosqlite rejects the kwargs.
    pool_kwargs = (
        {"pool_size": pool_size, "max_overflow": max_overflow, "pool_pre_ping": True}
        if database_url.startswith("postgresql") else {"pool_pre_ping": True}
    )
    return create_async_engine(database_url, echo=echo, **pool_kwargs)


def get_engine_for_settings(settings: Settings) -> AsyncEngine:
    return get_engine(settings.database_url, settings.db_echo,
                      pool_size=settings.db_pool_size,
                      max_overflow=settings.db_max_overflow)


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(engine: AsyncEngine):
    """Transactional scope: commit on success, rollback on error."""
    factory = get_sessionmaker(engine)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database schema ensured")
