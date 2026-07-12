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

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.conversation import BotRunOutcome
from app.models.user import User
from app.schemas.bot_run import BotRunListResponse, BotRunOut
from app.services.bot_run_service import BotRunService

router = APIRouter(prefix="/bot_runs", tags=["bot_runs"])


@router.get("", response_model=BotRunListResponse)
async def list_bot_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    conversation_id: uuid.UUID | None = None,
    outcome: BotRunOutcome | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BotRunListResponse:
    # Read-only ops audit trail; both roles may view (writes are bot-side only).
    rows, total = await BotRunService(db).list(
        conversation_id=conversation_id, outcome=outcome, page=page, per_page=per_page
    )
    return BotRunListResponse(data=[BotRunOut.model_validate(r) for r in rows], total=total)
