"""Personas admin API — CRUD + activate (one active global persona).

A persona is the bot's voice (free-form markdown). Several may be stored; exactly one
*global* persona is active at a time. ``activate`` transactionally deactivates the
other global personas first, so the ``personas_one_active_global`` partial unique index
never trips. ``resolve_persona`` (graph) reads the active body_md, falling back to
persona.md when none is active.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.persona import Persona
from app.models.user import User
from app.schemas.personas import (
    PersonaCreate,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaListResponse,
    PersonaOut,
    PersonaUpdate,
    _slugify,
)
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge/personas", tags=["personas"])


async def _get(pid: uuid.UUID, db: AsyncSession) -> Persona:
    p = await db.get(Persona, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "persona not found")
    return p


@router.get("", response_model=PersonaListResponse)
async def list_personas(_admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> PersonaListResponse:
    rows = list((await db.scalars(select(Persona).order_by(Persona.created_at.desc()))).all())
    return PersonaListResponse(data=[PersonaOut.model_validate(p) for p in rows], total=len(rows))


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(body: PersonaCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> PersonaOut:
    slug = (body.slug or _slugify(body.name)).strip() or _slugify(body.name)
    persona = Persona(name=body.name.strip(), slug=slug, body_md=body.body_md, notes=body.notes, created_by=admin.id)
    db.add(persona)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001 — unique slug collision
        await db.rollback()
        # retry with a uniquified slug
        persona.slug = f"{slug}-{uuid.uuid4().hex[:6]}"
        db.add(persona)
        try:
            await db.commit()
        except Exception as exc2:  # noqa: BLE001
            await db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, f"persona create failed: {exc2}") from exc2
    await record_audit(db, action="create_persona", actor_id=admin.id, target_type="persona", target_id=str(persona.id))
    await db.commit()
    await db.refresh(persona)
    if body.is_active:
        return PersonaOut.model_validate(await _activate(persona, db))
    return PersonaOut.model_validate(persona)


@router.patch("/{persona_id}", response_model=PersonaOut)
async def update_persona(
    persona_id: uuid.UUID, body: PersonaUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    persona = await _get(persona_id, db)
    if body.name is not None:
        persona.name = body.name.strip()
    if body.body_md is not None:
        persona.body_md = body.body_md
    if body.notes is not None:
        persona.notes = body.notes
    await record_audit(db, action="update_persona", actor_id=admin.id, target_type="persona", target_id=str(persona.id))
    await db.commit()
    await db.refresh(persona)
    return PersonaOut.model_validate(persona)


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    persona = await _get(persona_id, db)
    # If this was the active global persona, none remains active afterwards and
    # resolve_persona falls back to persona.md until a new one is activated.
    await db.delete(persona)
    await db.commit()


@router.post("/{persona_id}/activate", response_model=PersonaOut)
async def activate_persona(
    persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    persona = await _get(persona_id, db)
    if persona.project_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "activation is for global personas only")
    return PersonaOut.model_validate(await _activate(persona, db))


async def _activate(persona: Persona, db: AsyncSession) -> Persona:
    """Deactivate other global personas, then activate this one (one transaction)."""
    await db.execute(
        text("UPDATE personas SET is_active = false WHERE project_id IS NULL AND is_active AND id <> :id"),
        {"id": str(persona.id)},
    )
    persona.is_active = True
    await record_audit(db, action="activate_persona", actor_id=None, target_type="persona", target_id=str(persona.id))
    await db.commit()
    await db.refresh(persona)
    return persona


# --- LLM-assisted persona generation --------------------------------------
# Admin enters a short description -> MiniMax (rule-expander prompt) expands it
# into a full 7-part persona body_md. Admin previews/edits in the UI before
# saving; nothing here auto-activates or persists a persona.

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


# Best-effort per-admin throttle: a stuck retry loop or double-click must not
# starve the 1-vCPU droplet's ASGI worker (each generate holds it up to the
# MiniMax timeout). Fail-open: a redis hiccup never blocks the feature.
_RATE_KEY = "persona_gen:{admin_id}"
_RATE_LIMIT = 5  # max generates ...
_RATE_WINDOW = 600  # ... per 600s per admin


async def _enforce_generate_rate_limit(admin_id: uuid.UUID) -> None:
    try:
        from app.core.redis import get_redis

        r = get_redis()
        key = _RATE_KEY.format(admin_id=admin_id)
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _RATE_WINDOW)
        if count > _RATE_LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Bạn đã sinh persona quá nhiều lần. Vui lòng thử lại sau vài phút.",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — redis unavailable -> fail open
        logger.warning("persona-generate rate-limit check skipped (redis unavailable)")


@router.post("/generate", response_model=PersonaGenerateResponse)
async def generate_persona(
    body: PersonaGenerateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaGenerateResponse:
    await _enforce_generate_rate_limit(admin.id)
    # Imported lazily so langchain_openai is pulled in only when generation
    # actually runs, keeping the web-process import path langchain-free.
    from app.graph.llm_real import build_persona_expander

    try:
        expand = build_persona_expander()
        body_md = (await expand(_persona_user_message(body.description))).strip()
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
        db, action="generate_persona", actor_id=admin.id, target_type="persona", target_id=None
    )
    await db.commit()  # record_audit only flushes
    return PersonaGenerateResponse(body_md=body_md)
