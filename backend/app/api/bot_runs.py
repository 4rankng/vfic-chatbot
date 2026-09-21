"""Bot-run admin API: read-only list of the takeover race-guard audit trail.

Readable by any authenticated user (both admin + recruiter) — this is an
org-wide ops diagnostic, matching the frontend automation page. Note
`proposed_reply` is the bot's draft and may echo candidate content; writes are
bot-side only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user, require_admin
from app.identity.application.http import AuthenticatedUser
from app.schemas.bot_run import BotRunListResponse, BotRunOut, BotRunOutcome, BotRunTraceDetailOut
from app.shared.domain.errors import NotFoundError
from app.shared.infrastructure.db import get_request_db
from app.services.bot_run_service import BotRunService

router = APIRouter(prefix="/bot_runs", tags=["bot_runs"])


@router.get("", response_model=BotRunListResponse)
async def list_bot_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    conversation_id: uuid.UUID | None = None,
    outcome: BotRunOutcome | None = None,
    _user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> BotRunListResponse:
    # Read-only ops audit trail; both roles may view (writes are bot-side only).
    rows, total = await BotRunService(db).list(
        conversation_id=conversation_id, outcome=outcome, page=page, per_page=per_page
    )
    return BotRunListResponse(data=[BotRunOut.model_validate(r) for r in rows], total=total)


@router.get("/{run_id}", response_model=BotRunTraceDetailOut)
async def get_bot_run_detail(
    run_id: int,
    _admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> BotRunTraceDetailOut:
    detail = await BotRunService(db).get_trace_detail(run_id)
    if detail is None:
        raise NotFoundError("bot run not found")
    return detail
