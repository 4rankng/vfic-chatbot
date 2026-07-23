"""HTTP-facing dependency adapters for the project/knowledge slice."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db


async def get_project_knowledge_db() -> AsyncIterator[AsyncSession]:
    async for db in get_db():
        yield db


__all__ = ["get_project_knowledge_db"]
