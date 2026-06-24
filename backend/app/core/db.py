"""Async SQLAlchemy 2.x engine + session factory.

The schema is managed by Alembic (raw-SQL baseline). ORM models mirror the tables
for querying; they do NOT generate migrations.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.base import Base

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True, future=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and rolls back on exception."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


__all__ = ["Base", "engine", "async_session", "get_db"]
