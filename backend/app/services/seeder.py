"""Idempotent startup seeder for defaults that the live bot assumes.

Ensures there is at least one global persona (seeded from the committed persona.md) so
resolve_persona always has something to return. Safe to run on every startup; never
throws (a seeding failure is logged but non-fatal — the app still boots).
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def ensure_defaults(db: AsyncSession) -> None:
    # Default global persona from persona.md if NO global persona exists yet.
    has_global = (await db.execute(
        text("SELECT 1 FROM personas WHERE project_id IS NULL LIMIT 1")
    )).first()
    if not has_global:
        from app.graph.prompts import AGENT_SYSTEM_PROMPT

        await db.execute(
            text("INSERT INTO personas(slug, name, body_md, is_active, project_id) "
                 "VALUES ('default-vfic', 'Default VFIC', :body, true, NULL)"),
            {"body": AGENT_SYSTEM_PROMPT},
        )
        logger.info("seeded Default VFIC persona from persona.md")
    await db.commit()
