"""Installation setup and lifecycle API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.installation import (
    InstallationAdminOut,
    InstallationCatalogOut,
    InstallationRevisionCreate,
    InstallationRevisionOut,
    InstallationRuntimeOut,
    InstallationSetupDraftFinalize,
    InstallationSetupDraftOut,
    InstallationSetupDraftSave,
    InstallationValidationOut,
)
from app.services.installation.service import InstallationService
from app.services.installation.setup import InstallationSetupService

router = APIRouter(tags=["installation"])


@router.get("/installation/runtime", response_model=InstallationRuntimeOut)
async def get_installation_runtime(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> InstallationRuntimeOut:
    response.headers["Cache-Control"] = "no-store"
    return await InstallationService(db).runtime_view()


@router.get("/admin/installation/setup-draft", response_model=InstallationSetupDraftOut)
async def get_installation_setup_draft(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationSetupDraftOut:
    return await InstallationSetupService(db).view()


@router.put("/admin/installation/setup-draft", response_model=InstallationSetupDraftOut)
async def save_installation_setup_draft(
    body: InstallationSetupDraftSave,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationSetupDraftOut:
    return await InstallationSetupService(db).save(body, admin.id)


@router.post(
    "/admin/installation/setup-draft/finalize",
    response_model=InstallationRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def finalize_installation_setup_draft(
    body: InstallationSetupDraftFinalize,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationRevisionOut:
    return await InstallationSetupService(db).finalize(body, admin.id)


@router.get("/admin/installation/catalog", response_model=InstallationCatalogOut)
async def get_installation_catalog(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationCatalogOut:
    return await InstallationSetupService(db).catalog()


@router.get("/admin/installation", response_model=InstallationAdminOut)
async def get_installation_admin(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationAdminOut:
    return await InstallationService(db).admin_view()


@router.post(
    "/admin/installation/revisions",
    response_model=InstallationRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_installation_revision(
    body: InstallationRevisionCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationRevisionOut:
    revision = await InstallationService(db).create_revision(body, admin.id)
    return InstallationRevisionOut.model_validate(revision)


@router.post(
    "/admin/installation/revisions/{revision_id}/validate",
    response_model=InstallationValidationOut,
)
async def validate_installation_revision(
    revision_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationValidationOut:
    validation = await InstallationService(db).validate_revision(revision_id, admin.id)
    return InstallationValidationOut.model_validate(validation)


@router.post(
    "/admin/installation/revisions/{revision_id}/activate",
    response_model=InstallationAdminOut,
)
async def activate_installation_revision(
    revision_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationAdminOut:
    service = InstallationService(db)
    await service.activate_revision(revision_id, admin.id)
    return await service.admin_view()


@router.post(
    "/admin/installation/revisions/{revision_id}/rollback",
    response_model=InstallationAdminOut,
)
async def rollback_installation_revision(
    revision_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationAdminOut:
    service = InstallationService(db)
    await service.rollback_revision(revision_id, admin.id)
    return await service.admin_view()


@router.post("/admin/installation/suspend", response_model=InstallationAdminOut)
async def suspend_installation(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationAdminOut:
    service = InstallationService(db)
    await service.suspend(admin.id)
    return await service.admin_view()


@router.post("/admin/installation/resume", response_model=InstallationAdminOut)
async def resume_installation(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InstallationAdminOut:
    service = InstallationService(db)
    await service.resume(admin.id)
    return await service.admin_view()
