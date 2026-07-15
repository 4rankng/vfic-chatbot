"""Dormant authenticated generic Case API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_capability
from app.core.db import get_db
from app.models.case import Case, FollowupStatus
from app.models.case_workflow import CaseWorkflowVersion
from app.models.user import User
from app.schemas.case_workflows import CaseWorkflowSummaryOut
from app.schemas.cases import (
    CaseAssignRequest,
    CaseCreate,
    CaseFollowupCreate,
    CaseFollowupOut,
    CaseListResponse,
    CaseNoteCreate,
    CaseNoteOut,
    CaseOut,
    CaseTagsReplace,
    CaseTransitionRequest,
    CaseUpdate,
    CaseVersionRequest,
)
from app.services.case_service import CaseService

router = APIRouter(
    prefix="/cases", tags=["cases"], dependencies=[Depends(require_capability("conversation"))]
)


async def _out(
    service: CaseService,
    case: Case,
    *,
    tags: list[str] | None = None,
    workflow: CaseWorkflowVersion | None = None,
) -> CaseOut:
    if workflow is None:
        workflow = await service.db.get(CaseWorkflowVersion, case.workflow_version_id)
    if tags is None:
        tags = await service.tags(case)
    return CaseOut.model_validate(
        {
            **case.__dict__,
            "tags": tags,
            "workflow": CaseWorkflowSummaryOut.model_validate(workflow) if workflow else None,
        }
    )


@router.get("", response_model=CaseListResponse)
async def list_cases(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    contact_id: uuid.UUID | None = None,
    stage: str | None = Query(None, max_length=64),
    lifecycle: str | None = Query(None, pattern="^(OPEN|CLOSED|CANCELLED)$"),
    assigned_user_id: uuid.UUID | None = None,
    sort: str | None = Query(None, pattern="^(created_at|updated_at|case_no)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseListResponse:
    service = CaseService(db)
    rows, total = await service.list(
        viewer=user,
        page=page,
        per_page=per_page,
        contact_id=contact_id,
        stage=stage,
        lifecycle=lifecycle,
        assignee_id=assigned_user_id,
        sort_by=sort,
        order=order,
    )
    tags_by_case, workflows = await service.list_projection(rows)
    return CaseListResponse(
        data=[
            await _out(
                service,
                row,
                tags=tags_by_case.get(row.id, []),
                workflow=workflows.get(row.workflow_version_id),
            )
            for row in rows
        ],
        total=total,
    )


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(
    body: CaseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CaseOut:
    service = CaseService(db)
    try:
        case = await service.create(body, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _out(service, case)


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CaseOut:
    service = CaseService(db)
    return await _out(service, await service.get_visible(case_id, user))


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: uuid.UUID,
    body: CaseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    try:
        updated = await service.update(case, body, user)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return await _out(service, updated)


@router.post("/{case_id}/assign", response_model=CaseOut)
async def assign_case(
    case_id: uuid.UUID,
    body: CaseAssignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return await _out(
        service,
        await service.assign(
            case, assignee_id=body.assigned_user_id, version=body.version, actor=user
        ),
    )


@router.post("/{case_id}/transition", response_model=CaseOut)
async def transition_case(
    case_id: uuid.UUID,
    body: CaseTransitionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return await _out(
        service,
        await service.transition(
            case, target=body.target_stage_key, version=body.version, actor=user
        ),
    )


@router.post("/{case_id}/cancel", response_model=CaseOut)
async def cancel_case(
    case_id: uuid.UUID,
    body: CaseVersionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return await _out(service, await service.cancel(case, version=body.version, actor=user))


@router.get("/{case_id}/tags", response_model=list[str])
async def list_case_tags(
    case_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[str]:
    service = CaseService(db)
    return await service.tags(await service.get_visible(case_id, user))


@router.put("/{case_id}/tags", response_model=CaseOut)
async def replace_case_tags(
    case_id: uuid.UUID,
    body: CaseTagsReplace,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return await _out(
        service,
        await service.replace_tags(case, tag_keys=body.tag_keys, version=body.version, actor=user),
    )


@router.get("/{case_id}/notes", response_model=list[CaseNoteOut])
async def list_case_notes(
    case_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CaseNoteOut]:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return [CaseNoteOut.model_validate(item) for item in await service.notes(case, limit=limit)]


@router.post("/{case_id}/notes", response_model=CaseNoteOut, status_code=status.HTTP_201_CREATED)
async def create_case_note(
    case_id: uuid.UUID,
    body: CaseNoteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseNoteOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return CaseNoteOut.model_validate(await service.add_note(case, body=body.body, actor=user))


@router.get("/{case_id}/follow-ups", response_model=list[CaseFollowupOut])
async def list_case_followups(
    case_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CaseFollowupOut]:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return [
        CaseFollowupOut.model_validate(item) for item in await service.followups(case, limit=limit)
    ]


@router.post(
    "/{case_id}/follow-ups", response_model=CaseFollowupOut, status_code=status.HTTP_201_CREATED
)
async def create_case_followup(
    case_id: uuid.UUID,
    body: CaseFollowupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFollowupOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return CaseFollowupOut.model_validate(await service.add_followup(case, body, user))


async def _finish_followup(
    case_id: uuid.UUID,
    followup_id: int,
    body: CaseVersionRequest,
    user: User,
    db: AsyncSession,
    target: FollowupStatus,
) -> CaseFollowupOut:
    service = CaseService(db)
    case = await service.get_visible(case_id, user)
    return CaseFollowupOut.model_validate(
        await service.finish_followup(
            case, followup_id, version=body.version, status=target, actor=user
        )
    )


@router.post("/{case_id}/follow-ups/{followup_id}/complete", response_model=CaseFollowupOut)
async def complete_case_followup(
    case_id: uuid.UUID,
    followup_id: int,
    body: CaseVersionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFollowupOut:
    return await _finish_followup(case_id, followup_id, body, user, db, FollowupStatus.COMPLETED)


@router.post("/{case_id}/follow-ups/{followup_id}/cancel", response_model=CaseFollowupOut)
async def cancel_case_followup(
    case_id: uuid.UUID,
    followup_id: int,
    body: CaseVersionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseFollowupOut:
    return await _finish_followup(case_id, followup_id, body, user, db, FollowupStatus.CANCELLED)
