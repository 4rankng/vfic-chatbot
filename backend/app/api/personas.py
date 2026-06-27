"""Personas admin API — thin HTTP layer over :class:`PersonaService`.

A persona is the bot's voice (free-form markdown). Several may be stored; exactly one
*global* persona is active at a time. All persistence, activation, and LLM generation
live in ``app.services.persona_service``; this router only validates input, delegates,
and serializes the response.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.personas import (
    PersonaCreate,
    PersonaGenerateRequest,
    PersonaGenerateResponse,
    PersonaListResponse,
    PersonaOut,
    PersonaUpdate,
)
from app.services.persona_service import PersonaService

router = APIRouter(prefix="/knowledge/personas", tags=["personas"])


@router.get("", response_model=PersonaListResponse)
async def list_personas(
    _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaListResponse:
    rows = await PersonaService(db).list()
    return PersonaListResponse(data=[PersonaOut.model_validate(p) for p in rows], total=len(rows))


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    body: PersonaCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    return PersonaOut.model_validate(await PersonaService(db).create(body, admin))


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


@router.post("/generate", response_model=PersonaGenerateResponse)
async def generate_persona(
    body: PersonaGenerateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaGenerateResponse:
    body_md = await PersonaService(db).generate(admin, body.description)
    return PersonaGenerateResponse(body_md=body_md)
