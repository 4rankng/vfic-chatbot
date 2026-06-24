"""Conversation API: list/get/messages + takeover/release/close/reopen/read + recruiter reply.

The recruiter-reply endpoint (POST /{id}/messages) is the replacement for the n8n
"Human Reply" webhook: it enforces JWT + ownership + mode=HUMAN, sends via Zalo
(server-side token), inserts the RECRUITER message + audit, and fans out events.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.user import Role, User
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationOut,
    MessageListResponse,
    MessageOut,
    SendMessageRequest,
)
from app.services.conversation_service import ConversationConflict, ConversationService
from app.services.zalo_service import ZaloMessageService

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _load(conv_id: uuid.UUID, db: AsyncSession) -> Conversation:
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return conv


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    mode: ConversationMode | None = None,
    status_: ConversationStatus | None = Query(None, alias="status"),
    zalo_chat_id: str | None = None,
    q: str | None = Query(None, description="Case-insensitive search over zalo_chat_id"),
    sort: str | None = Query(None, description="Sort field (updated_at, created_at, last_inbound_at)"),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    svc = ConversationService(db)
    rows, total = await svc.list(
        viewer=user,
        page=page,
        per_page=per_page,
        mode=mode,
        status=status_,
        zalo_chat_id=zalo_chat_id,
        q=q,
        sort_by=sort,
        order=order,
    )
    return ConversationListResponse(data=[ConversationOut.model_validate(r) for r in rows], total=total)


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(await _load(conv_id, db))


@router.get("/{conv_id}/last-messages", response_model=list[MessageOut])
async def last_messages(
    conv_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    conv = await _load(conv_id, db)
    svc = ConversationService(db)
    return [MessageOut.model_validate(m) for m in await svc.last_messages(conv, limit)]


@router.get("/{conv_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conv_id: uuid.UUID,
    per_page: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, description="Cursor: return messages older than this message id (load-more)"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    conv = await _load(conv_id, db)
    svc = ConversationService(db)
    msgs = await svc.messages_page(conv, limit=per_page, before_id=before_id)
    return MessageListResponse(data=[MessageOut.model_validate(m) for m in msgs], total=len(msgs))


@router.post("/{conv_id}/take-over", response_model=ConversationOut)
async def take_over(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = await _load(conv_id, db)
    try:
        conv = await ConversationService(db).take_over(conv, user)
    except ConversationConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hội thoại đã được tiếp nhận bởi nhân viên khác")
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/release", response_model=ConversationOut)
async def release(conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ConversationOut:
    return ConversationOut.model_validate(await ConversationService(db).release(await _load(conv_id, db), user))


@router.post("/{conv_id}/close", response_model=ConversationOut)
async def close(conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ConversationOut:
    return ConversationOut.model_validate(await ConversationService(db).close(await _load(conv_id, db), user))


@router.post("/{conv_id}/reopen", response_model=ConversationOut)
async def reopen(conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ConversationOut:
    return ConversationOut.model_validate(await ConversationService(db).reopen(await _load(conv_id, db), user))


@router.post("/{conv_id}/read", response_model=ConversationOut)
async def mark_read(conv_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ConversationOut:
    return ConversationOut.model_validate(await ConversationService(db).mark_read(await _load(conv_id, db)))


@router.post("/{conv_id}/messages", response_model=MessageOut)
async def send_recruiter_message(
    conv_id: uuid.UUID,
    body: SendMessageRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    conv = await _load(conv_id, db)
    owns = conv.assigned_recruiter_id == user.id
    allowed = conv.mode == ConversationMode.HUMAN and (owns or user.role == Role.admin)
    if not allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bạn cần tiếp nhận hội thoại trước khi trả lời"
        )
    result = await ZaloMessageService().send(conv.zalo_chat_id, body.body)
    # The RECRUITER message is persisted in both outcomes (FAILED rows are the
    # audit trail and surface in the thread via SSE); the HTTP status reports
    # whether the upstream Zalo delivery itself succeeded.
    msg = await ConversationService(db).record_recruiter_message(conv, user, body.body, result)
    response.status_code = status.HTTP_201_CREATED if result.ok else status.HTTP_502_BAD_GATEWAY
    return MessageOut.model_validate(msg)
