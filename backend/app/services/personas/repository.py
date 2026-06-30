"""Persona data-access layer (raw SQL + ORM lookups behind one class).

Mirrors the ``services/knowledge/repository.py`` pattern: raw SQL and select/update
queries live here, business logic in ``service.py`` calls these methods.

Raises ``NotFoundError`` (not HTTPException) for missing entities — the service
layer maps these to HTTP responses where appropriate.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.schemas.personas import ProjectMini
from app.services.errors import NotFoundError


class PersonaRepository:
    """All persona-related DB access for the service layer."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, pid: uuid.UUID) -> Persona:
        """Return the persona or raise :class:`NotFoundError`."""
        p = await self.db.get(Persona, pid)
        if p is None:
            raise NotFoundError("Agent not found")
        return p

    async def assigned_projects_for(self, pid: uuid.UUID) -> list[ProjectMini]:
        """Projects whose ``default_persona_id`` equals ``pid``."""
        result = await self.db.execute(
            text("SELECT id, name, slug FROM projects WHERE default_persona_id = :pid"),
            {"pid": pid},
        )
        return [ProjectMini(id=r.id, name=r.name, slug=r.slug) for r in result.all()]

    async def assigned_projects_map(self) -> dict[str, list[ProjectMini]]:
        """Mapping of ``str(persona_id) -> [ProjectMini, ...]`` for all assigned personas."""
        result = await self.db.execute(
            text(
                "SELECT id, name, slug, default_persona_id FROM projects WHERE default_persona_id IS NOT NULL"
            )
        )
        project_map: dict[str, list[ProjectMini]] = {}
        for r in result.all():
            project_map.setdefault(str(r.default_persona_id), []).append(
                ProjectMini(id=r.id, name=r.name, slug=r.slug)
            )
        return project_map

    async def find_by_slug(self, slug: str) -> Persona | None:
        """First persona matching ``slug``, or ``None``."""
        return (await self.db.scalars(select(Persona).where(Persona.slug == slug).limit(1))).first()

    async def deactivate_other_globals(self, persona_id: uuid.UUID) -> None:
        """Deactivate all other active global personas (project_id IS NULL)."""
        await self.db.execute(
            update(Persona)
            .where(
                Persona.project_id.is_(None),
                Persona.is_active.is_(True),
                Persona.id != persona_id,
            )
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )
