"""Persona data-access layer (raw SQL + ORM lookups behind one class).

Mirrors the ``services/knowledge/repository.py`` pattern: raw SQL and select/update
queries live here, business logic in ``service.py`` calls these methods.

Raises ``NotFoundError`` (not HTTPException) for missing entities — the service
layer maps these to HTTP responses where appropriate.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import AdapterPersonaAssignment, Persona, PersonaVersion
from app.schemas.personas import AdapterProvider, SUPPORTED_ADAPTER_PROVIDERS
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

    async def find_by_slug(self, slug: str) -> Persona | None:
        """First persona matching ``slug``, or ``None``."""
        return (await self.db.scalars(select(Persona).where(Persona.slug == slug).limit(1))).first()

    async def active_persona(self) -> Persona | None:
        return (
            await self.db.scalars(
                select(Persona).where(Persona.is_active.is_(True)).order_by(Persona.updated_at.desc())
            )
        ).first()

    async def assignment_for_provider(
        self, provider: AdapterProvider
    ) -> AdapterPersonaAssignment | None:
        return await self.db.get(AdapterPersonaAssignment, provider)

    async def assignment_rows(self) -> list[AdapterPersonaAssignment]:
        return list(
            (
                await self.db.scalars(
                    select(AdapterPersonaAssignment).order_by(AdapterPersonaAssignment.provider)
                )
            ).all()
        )

    async def set_assignment(self, provider: AdapterProvider, persona_id: uuid.UUID) -> None:
        """Atomically create or replace one provider assignment."""
        statement = insert(AdapterPersonaAssignment).values(
            provider=provider,
            persona_id=persona_id,
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                index_elements=[AdapterPersonaAssignment.provider],
                set_={
                    "persona_id": statement.excluded.persona_id,
                    "updated_at": func.now(),
                },
            )
        )

    async def clear_assignment(self, provider: AdapterProvider) -> None:
        """Atomically remove a provider override so it inherits the default."""
        await self.db.execute(
            delete(AdapterPersonaAssignment).where(
                AdapterPersonaAssignment.provider == provider
            )
        )

    async def effective_provider_map(self) -> dict[str, list[AdapterProvider]]:
        mapping: dict[str, list[AdapterProvider]] = {}
        overrides = await self.assignment_rows()
        overridden = {row.provider for row in overrides}
        for row in overrides:
            mapping.setdefault(str(row.persona_id), []).append(row.provider)  # type: ignore[arg-type]

        active = await self.active_persona()
        if active is not None:
            providers = mapping.setdefault(str(active.id), [])
            for provider in SUPPORTED_ADAPTER_PROVIDERS:
                if provider not in overridden and provider not in providers:
                    providers.append(provider)

        for persona_id, providers in mapping.items():
            mapping[persona_id] = sorted(
                providers,
                key=lambda provider: SUPPORTED_ADAPTER_PROVIDERS.index(provider),
            )
        return mapping

    async def effective_persona_for_provider(self, provider: AdapterProvider) -> Persona | None:
        assignment = await self.assignment_for_provider(provider)
        if assignment is not None:
            return await self.get_by_id(assignment.persona_id)
        return await self.active_persona()

    async def active_persona_body(self, provider: AdapterProvider) -> str | None:
        persona = await self.effective_persona_for_provider(provider)
        return None if persona is None else persona.body_md

    async def next_version_no(self, persona_id: uuid.UUID) -> int:
        current = await self.db.scalar(
            select(func.max(PersonaVersion.version_no)).where(
                PersonaVersion.persona_id == persona_id
            )
        )
        return int(current or 0) + 1

    async def lock_for_version_append(self, persona_id: uuid.UUID) -> None:
        await self.db.execute(select(Persona.id).where(Persona.id == persona_id).with_for_update())

    async def has_versions(self, persona_id: uuid.UUID) -> bool:
        count = await self.db.scalar(
            select(func.count(PersonaVersion.id)).where(PersonaVersion.persona_id == persona_id)
        )
        return bool(count)

    async def list_versions(self, persona_id: uuid.UUID) -> list[PersonaVersion]:
        await self.get_by_id(persona_id)
        return list(
            (
                await self.db.scalars(
                    select(PersonaVersion)
                    .where(PersonaVersion.persona_id == persona_id)
                    .order_by(PersonaVersion.version_no.desc())
                )
            ).all()
        )

    async def deactivate_other_active(self, persona_id: uuid.UUID) -> None:
        """Deactivate all other active personas before activating ``persona_id``."""
        await self.db.execute(
            update(Persona)
            .where(
                Persona.is_active.is_(True),
                Persona.id != persona_id,
            )
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )
