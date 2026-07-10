"""Conversation API: list/get/messages + mode changes/close/reopen/read + recruiter reply.

The recruiter-reply endpoint (POST /{id}/messages) enforces JWT + ownership +
human-capable mode, sends via Zalo, inserts the recruiter message + audit, and
fans out events.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_admin
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


async def _load(conv_id: uuid.UUID, db: AsyncSession, user: User | None = None) -> Conversation:
    if user is None:
        conv = await db.get(Conversation, conv_id)
    else:
        conv = await ConversationService(db).get_visible(conv_id, viewer=user)
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
    """Count of conversations where the latest user message is still unanswered,
    scoped to the viewer. Lightweight count for the topbar notification badge —
    replaces the previous useGetList(perPage=500) + client-side filter.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``needs-attention``
    segment is never shadowed by the uuid path param.
    """
    count = await ConversationService(db).needs_attention_count(viewer=user)
    return {"count": count}


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(await _load(conv_id, db, user))


@router.get("/{conv_id}/last-messages", response_model=list[MessageOut])
async def last_messages(
    conv_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    conv = await _load(conv_id, db, user)
    svc = ConversationService(db)
    return [MessageOut.model_validate(m) for m in await svc.last_messages(conv, limit)]


@router.get("/{conv_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conv_id: uuid.UUID,
    per_page: int = Query(50, ge=1, le=200),
    limit: int | None = Query(
        None, ge=1, le=200, description="Cursor page size alias for per_page"
    ),
    before_id: int | None = Query(
        None, description="Cursor: return messages older than this message id (load-more)"
    ),
    before: int | None = Query(
        None, description="Cursor alias: return messages older than this message id"
    ),
    since_id: int | None = Query(
        None,
        description="Reconnect gap-fill: return messages NEWER than this message id",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    conv = await _load(conv_id, db, user)
    svc = ConversationService(db)
    page_size = limit if limit is not None else per_page
    if since_id is not None:
        # Gap-fill path: fetch everything newer than the client's newest known msg.
        msgs = await svc.messages_since(conv, since_id=since_id, limit=200)
        return MessageListResponse(
            data=[MessageOut.model_validate(m) for m in msgs], total=len(msgs)
        )
    cursor = before if before is not None else before_id
    msgs = await svc.messages_page(conv, limit=page_size, before_id=cursor)
    return MessageListResponse(data=[MessageOut.model_validate(m) for m in msgs], total=len(msgs))


@router.post("/{conv_id}/take-over", response_model=ConversationOut)
async def take_over(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = await _load(conv_id, db, user)
    try:
        conv = await ConversationService(db).take_over(conv, user)
    except ConversationConflict as exc:
        who = exc.owner_name or "nhân viên khác"
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Đã được {who} tiếp nhận"
        )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/release", response_model=ConversationOut)
async def release(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    svc = ConversationService(db)
    conv = await svc.release_and_enqueue_unanswered(
        await _load(conv_id, db, user),
        user,
        enqueue=enqueue_chat_run,
    )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/semi-auto", response_model=ConversationOut)
async def semi_auto(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    conv = await _load(conv_id, db, user)
    try:
        conv = await ConversationService(db).semi_auto(conv, user)
    except ConversationConflict as exc:
        who = exc.owner_name or "nhân viên khác"
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Đã được {who} tiếp nhận"
        )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/close", response_model=ConversationOut)
async def close(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).close(await _load(conv_id, db, user), user)
    )


@router.post("/{conv_id}/reopen", response_model=ConversationOut)
async def reopen(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).reopen(await _load(conv_id, db, user), user)
    )


@router.post("/{conv_id}/read", response_model=ConversationOut)
async def mark_read(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).mark_read(await _load(conv_id, db, user))
    )


@router.delete("/{conv_id}/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation_history(
    conv_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conv = await _load(conv_id, db)
    await ConversationService(db).clear_history(conv, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conv_id}/messages", response_model=MessageOut)
async def send_recruiter_message(
    conv_id: uuid.UUID,
    body: SendMessageRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    conv = await _load(conv_id, db, user)
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
