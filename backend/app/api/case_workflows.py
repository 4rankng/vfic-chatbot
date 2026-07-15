"""Pre-activation admin API for immutable case workflow publication."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.db import get_db
from app.models.user import User
from app.schemas.case_workflows import (
    CaseWorkflowCreate,
    CaseWorkflowListResponse,
    CaseWorkflowOut,
    CaseWorkflowSummaryOut,
    WorkflowStageOut,
    WorkflowTagOut,
    WorkflowTransitionOut,
)
from app.services.case_workflow_service import CaseWorkflowService

router = APIRouter(prefix="/admin/case-workflows", tags=["case-workflows"])


@router.get("", response_model=CaseWorkflowListResponse)
async def list_case_workflows(
    pack_key: str | None = Query(None, max_length=64),
    workflow_key: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CaseWorkflowListResponse:
    rows, total = await CaseWorkflowService(db).list(
        pack_key=pack_key, workflow_key=workflow_key, page=page, per_page=per_page
    )
    return CaseWorkflowListResponse(
        data=[CaseWorkflowSummaryOut.model_validate(row) for row in rows], total=total
    )


@router.post("", response_model=CaseWorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_case_workflow(
    body: CaseWorkflowCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CaseWorkflowOut:
    service = CaseWorkflowService(db)
    try:
        version = await service.create(body, admin.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _out(service, version.id)


@router.get("/{version_id}", response_model=CaseWorkflowOut)
async def get_case_workflow(
    version_id: uuid.UUID, _admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> CaseWorkflowOut:
    return await _out(CaseWorkflowService(db), version_id)


async def _out(service: CaseWorkflowService, version_id: uuid.UUID) -> CaseWorkflowOut:
    version, stages, transitions, tags = await service.get(version_id)
    return CaseWorkflowOut(
        **CaseWorkflowSummaryOut.model_validate(version).model_dump(),
        schema_version=version.schema_version,
        case_attribute_schema=version.case_attribute_schema,
        stages=[
            WorkflowStageOut(
                key=item.stage_key,
                label=item.label,
                position=item.position,
                is_initial=item.is_initial,
                is_terminal=item.is_terminal,
            )
            for item in stages
        ],
        transitions=[WorkflowTransitionOut.model_validate(item) for item in transitions],
        tags=[
            WorkflowTagOut(
                key=item.tag_key, label=item.label, tone=item.tone, position=item.position
            )
            for item in tags
        ],
    )
