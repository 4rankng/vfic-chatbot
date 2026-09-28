"""Lead CRM API: list/get/update + assign/stage(+lead_events)/follow-ups/events."""

from __future__ import annotations
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user
from app.api.installation_dependencies import require_capability_or_legacy
from app.identity.application.http import AuthenticatedUser as User
from app.recruitment.domain.statuses import LeadStage
from app.schemas.lead import (
    AssignRequest,
    LeadBoardQuery,
    LeadBoardResponse,
    LeadBoardSection,
    FollowUpCreate,
    FollowUpOut,
    LeadAssistOut,
    LeadChatOpsActionResult,
    LeadEventOut,
    LeadListResponse,
    LeadMemoryOut,
    LeadOut,
    LeadTagOut,
    LeadTagsUpdate,
    LeadUpdate,
    StageRequest,
)
from app.shared.domain.errors import BadRequestError, ConflictError, NotFoundError
from app.shared.infrastructure.rate_limits import (
    enforce_lead_assist_rate_limit,
    enforce_lead_chatops_action_rate_limit,
)
from app.services.lead import LeadService
from app.services.memory_repository import MemoryRepository
from app.shared.infrastructure.db import get_request_db as get_db

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
    dependencies=[Depends(require_capability_or_legacy("candidate_intake"))],
)


async def _load(lead_id: int, db: AsyncSession, viewer: User):
    """Load one lead through the viewer-scope invariant.

    Out-of-scope ids raise 404 (not 403) so the sequential lead ids are not
    probeable: a recruiter may only reach their own or unassigned leads, an
    admin reaches every lead.
    """
    lead = await LeadService(db).get_visible(lead_id, viewer=viewer)
    if lead is None:
        raise NotFoundError("lead not found")
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
    contact_id: uuid.UUID | None = Query(
        None, description="Filter to the lead of one contact (Messenger rows have NULL zalo_id)"
    ),
    q: str | None = Query(
        None, description="Case-insensitive search over name/phone/desired_job/zalo_id"
    ),
    sort: str | None = Query(
        None, description="Sort field (updated_at, created_at, name, lead_stage, lead_score)"
    ),
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
        contact_id=str(contact_id) if contact_id else None,
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
async def get_lead(
    lead_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> LeadOut:
    return LeadOut.model_validate(await _load(lead_id, db, user))


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: int,
    body: LeadUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    lead = await _load(lead_id, db, user)
    changes = body.model_dump(exclude_unset=True)
    try:
        stage = changes.pop("lead_stage", None)
        service = LeadService(db)
        if stage is not None:
            lead = await service.set_stage(lead, stage, actor=user)
            # `set_stage` advanced the row version and refreshed `lead`, so the
            # caller's original version is now stale. Re-arm the guard with the
            # fresh value: discarding it (the previous behaviour) pushed the
            # remaining fields onto the unchecked write path and silently lost
            # concurrent edits.
            if changes:
                changes["version"] = lead.version
        if changes:
            lead = await service.update(lead, changes)
        return LeadOut.model_validate(lead)
    except ConflictError:
        raise ConflictError("Vừa được nhân viên khác thay đổi")


@router.post("/{lead_id}/assign", response_model=LeadOut)
async def assign_lead(
    lead_id: int,
    body: AssignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    lead = await _load(lead_id, db, user)
    try:
        return LeadOut.model_validate(
            await LeadService(db).assign(lead, body.recruiter_id, actor=user)
        )
    except ConflictError:
        raise ConflictError("Vừa được nhân viên khác thay đổi")


@router.post("/{lead_id}/stage", response_model=LeadOut)
async def set_stage(
    lead_id: int,
    body: StageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    lead = await _load(lead_id, db, user)
    try:
        return LeadOut.model_validate(await LeadService(db).set_stage(lead, body.stage, actor=user))
    except ConflictError:
        raise ConflictError("Vừa được nhân viên khác thay đổi")


@router.post(
    "/{lead_id}/follow-ups", response_model=FollowUpOut, status_code=status.HTTP_201_CREATED
)
async def create_followup(
    lead_id: int,
    body: FollowUpCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowUpOut:
    lead = await _load(lead_id, db, user)
    return FollowUpOut.model_validate(
        await LeadService(db).create_followup(lead, body.due_at, body.note, actor=user)
    )


@router.get("/{lead_id}/tags", response_model=list[LeadTagOut])
async def list_tags(
    lead_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadTagOut]:
    lead = await _load(lead_id, db, user)
    return [
        LeadTagOut.model_validate(tag) for tag in await LeadService(db).list_operational_tags(lead)
    ]


@router.put("/{lead_id}/tags", response_model=list[LeadTagOut])
async def update_tags(
    lead_id: int,
    body: LeadTagsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadTagOut]:
    lead = await _load(lead_id, db, user)
    return [
        LeadTagOut.model_validate(tag)
        for tag in await LeadService(db).replace_manual_tags(
            lead,
            body.keys,
            actor=user,
            tags=[tag.model_dump() for tag in body.tags],
        )
    ]


@router.get("/{lead_id}/assist", response_model=LeadAssistOut)
async def get_chatops_assist(
    lead_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadAssistOut:
    # SEC-04: chatops assist is an LLM call; budget it per recruiter.
    await enforce_lead_assist_rate_limit(user.id)
    lead = await _load(lead_id, db, user)
    return LeadAssistOut.model_validate(await LeadService(db).build_chatops_assist(lead))


@router.post("/{lead_id}/chatops-actions/{action}", response_model=LeadChatOpsActionResult)
async def run_chatops_action(
    lead_id: int,
    action: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadChatOpsActionResult:
    # SEC-04: a chatops action can spend an LLM call plus a send.
    await enforce_lead_chatops_action_rate_limit(user.id)
    lead = await _load(lead_id, db, user)
    service = LeadService(db)
    try:
        updated = await service.apply_chatops_action(lead, action, actor=user)
    except ValueError:
        raise BadRequestError("Thao tác ChatOps không hợp lệ")
    return LeadChatOpsActionResult(
        lead=LeadOut.model_validate(updated),
        tags=[
            LeadTagOut.model_validate(tag) for tag in await service.list_operational_tags(updated)
        ],
        assist=LeadAssistOut.model_validate(await service.build_chatops_assist(updated)),
    )


@router.get("/{lead_id}/follow-ups", response_model=list[FollowUpOut])
async def list_followups(
    lead_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[FollowUpOut]:
    await _load(lead_id, db, user)
    return [FollowUpOut.model_validate(f) for f in await LeadService(db).list_followups(lead_id)]


@router.get("/{lead_id}/events", response_model=list[LeadEventOut])
async def list_events(
    lead_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[LeadEventOut]:
    await _load(lead_id, db, user)
    return [LeadEventOut.model_validate(e) for e in await LeadService(db).list_events(lead_id)]


@router.get("/{lead_id}/memories", response_model=list[LeadMemoryOut])
async def list_memories(
    lead_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LeadMemoryOut]:
    lead = await _load(lead_id, db, user)
    if not lead.zalo_id:
        return []
    rows = await MemoryRepository(db).list_for_chat(lead.zalo_id)
    return [LeadMemoryOut.model_validate(row) for row in rows]


@router.get("/{lead_id}/presence")
async def get_lead_presence(
    lead_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Return current viewers and typing users for a lead."""
    from app.services.presence import get_typing_users, get_viewers

    await _load(lead_id, db, user)
    viewers = await get_viewers("lead", lead_id)
    typing = await get_typing_users("lead", str(lead_id))
    return {"viewers": viewers, "typing": typing}
