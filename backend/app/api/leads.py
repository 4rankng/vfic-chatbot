"""Lead CRM API: list/get/update + assign/stage(+lead_events)/follow-ups/events."""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.lead import LeadStage
from app.models.user import User
from app.schemas.lead import (
    AssignRequest,
    LeadBoardQuery,
    LeadBoardResponse,
    LeadBoardSection,
    FollowUpCreate,
    FollowUpOut,
    LeadEventOut,
    LeadListResponse,
    LeadMemoryOut,
    LeadOut,
    LeadUpdate,
    StageRequest,
)
from app.services.lead_service import LeadConflict, LeadService
from app.services.memory_repository import MemoryRepository

router = APIRouter(prefix="/leads", tags=["leads"])


async def _load(lead_id: int, db: AsyncSession):
    lead = await LeadService(db).get(lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
    return lead


@router.get("", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    stage: LeadStage | None = None,
    needs_reply: bool = Query(
        False,
        description="Return leads in the Cần trả lời queue.",
    ),
    exclude_needs_reply: bool = Query(
        False,
        description="Exclude Cần trả lời leads from results. Kept for API compatibility; stage sections normally include all leads.",
    ),
    zalo_id: str | None = None,
    zalo_ids: str | None = Query(None, description="Comma-separated list of zalo ids (IN filter)"),
    q: str | None = Query(None, description="Case-insensitive search over name/phone/desired_job/zalo_id"),
    sort: str | None = Query(None, description="Sort field (updated_at, created_at, name, lead_stage, lead_score)"),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadListResponse:
    zalo_id_list = [s for s in (zalo_ids.split(",") if zalo_ids else []) if s]
    rows, total = await LeadService(db).list(
        viewer=user,
        page=page,
        per_page=per_page,
        stage=stage,
        needs_reply=needs_reply,
        exclude_needs_reply=exclude_needs_reply,
        zalo_id=zalo_id,
        zalo_ids=zalo_id_list or None,
        q=q,
        sort_by=sort,
        order=order,
    )
    return LeadListResponse(data=[LeadOut.model_validate(r) for r in rows], total=total)


@router.post("/board", response_model=LeadBoardResponse)
async def lead_board(
    body: LeadBoardQuery,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadBoardResponse:
    sections, total = await LeadService(db).board(
        viewer=user,
        section_pages=body.section_pages,
        per_page=body.per_page,
        q=body.q,
        sort_by=body.sort,
        order=body.order,
    )
    return LeadBoardResponse(
        sections=[
            LeadBoardSection(
                key=section["key"],
                title=section["title"],
                data=[LeadOut.model_validate(row) for row in section["data"]],
                total=section["total"],
                page=section["page"],
                per_page=section["per_page"],
                is_priority=section["is_priority"],
            )
            for section in sections
        ],
        total=total,
    )


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(lead_id: int, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> LeadOut:
    return LeadOut.model_validate(await _load(lead_id, db))


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: int, body: LeadUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> LeadOut:
    lead = await _load(lead_id, db)
    changes = body.model_dump(exclude_unset=True)
    try:
        stage = changes.pop("lead_stage", None)
        service = LeadService(db)
        if stage is not None:
            lead = await service.set_stage(lead, stage, actor=user)
            changes.pop("version", None)
        if changes:
            lead = await service.update(lead, changes)
        return LeadOut.model_validate(lead)
    except LeadConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Vừa được nhân viên khác thay đổi")


@router.post("/{lead_id}/assign", response_model=LeadOut)
async def assign_lead(lead_id: int, body: AssignRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> LeadOut:
    lead = await _load(lead_id, db)
    try:
        return LeadOut.model_validate(await LeadService(db).assign(lead, body.recruiter_id, actor=user))
    except LeadConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Vừa được nhân viên khác thay đổi")


@router.post("/{lead_id}/stage", response_model=LeadOut)
async def set_stage(lead_id: int, body: StageRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> LeadOut:
    lead = await _load(lead_id, db)
    try:
        return LeadOut.model_validate(await LeadService(db).set_stage(lead, body.stage, actor=user))
    except LeadConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Vừa được nhân viên khác thay đổi")


@router.post("/{lead_id}/follow-ups", response_model=FollowUpOut, status_code=status.HTTP_201_CREATED)
async def create_followup(lead_id: int, body: FollowUpCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> FollowUpOut:
    lead = await _load(lead_id, db)
    return FollowUpOut.model_validate(await LeadService(db).create_followup(lead, body.due_at, body.note, actor=user))


@router.get("/{lead_id}/follow-ups", response_model=list[FollowUpOut])
async def list_followups(lead_id: int, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[FollowUpOut]:
    await _load(lead_id, db)
    return [FollowUpOut.model_validate(f) for f in await LeadService(db).list_followups(lead_id)]


@router.get("/{lead_id}/events", response_model=list[LeadEventOut])
async def list_events(lead_id: int, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[LeadEventOut]:
    await _load(lead_id, db)
    return [LeadEventOut.model_validate(e) for e in await LeadService(db).list_events(lead_id)]


@router.get("/{lead_id}/memories", response_model=list[LeadMemoryOut])
async def list_memories(
    lead_id: int,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadMemoryOut]:
    lead = await _load(lead_id, db)
    if not lead.zalo_id:
        return []
    rows = await MemoryRepository(db).list_for_chat(lead.zalo_id)
    return [LeadMemoryOut.model_validate(row) for row in rows]


@router.get("/{lead_id}/presence")
async def get_lead_presence(lead_id: int, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Return current viewers and typing users for a lead."""
    from app.services.presence import get_typing_users, get_viewers

    await _load(lead_id, db)
    viewers = await get_viewers("lead", lead_id)
    typing = await get_typing_users("lead", str(lead_id))
    return {"viewers": viewers, "typing": typing}
