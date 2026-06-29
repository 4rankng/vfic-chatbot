"""Conversation API: list/get/messages + mode changes/close/reopen/read + recruiter reply.

The recruiter-reply endpoint (POST /{id}/messages) is the replacement for the n8n
"Human Reply" webhook: it enforces JWT + ownership + human-capable mode, sends
via Zalo (server-side token), inserts the RECRUITER message + audit, and fans
out events.
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
from app.services.conversation import ConversationConflict, ConversationService
from app.workers.chatbot_worker import enqueue_chat_run

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
    needs_attention: bool = False,
    q: str | None = Query(None, description="Case-insensitive search over zalo_chat_id"),
    sort: str | None = Query(
        None, description="Sort field (updated_at, created_at, last_inbound_at)"
    ),
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
        needs_attention=needs_attention,
        q=q,
        sort_by=sort,
        order=order,
    )
    return ConversationListResponse(
        data=[ConversationOut.model_validate(r) for r in rows], total=total
    )


@router.get("/last-messages/batch")
async def last_messages_batch(
    ids: str = Query(..., description="Comma-separated conversation UUIDs (max 200)"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Latest message snippet per conversation (inbox row previews) in ONE request.

    Replaces the client-side N-fanout over GET /{conv_id}/last-messages. Returns
    ``{"snippets": {conversation_id: body}}`` for the conversations the viewer can
    see; missing conversations are simply absent from the map.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``last-messages``
    segment can never be shadowed by the uuid path param (defensive against a
    future retyping of conv_id to str).
    """
    snippets = await ConversationService(db).last_messages_batch(viewer=user, ids_str=ids)
    return {"snippets": snippets}


@router.get("/needs-attention")
async def needs_attention(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Count of conversations needing a human (mode=HUMAN or unread_count>0),
    scoped to the viewer. Lightweight count for the topbar notification badge —
    replaces the previous useGetList(perPage=500) + client-side filter.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``needs-attention``
    segment is never shadowed by the uuid path param.
    """
    count = await ConversationService(db).needs_attention_count(viewer=user)
    return {"count": count}


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
    before_id: int | None = Query(
        None, description="Cursor: return messages older than this message id (load-more)"
    ),
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
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Hội thoại đã được tiếp nhận bởi nhân viên khác"
        )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/release", response_model=ConversationOut)
async def release(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    svc = ConversationService(db)
    conv = await svc.release(await _load(conv_id, db), user)
    pending = await svc.latest_unanswered_worker_message(conv)
    if pending is not None and await svc.acquire_lock(conv.id):
        enqueued = enqueue_chat_run(
            {
                "conversation_id": str(conv.id),
                "version_at_start": conv.version,
                "user_text": pending.body,
                "user_name": "",
                "received_at": pending.created_at.isoformat(),
            }
        )
        if not enqueued:
            await svc.release_lock(conv.id)
            import logging

            logging.getLogger(__name__).warning(
                "release enqueue failed for conversation %s; lock released", conv.id
            )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/semi-auto", response_model=ConversationOut)
async def semi_auto(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = await _load(conv_id, db)
    try:
        conv = await ConversationService(db).semi_auto(conv, user)
    except ConversationConflict:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Hội thoại đã được tiếp nhận bởi nhân viên khác"
        )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/close", response_model=ConversationOut)
async def close(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).close(await _load(conv_id, db), user)
    )


@router.post("/{conv_id}/reopen", response_model=ConversationOut)
async def reopen(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).reopen(await _load(conv_id, db), user)
    )


@router.post("/{conv_id}/read", response_model=ConversationOut)
async def mark_read(
    conv_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).mark_read(await _load(conv_id, db))
    )


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
    allowed = conv.mode in (
        ConversationMode.HUMAN,
        ConversationMode.SEMI_AUTO,
    ) and (owns or user.role == Role.admin)
    if not allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bạn cần tiếp nhận hội thoại trước khi trả lời"
        )
    # The RECRUITER message is persisted in both outcomes (FAILED rows are the
    # audit trail and surface in the thread via SSE); the HTTP status reports
    # whether the upstream Zalo delivery itself succeeded.
    msg, delivered = await ConversationService(db).deliver_recruiter_message(conv, user, body.body)
    response.status_code = status.HTTP_201_CREATED if delivered else status.HTTP_502_BAD_GATEWAY
    return MessageOut.model_validate(msg)
