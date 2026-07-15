"""Persona business logic: CRUD + activate (one active global) + template import.

Extracted from the personas router so the router stays a thin HTTP layer (validate ->
delegate -> serialize). ``activate`` transactionally deactivates the other global personas
first (via the ORM, replacing the router's raw SQL), so the ``personas_one_active_global``
partial unique index never trips. ``resolve_persona`` (graph) reads the active body_md,
falling back to persona.md when none is active.

Raises domain errors (:class:`NotFoundError`, :class:`ConflictError`) for not-found /
conflict outcomes; the router maps these to HTTP status codes.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import bump_cache_version
from app.core.preamble_cache import NS_PREAMBLE
from app.models.persona import Persona, PersonaVersion
from app.models.user import User
from app.schemas.personas import PersonaCreate, PersonaUpdate, _slugify
from app.services.audit_service import record_audit
from app.services.errors import ConflictError

from .parsing import parse_persona_markdown
from .repository import PersonaRepository

logger = logging.getLogger(__name__)

_PERSONA_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "persona_v1.md"


def load_persona_template() -> str:
    return _PERSONA_TEMPLATE_PATH.read_text(encoding="utf-8")


class PersonaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PersonaRepository(db)

    async def get(self, persona_id: uuid.UUID) -> Persona:
        persona = await self.repo.get_by_id(persona_id)
        # Enrich with assigned projects (same as list).
        try:
            persona._assigned_projects = await self.repo.assigned_projects_for(persona_id)
        except Exception:  # noqa: BLE001
            persona._assigned_projects = []
        return persona

    async def list_versions(self, persona_id: uuid.UUID) -> list[PersonaVersion]:
        return await self.repo.list_versions(persona_id)

    async def list(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        sort_by: str | None = None,
        order: str | None = "desc",
        q: str | None = None,
    ) -> tuple[list[Persona], int]:
        query = select(Persona)
        if q:
            pat = f"%{q.strip()}%"
            ua = func.extensions.unaccent
            query = query.where(
                ua(Persona.name).ilike(ua(pat))
                | ua(Persona.slug).ilike(ua(pat))
                | ua(Persona.notes).ilike(ua(pat))
            )
        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        sort_map = {
            "created_at": Persona.created_at,
            "updated_at": Persona.updated_at,
            "name": Persona.name,
            "slug": Persona.slug,
        }
        sort_col = sort_map.get((sort_by or "").lower()) or Persona.created_at
        order_expr = sort_col.asc() if (order or "desc").lower() == "asc" else sort_col.desc()
        rows = list(
            (
                await self.db.scalars(
                    query.order_by(order_expr).offset((page - 1) * per_page).limit(per_page)
                )
            ).all()
        )
        # Enrich with assigned projects (projects whose default_persona_id = persona.id).
        try:
            project_map = await self.repo.assigned_projects_map()
            for persona in rows:
                persona._assigned_projects = project_map.get(str(persona.id), [])
        except Exception:  # noqa: BLE001
            for persona in rows:
                persona._assigned_projects = []
        return rows, int(total or 0)

    async def create(self, body: PersonaCreate, admin: User) -> Persona:
        slug = (body.slug or _slugify(body.name)).strip() or _slugify(body.name)
        persona = Persona(
            name=body.name.strip(),
            slug=slug,
            body_md=body.body_md,
            followup_rules=body.followup_rules.model_dump(mode="json"),
            notes=body.notes,
            created_by=admin.id,
        )
        self.db.add(persona)
        try:
            await self.db.flush()
        except Exception:  # noqa: BLE001 — unique slug collision
            await self.db.rollback()
            # retry with a uniquified slug
            persona.slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            self.db.add(persona)
            try:
                await self.db.flush()
            except Exception as exc2:  # noqa: BLE001
                await self.db.rollback()
                raise ConflictError(f"Agent create failed: {exc2}") from exc2
        await self._append_version(persona, admin.id)
        await record_audit(
            self.db,
            action="create_persona",
            actor_id=admin.id,
            target_type="persona",
            target_id=str(persona.id),
        )
        await self.db.commit()
        await self.db.refresh(persona)
        if body.is_active:
            return await self._activate(persona)
        await bump_cache_version(NS_PREAMBLE)
        return persona

    async def update(self, persona_id: uuid.UUID, body: PersonaUpdate, admin: User) -> Persona:
        persona = await self.repo.get_by_id(persona_id)
        if body.name is not None:
            persona.name = body.name.strip()
        if body.body_md is not None:
            persona.body_md = body.body_md
        if body.notes is not None:
            persona.notes = body.notes
        if body.followup_rules is not None:
            persona.followup_rules = body.followup_rules.model_dump(mode="json")
        if body.body_md is not None or body.followup_rules is not None:
            await self._append_version(persona, admin.id)
        await record_audit(
            self.db,
            action="update_persona",
            actor_id=admin.id,
            target_type="persona",
            target_id=str(persona.id),
            payload={"followup_rules_changed": body.followup_rules is not None},
        )
        await self.db.commit()
        await self.db.refresh(persona)
        await bump_cache_version(NS_PREAMBLE)
        return persona

    async def delete(self, persona_id: uuid.UUID) -> None:
        persona = await self.repo.get_by_id(persona_id)
        if await self.repo.has_versions(persona_id):
            raise ConflictError("Agent has immutable versions and cannot be deleted")
        await self.db.delete(persona)
        await self.db.commit()
        await bump_cache_version(NS_PREAMBLE)

    async def activate(self, persona_id: uuid.UUID) -> Persona:
        persona = await self.repo.get_by_id(persona_id)
        if persona.project_id is not None:
            raise ValueError("activation is for global Agents only")
        return await self._activate(persona)

    async def assign_to_all_projects(self, persona_id: uuid.UUID, admin: User) -> int:
        await self.repo.get_by_id(persona_id)
        result = await self.db.execute(
            text(
                "UPDATE projects "
                "SET default_persona_id = :persona_id "
                "WHERE default_persona_id IS DISTINCT FROM :persona_id"
            ),
            {"persona_id": persona_id},
        )
        changed = int(result.rowcount or 0)
        await record_audit(
            self.db,
            action="assign_persona_all_projects",
            actor_id=admin.id,
            target_type="persona",
            target_id=str(persona_id),
            payload={"project_count": changed},
        )
        await self.db.commit()
        await bump_cache_version(NS_PREAMBLE)
        return changed

    async def _activate(self, persona: Persona) -> Persona:
        """Deactivate other global personas, then activate this one (one transaction)."""
        await self.repo.deactivate_other_globals(persona.id)
        persona.is_active = True
        await record_audit(
            self.db,
            action="activate_persona",
            actor_id=None,
            target_type="persona",
            target_id=str(persona.id),
        )
        await self.db.commit()
        await self.db.refresh(persona)
        await bump_cache_version(NS_PREAMBLE)
        return persona

    async def import_persona(self, text: str, admin: User) -> Persona:
        """Import a persona from a markdown file (with optional YAML frontmatter).

        If a persona with the same slug already exists, overwrites its ``body_md``
        (and optionally ``name``/``notes``). Otherwise creates a new persona.
        """
        name, slug, notes, body_md = parse_persona_markdown(text)
        derived_slug = slug or _slugify(name)

        # Check for existing persona with this slug → overwrite
        existing = await self.repo.find_by_slug(derived_slug)

        if existing:
            existing.name = name
            existing.body_md = body_md
            if notes is not None:
                existing.notes = notes
            await self._append_version(existing, admin.id)
            await record_audit(
                self.db,
                action="import_persona",
                actor_id=admin.id,
                target_type="persona",
                target_id=str(existing.id),
            )
            await self.db.commit()
            await self.db.refresh(existing)
            await bump_cache_version(NS_PREAMBLE)
            return existing

        # New persona
        body = PersonaCreate(name=name, body_md=body_md, slug=slug, notes=notes)
        return await self.create(body, admin)

    async def _append_version(
        self, persona: Persona, created_by: uuid.UUID | None
    ) -> PersonaVersion:
        """Append immutable content while keeping the legacy persona projection current."""
        from app.services.installation.hashing import sha256_json

        await self.repo.lock_for_version_append(persona.id)
        version = PersonaVersion(
            persona_id=persona.id,
            version_no=await self.repo.next_version_no(persona.id),
            body_md=persona.body_md,
            followup_rules=persona.followup_rules,
            checksum=sha256_json(
                {"body_md": persona.body_md, "followup_rules": persona.followup_rules}
            ),
            created_by=created_by,
        )
        self.db.add(version)
        await self.db.flush()
        return version
