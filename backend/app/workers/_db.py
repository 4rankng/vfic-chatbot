"""Per-job async DB session for RQ workers.

RQ's SimpleWorker runs each job via ``asyncio.run()`` — a fresh event loop per job. The
module-global engine in :mod:`app.core.db` binds its asyncpg connection pool to whichever loop
first touched it; reusing it across jobs raises ``RuntimeError: Future attached to a different
loop``. This helper gives each job its OWN engine on the job's OWN loop, with ``NullPool`` so
no connection ever outlives the loop that created it. The web app's module-global engine is
unaffected (it runs on one long-lived uvicorn loop).

Teardown: the engine is created inside the coroutine and disposed in ``finally`` on the SAME
loop, so disposal can never hit the cross-loop error. ``NullPool`` closes the connection the
moment the session context exits, so ``dispose()`` has nothing left to close — it just
finalizes the engine.

TODO(option-D): the cleaner long-term design is one persistent asyncio loop per worker process
(like uvicorn), letting the engine + httpx/genai clients all share one loop-bound pool.
Deferred per the no-big-bang constraint; see .omc/plans/ingest-worker-crossloop-fix.md.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def worker_session() -> AsyncIterator[AsyncSession]:
    """Yield a session backed by a per-job ``NullPool`` engine; dispose it on exit.

    Created + disposed inside the coroutine so the engine always lives on the job's own
    event loop (the one ``asyncio.run`` made for this job) — the property that prevents the
    cross-loop asyncpg poison.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,  # no connection retained across checkouts -> nothing can cross loops
        future=True,
        # pool_pre_ping intentionally omitted: inert under NullPool (no pooled conn to ping).
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:  # session.close() runs here on normal exit OR exception
            yield session
    finally:
        await engine.dispose()  # always on the loop that created the engine
