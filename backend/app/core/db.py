"""Async SQLAlchemy 2.x engine + session factory.

The schema is managed by Alembic (raw-SQL baseline). ORM models mirror the tables
for querying; they do NOT generate migrations.

The engine is created lazily: importing this module (which ``app.models.base``
importers no longer pay for) must not bind the production pool configuration.
The first access to ``engine`` / ``async_session`` — the app boot, a worker
session, or an explicit ``get_engine()`` — builds it once from the then-current
settings and caches it, so production still has exactly one engine per process.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.base import Base

_engine = None
_session_factory: async_sessionmaker | None = None


def get_engine():
    """The process-wide async engine, built on first use (import-safe)."""
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_pre_ping=True,
            future=True,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
            pool_recycle=s.db_pool_recycle,
        )
    return _engine


def get_session_factory() -> async_sessionmaker:
    """The session factory bound to the process engine, built on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


def __getattr__(name: str):
    # Lazy module attributes: ``from app.core.db import engine`` and
    # ``db.async_session`` keep working unchanged while a bare import of this
    # module opens no pool. Assigning ``db.engine = ...`` (the integration
    # conftest swaps both attributes per disposable database) creates a real
    # module attribute that shadows this lookup, exactly as before.
    if name == "engine":
        return get_engine()
    if name == "async_session":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and rolls back on exception."""
    # Resolved through the module namespace at call time so the integration
    # conftest's attribute swap rebinds this dependency, not just the name.
    from app.core import db as _db

    async with _db.async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ``engine`` and ``async_session`` are intentionally absent: they are lazy
# module attributes provided through ``__getattr__`` above, not module globals.
__all__ = ["Base", "get_db"]
