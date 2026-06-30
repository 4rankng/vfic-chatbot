"""Personas admin API — thin HTTP layer over :class:`PersonaService`.

A persona is the bot's voice (free-form markdown). Several may be stored; exactly one
*global* persona is active at a time. All persistence and activation live in
``app.services.persona_service``; this router only validates input, delegates,
and serializes the response.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.personas import (
    PersonaCreate,
    PersonaListResponse,
    PersonaOut,
    PersonaUpdate,
    ProjectMini,
)
from app.services.persona_service import PersonaService, load_persona_template

router = APIRouter(prefix="/knowledge/personas", tags=["personas"])


@router.get("", response_model=PersonaListResponse)
async def list_personas(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    sort: str | None = Query(None, description="Sort field (name, slug, created_at, updated_at)"),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaListResponse:
    rows, total = await PersonaService(db).list(
        page=page,
        per_page=per_page,
        sort_by=sort,
        order=order,
    )
    out = []
    for p in rows:
        d = PersonaOut.model_validate(p)
        d.assigned_projects = getattr(p, "_assigned_projects", [])
        out.append(d)
    return PersonaListResponse(data=out, total=total)


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    body: PersonaCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    return PersonaOut.model_validate(await PersonaService(db).create(body, admin))


@router.get("/{persona_id}", response_model=PersonaOut)
async def get_persona(
    persona_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    persona = await PersonaService(db).get(persona_id)
    out = PersonaOut.model_validate(persona)
    out.assigned_projects = getattr(persona, "_assigned_projects", [])
    return out


@router.patch("/{persona_id}", response_model=PersonaOut)
async def update_persona(
    persona_id: uuid.UUID,
    body: PersonaUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    return PersonaOut.model_validate(await PersonaService(db).update(persona_id, body, admin))


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    await PersonaService(db).delete(persona_id)


@router.post("/{persona_id}/activate", response_model=PersonaOut)
async def activate_persona(
    persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    return PersonaOut.model_validate(await PersonaService(db).activate(persona_id))


@router.get("/format/template")
async def get_persona_template(_admin: User = Depends(require_admin)) -> PlainTextResponse:
    return PlainTextResponse(
        load_persona_template(),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vfic-persona-v1-template.md"'},
    )


@router.post("/import", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def import_persona(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    data = await file.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Tệp không phải UTF-8 hợp lệ.",
        ) from None
    try:
        persona = await PersonaService(db).import_persona(text, admin)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            str(exc),
        ) from exc
    return PersonaOut.model_validate(persona)
