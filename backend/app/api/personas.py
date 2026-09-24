"""Personas admin API — thin HTTP layer over :class:`PersonaService`.

A persona is the bot's voice (free-form markdown). Several may be stored; exactly one
*global* persona is active at a time. All persistence and activation live in
``app.services.personas``; this router only validates input, delegates,
and serializes the response.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_admin
from app.identity.application.http import AuthenticatedUser as User
from app.schemas.personas import (
    PersonaAssignmentListResponse,
    PersonaAssignmentOut,
    PersonaAssignmentUpdate,
    PersonaCreate,
    PersonaListResponse,
    PersonaOut,
    PersonaUpdate,
    PersonaVersionListResponse,
    PersonaVersionMetadataOut,
)
from app.services.ingestion.limits import (
    MAX_UPLOAD_BYTES,
    IngestionLimitError,
    assert_upload_size,
)
from app.services.personas import (
    PersonaService,
    load_persona_template,
    persona_out_from_model,
)
from app.shared.domain.errors import BadRequestError, ValidationError
from app.shared.infrastructure.db import get_request_db as get_db

router = APIRouter(prefix="/knowledge/personas", tags=["personas"])
versions_router = APIRouter(prefix="/personas", tags=["personas"])
assignments_router = APIRouter(prefix="/knowledge/persona-assignments", tags=["personas"])


@router.get("", response_model=PersonaListResponse)
async def list_personas(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    q: str | None = Query(None, description="Case-insensitive search over Agent name, slug, notes"),
    sort: str | None = Query(None, description="Sort field (name, slug, created_at, updated_at)"),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaListResponse:
    rows, total = await PersonaService(db).list(
        page=page,
        per_page=per_page,
        q=q,
        sort_by=sort,
        order=order,
    )
    return PersonaListResponse(data=[persona_out_from_model(row) for row in rows], total=total)


@assignments_router.get("", response_model=PersonaAssignmentListResponse)
async def list_persona_assignments(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaAssignmentListResponse:
    return PersonaAssignmentListResponse(data=await PersonaService(db).list_adapter_assignments())


@assignments_router.put("/{provider}", response_model=PersonaAssignmentOut)
async def update_persona_assignment(
    provider: str,
    body: PersonaAssignmentUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaAssignmentOut:
    try:
        return await PersonaService(db).update_adapter_assignment(provider, body, admin)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(
    body: PersonaCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    return persona_out_from_model(await PersonaService(db).create(body, admin))


@router.get("/{persona_id}", response_model=PersonaOut)
async def get_persona(
    persona_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    persona = await PersonaService(db).get(persona_id)
    return persona_out_from_model(persona)


@versions_router.get("/{persona_id}/versions", response_model=PersonaVersionListResponse)
async def list_persona_versions(
    persona_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaVersionListResponse:
    versions = await PersonaService(db).list_versions(persona_id)
    return PersonaVersionListResponse(
        data=[PersonaVersionMetadataOut.model_validate(version) for version in versions]
    )


@router.patch("/{persona_id}", response_model=PersonaOut)
async def update_persona(
    persona_id: uuid.UUID,
    body: PersonaUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    return persona_out_from_model(await PersonaService(db).update(persona_id, body, admin))


@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(
    persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> None:
    await PersonaService(db).delete(persona_id)


@router.post("/{persona_id}/activate", response_model=PersonaOut)
async def activate_persona(
    persona_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PersonaOut:
    try:
        return persona_out_from_model(await PersonaService(db).activate(persona_id))
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc


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
    knowledge_base_id: uuid.UUID | None = Query(None),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PersonaOut:
    data = await file.read()
    try:
        # A persona is markdown; the shared 20 MiB upload ceiling keeps a
        # multi-gigabyte body from being buffered and parsed (SEC-05).
        assert_upload_size(len(data))
    except IngestionLimitError as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Tệp vượt quá giới hạn {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        ) from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationError("Tệp không phải UTF-8 hợp lệ.") from None
    try:
        persona = await PersonaService(db).import_persona(text, admin, knowledge_base_id)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return persona_out_from_model(persona)
