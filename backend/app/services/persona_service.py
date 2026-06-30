"""Persona business logic: CRUD + activate (one active global) + template import.

Extracted from the personas router so the router stays a thin HTTP layer (validate ->
delegate -> serialize). ``activate`` transactionally deactivates the other global personas
first (via the ORM, replacing the router's raw SQL), so the ``personas_one_active_global``
partial unique index never trips. ``resolve_persona`` (graph) reads the active body_md,
falling back to persona.md when none is active.

Raises ``HTTPException`` for not-found / conflict / validation outcomes.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.models.persona import Persona
from app.models.user import User
from app.schemas.personas import PersonaCreate, PersonaUpdate, _slugify, ProjectMini
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

_PERSONA_TEMPLATE_PATH = Path(__file__).resolve().parent / "personas" / "templates" / "persona_v1.md"


def load_persona_template() -> str:
    return _PERSONA_TEMPLATE_PATH.read_text(encoding="utf-8")


def parse_persona_markdown(text: str) -> tuple[str, str | None, str | None, str]:
    """Parse a persona markdown file with optional YAML frontmatter.

    Returns ``(name, slug_or_None, notes_or_None, body_md)``.
    Raises ``ValueError`` if *name* is missing/blank or body is empty.
    """
    errors: list[str] = []

    # --- frontmatter split (hand-rolled, same shape as knowledge/canonical.py) ---
    if not text.startswith("---\n"):
        # No frontmatter — treat entire file as body; name will fail validation.
        fm: dict[str, Any] = {}
        body = text.strip()
    else:
        end = text.find("\n---", 4)
        if end == -1:
            errors.append("frontmatter closing --- delimiter is missing")
            fm, body = {}, text
        else:
            raw = text[4:end].strip("\n")
            body = text[end + 4 :].lstrip("\r\n")
            fm = _parse_persona_frontmatter(raw, errors)

    if errors:
        raise ValueError("; ".join(errors))

    name = str(fm.get("name", "")).strip()
    if not name:
        raise ValueError("Frontmatter thiếu 'name' — tên Agent là bắt buộc.")

    body_md = body.strip()
    if not body_md:
        raise ValueError("Nội dung Agent (body) trống — cần ít nhất 1 phần.")

    slug = str(fm.get("slug", "")).strip() or None
    notes = str(fm.get("notes", "")).strip() or None
    return name, slug, notes, body_md


def _parse_persona_frontmatter(raw: str, errors: list[str]) -> dict[str, Any]:
    """Minimal key:value frontmatter parser (flat only, no nested objects)."""
    out: dict[str, Any] = {}
    current_key: str | None = None
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            errors.append(f"frontmatter line {line_no}: expected key: value")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        current_key = key
        value = value.strip()
        out[key] = value  # persona frontmatter is always scalar
    return out


async def _get(pid: uuid.UUID, db: AsyncSession) -> Persona:
    p = await db.get(Persona, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return p


class PersonaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, persona_id: uuid.UUID) -> Persona:
        persona = await _get(persona_id, self.db)
        # Enrich with assigned projects (same as list).
        try:
            result = await self.db.execute(
                text("SELECT id, name, slug FROM projects WHERE default_persona_id = :pid"),
                {"pid": persona_id},
            )
            persona._assigned_projects = [
                ProjectMini(id=r.id, name=r.name, slug=r.slug) for r in result.all()
            ]
        except Exception:  # noqa: BLE001
            persona._assigned_projects = []
        return persona

    async def list(self) -> list[Persona]:
        rows = list(
            (await self.db.scalars(select(Persona).order_by(Persona.created_at.desc()))).all()
        )
        # Enrich with assigned projects (projects whose default_persona_id = persona.id).
        try:
            result = await self.db.execute(
                text("SELECT id, name, slug, default_persona_id FROM projects WHERE default_persona_id IS NOT NULL")
            )
            project_map: dict[str, list[ProjectMini]] = {}
            for r in result.all():
                pid = str(r.default_persona_id)
                project_map.setdefault(pid, []).append(ProjectMini(id=r.id, name=r.name, slug=r.slug))
            for persona in rows:
                persona._assigned_projects = project_map.get(str(persona.id), [])
        except Exception:  # noqa: BLE001
            for persona in rows:
                persona._assigned_projects = []
        return rows

    async def create(self, body: PersonaCreate, admin: User) -> Persona:
        slug = (body.slug or _slugify(body.name)).strip() or _slugify(body.name)
        persona = Persona(
            name=body.name.strip(),
            slug=slug,
            body_md=body.body_md,
            notes=body.notes,
            created_by=admin.id,
        )
        self.db.add(persona)
        try:
            await self.db.commit()
        except Exception:  # noqa: BLE001 — unique slug collision
            await self.db.rollback()
            # retry with a uniquified slug
            persona.slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            self.db.add(persona)
            try:
                await self.db.commit()
            except Exception as exc2:  # noqa: BLE001
                await self.db.rollback()
                raise HTTPException(status.HTTP_409_CONFLICT, f"Agent create failed: {exc2}") from exc2
        await record_audit(
            self.db, action="create_persona", actor_id=admin.id, target_type="persona", target_id=str(persona.id)
        )
        await self.db.commit()
        await self.db.refresh(persona)
        if body.is_active:
            return await self._activate(persona)
        return persona

    async def update(self, persona_id: uuid.UUID, body: PersonaUpdate, admin: User) -> Persona:
        persona = await _get(persona_id, self.db)
        if body.name is not None:
            persona.name = body.name.strip()
        if body.body_md is not None:
            persona.body_md = body.body_md
        if body.notes is not None:
            persona.notes = body.notes
        await record_audit(
            self.db, action="update_persona", actor_id=admin.id, target_type="persona", target_id=str(persona.id)
        )
        await self.db.commit()
        await self.db.refresh(persona)
        return persona

    async def delete(self, persona_id: uuid.UUID) -> None:
        persona = await _get(persona_id, self.db)
        # If this was the active global persona, none remains active afterwards and
        # resolve_persona falls back to persona.md until a new one is activated.
        await self.db.delete(persona)
        await self.db.commit()

    async def activate(self, persona_id: uuid.UUID) -> Persona:
        persona = await _get(persona_id, self.db)
        if persona.project_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "activation is for global Agents only")
        return await self._activate(persona)

    async def _activate(self, persona: Persona) -> Persona:
        """Deactivate other global personas, then activate this one (one transaction)."""
        await self.db.execute(
            update(Persona)
            .where(
                Persona.project_id.is_(None),
                Persona.is_active.is_(True),
                Persona.id != persona.id,
            )
            .values(is_active=False)
            .execution_options(synchronize_session=False)
        )
        persona.is_active = True
        await record_audit(
            self.db, action="activate_persona", actor_id=None, target_type="persona", target_id=str(persona.id)
        )
        await self.db.commit()
        await self.db.refresh(persona)
        return persona

    async def import_persona(self, text: str, admin: User) -> Persona:
        """Import a persona from a markdown file (with optional YAML frontmatter).

        If a persona with the same slug already exists, overwrites its ``body_md``
        (and optionally ``name``/``notes``). Otherwise creates a new persona.
        """
        name, slug, notes, body_md = parse_persona_markdown(text)
        derived_slug = slug or _slugify(name)

        # Check for existing persona with this slug → overwrite
        existing = (await self.db.scalars(
            select(Persona).where(Persona.slug == derived_slug).limit(1)
        )).first()

        if existing:
            existing.name = name
            existing.body_md = body_md
            if notes is not None:
                existing.notes = notes
            await record_audit(
                self.db, action="import_persona", actor_id=admin.id,
                target_type="persona", target_id=str(existing.id),
            )
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        # New persona
        body = PersonaCreate(name=name, body_md=body_md, slug=slug, notes=notes)
        return await self.create(body, admin)
