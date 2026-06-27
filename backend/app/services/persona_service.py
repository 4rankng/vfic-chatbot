"""Persona business logic: CRUD + activate (one active global) + LLM generation.

Extracted from the personas router so the router stays a thin HTTP layer (validate ->
delegate -> serialize). ``activate`` transactionally deactivates the other global personas
first (via the ORM, replacing the router's raw SQL), so the ``personas_one_active_global``
partial unique index never trips. ``resolve_persona`` (graph) reads the active body_md,
falling back to persona.md when none is active.

Raises ``HTTPException`` for not-found / conflict / rate-limit / LLM-failure outcomes
(behavior-preserving vs. the legacy router).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.models.user import User
from app.schemas.personas import PersonaCreate, PersonaUpdate, _slugify
from app.services.audit_service import record_audit
from app.services.ratelimit import enforce_persona_generate_rate_limit

logger = logging.getLogger(__name__)

_PERSONA_USER_TEMPLATE = (
    "Mở rộng mô tả sau thành một persona HOÀN CHỈNH cho chatbot VFIC, theo ĐÚNG 7 phần "
    "với giữ nguyên các tiêu đề tiếng Việt sau:\n"
    "### Vai trò của tôi là gì?\n"
    "### Ai cần tôi giúp?\n"
    "### Tôi hoàn thành công việc thế nào?\n"
    "### Tôi nên tránh điều gì?\n"
    "### Kết quả nào cần theo dõi?\n"
    "### Tôi nên giao tiếp thế nào?\n"
    "### Mẹo bổ sung?\n\n"
    "Yêu cầu đầu ra:\n"
    "- Chỉ xuất persona 7 phần, KHÔNG thêm mục 'NGUỒN', 'BẢNG TRUY VẤN Ý NGHĨA', "
    "citations hay ghi chú kiểm tra trung thành.\n"
    "- Giữ nguyên ý mô tả; làm rõ + thêm ví dụ/edge case ở các phần khi phù hợp; tiếng Việt chuẩn.\n\n"
    "Mô tả: {desc}"
)


def _persona_user_message(description: str) -> str:
    return _PERSONA_USER_TEMPLATE.format(desc=description.strip())


async def _get(pid: uuid.UUID, db: AsyncSession) -> Persona:
    p = await db.get(Persona, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found")
    return p


class PersonaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self) -> list[Persona]:
        return list(
            (await self.db.scalars(select(Persona).order_by(Persona.created_at.desc()))).all()
        )

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
                raise HTTPException(status.HTTP_409_CONFLICT, f"persona create failed: {exc2}") from exc2
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
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "activation is for global personas only")
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

    async def generate(self, admin: User, description: str) -> str:
        """Expand a short description into a full 7-part persona body_md via MiniMax.

        Best-effort per-admin throttle; the MiniMax expander is imported lazily so
        langchain_openai is pulled in only when generation runs, keeping the web-process
        import path langchain-free. Nothing here auto-activates or persists a persona.
        """
        await enforce_persona_generate_rate_limit(admin.id)
        # Imported lazily (see note above).
        from app.graph.factories import build_persona_expander

        try:
            expand = build_persona_expander()
            body_md = (await expand(_persona_user_message(description))).strip()
        except Exception as exc:  # noqa: BLE001
            logger.exception("persona generation failed")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Sinh persona thất bại. Vui lòng thử lại."
            ) from exc
        if not body_md:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Sinh persona thất bại. Vui lòng thử lại."
            )
        await record_audit(
            self.db, action="generate_persona", actor_id=admin.id, target_type="persona", target_id=None
        )
        await self.db.commit()  # record_audit only flushes
        return body_md
