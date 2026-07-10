"""Async DB sessions for RQ workers.

Worker job functions are synchronous, but the app logic is async.  The worker
entrypoints run async jobs on a process-local event loop; this module keeps one
SQLAlchemy async engine/sessionmaker per event loop so pooled asyncpg
connections never cross loop boundaries.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class _WorkerDbState:
    loop: AbstractEventLoop
    engine: AsyncEngine
    factory: async_sessionmaker[AsyncSession]


_states: dict[int, _WorkerDbState] = {}


def _state_for_running_loop() -> _WorkerDbState:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    settings = get_settings()
    loop = asyncio.get_running_loop()
    key = id(loop)
    state = _states.get(key)
    if state is not None and not state.loop.is_closed():
        return state

    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    state = _WorkerDbState(loop=loop, engine=engine, factory=factory)
    _states[key] = state
    return state


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    """Yield a session backed by the current worker event loop's engine."""
    factory = _state_for_running_loop().factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_worker_engines() -> None:
    """Dispose every cached worker engine on its owning event loop."""
    current_loop = asyncio.get_running_loop()
    stale: list[int] = []
    for key, state in list(_states.items()):
        if state.loop is current_loop and not state.loop.is_closed():
            await state.engine.dispose()
            stale.append(key)
    for key in stale:
        _states.pop(key, None)
