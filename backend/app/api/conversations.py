"""Conversation API: list/get/messages + mode changes/close/reopen/read + recruiter reply.

The recruiter-reply endpoint (POST /{id}/messages) enforces JWT + ownership +
human-capable mode, sends via Zalo, inserts the recruiter message + audit, and
fans out events.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import get_current_user, require_admin
from app.composition.conversation_messaging import (
    enqueue_chat_turn,
    run_inline_web_chat_turn,
)
from app.composition.reporting import run_conversation_attention_query
from app.conversation_messaging.application.http import ConversationHttpRecord
from app.conversation_messaging.domain.statuses import ConversationMode, ConversationStatus
from app.conversation_messaging.infrastructure.http import load_conversation_record
from app.identity.application.http import AuthenticatedUser
from app.identity.domain.role import Role
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationOut,
    MessageListResponse,
    MessageOut,
    SendMessageRequest,
)
from app.schemas.dashboard import AttentionReason
from app.shared.domain.errors import ConflictError, NotFoundError, ValidationError
from app.shared.infrastructure.db import get_request_db
from app.shared.infrastructure.rate_limits import enforce_web_chat_turn_rate_limit
from app.services.conversation import ConversationConflict, ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ``tingting_oa`` is the employee-support OA: the same zalo_oa provider, filtered
# to the one linked account. It is a separate badge on the conversations page so
# admins can read those threads without mixing them into the recruitment inbox.
ChannelProvider = Literal["zalo_bot", "zalo_oa", "facebook_messenger", "tingting_oa"]


async def _load(
    conv_id: uuid.UUID,
    db: AsyncSession,
    user: AuthenticatedUser | None = None,
) -> ConversationHttpRecord:
    if user is None:
        conv = await load_conversation_record(db, conv_id)
    else:
        # The inbox's viewer scoping is a repository concern (admin = all,
        # recruiter = own + unassigned), so the read goes to the part that owns it.
        conv = await ConversationService(db).repo.get_visible(conv_id, viewer=user)
    if conv is None:
        raise NotFoundError("conversation not found")
    return conv


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    mode: ConversationMode | None = None,
    status_: ConversationStatus | None = Query(None, alias="status"),
    zalo_chat_id: str | None = None,
    needs_attention: bool = False,
    channel_provider: ChannelProvider | None = None,
    q: str | None = Query(None, description="Case-insensitive search over zalo_chat_id"),
    sort: str | None = Query(
        None, description="Sort field (updated_at, created_at, last_inbound_at)"
    ),
    order: str | None = Query("desc", description="Sort direction: asc | desc"),
    reason: str | None = Query(
        None,
        description=(
            "Attention reason filter (DELIVERY_REVIEW|HUMAN_ESCALATION|REPLY_OVERDUE|"
            "FOLLOWUP_OVERDUE|WAITING_REPLY|PRIORITY_NO_ACTION|FOLLOWUP_TODAY|"
            "UNREAD|STALLED). Routes the recruiter to the conversations the attention "
            "dashboard surfaced for this reason."
        ),
    ),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationListResponse:
    svc = ConversationService(db)
    if reason is not None:
        # Validate against the canonical enum; FastAPI does not do this for a
        # plain str param, so reject unknown values with 422 explicitly.
        if reason not in AttentionReason._value2member_map_:
            raise ValidationError("invalid reason")
        rows, total = await run_conversation_attention_query(
            db,
            viewer=user,
            reason=reason,
            page=page,
            per_page=per_page,
            channel_provider=channel_provider,
        )
        return ConversationListResponse(
            data=[ConversationOut.model_validate(r) for r in rows], total=total
        )
    rows, total = await svc.repo.list(
        viewer=user,
        page=page,
        per_page=per_page,
        mode=mode,
        status=status_,
        zalo_chat_id=zalo_chat_id,
        needs_attention=needs_attention,
        channel_provider=channel_provider,
        q=q,
        sort_by=sort,
        order=order,
    )
    return ConversationListResponse(
        data=[ConversationOut.model_validate(r) for r in rows], total=total
    )


@router.get("/by-zalo-ids", response_model=ConversationListResponse)
async def list_conversations_by_zalo_ids(
    ids: str = Query(..., description="Comma-separated Zalo chat ids (max 200)"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationListResponse:
    zalo_chat_ids = list(dict.fromkeys(value for value in ids.split(",") if value))
    if not zalo_chat_ids or len(zalo_chat_ids) > 200:
        raise ValidationError("ids must contain between 1 and 200 Zalo chat ids")
    rows = await ConversationService(db).repo.list_by_zalo_ids(
        viewer=user,
        zalo_chat_ids=zalo_chat_ids,
    )
    return ConversationListResponse(
        data=[ConversationOut.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.get("/by-contact-ids", response_model=ConversationListResponse)
async def list_conversations_by_contact_ids(
    ids: str = Query(..., description="Comma-separated contact UUIDs (max 200)"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationListResponse:
    raw_ids = list(dict.fromkeys(value for value in ids.split(",") if value))
    if not raw_ids or len(raw_ids) > 200:
        raise ValidationError("ids must contain between 1 and 200 contact ids")
    try:
        contact_ids = [uuid.UUID(value) for value in raw_ids]
    except ValueError as exc:
        raise ValidationError("ids must be contact UUIDs") from exc
    rows = await ConversationService(db).repo.list_by_contact_ids(
        viewer=user,
        contact_ids=contact_ids,
    )
    return ConversationListResponse(
        data=[ConversationOut.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.get("/last-messages/batch")
async def last_messages_batch(
    ids: str = Query(..., description="Comma-separated conversation UUIDs (max 200)"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> dict:
    """Latest message snippet per conversation (inbox row previews) in ONE request.

    Replaces the client-side N-fanout over GET /{conv_id}/last-messages. Returns
    ``{"snippets": {conversation_id: body}}`` for the conversations the viewer can
    see; missing conversations are simply absent from the map.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``last-messages``
    segment can never be shadowed by the uuid path param (defensive against a
    future retyping of conv_id to str).
    """
    snippets = await ConversationService(db).repo.last_messages_batch(viewer=user, ids_str=ids)
    return {"snippets": snippets}


@router.get("/needs-attention")
async def needs_attention(
    channel_provider: ChannelProvider | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> dict:
    """Count of conversations where the latest user message is still unanswered,
    scoped to the viewer. Lightweight count for the topbar notification badge —
    replaces the previous useGetList(perPage=500) + client-side filter.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``needs-attention``
    segment is never shadowed by the uuid path param.
    """
    count = await ConversationService(db).repo.needs_attention_count(
        viewer=user, channel_provider=channel_provider
    )
    return {"count": count}


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    return ConversationOut.model_validate(await _load(conv_id, db, user))


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: uuid.UUID,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> Response:
    """Permanently remove a spam or test conversation from the inbox.

    Database foreign keys cascade to messages and bot runs. The candidate lead is
    intentionally retained so a future Zalo message can start a clean thread.
    """
    await ConversationService(db).state.delete(await _load(conv_id, db), admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conv_id}/last-messages", response_model=list[MessageOut])
async def last_messages(
    conv_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> list[MessageOut]:
    conv = await _load(conv_id, db, user)
    svc = ConversationService(db)
    return [MessageOut.model_validate(m) for m in await svc.repo.last_messages(conv, limit)]


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
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> MessageListResponse:
    conv = await _load(conv_id, db, user)
    svc = ConversationService(db)
    page_size = limit if limit is not None else per_page
    if since_id is not None:
        # Gap-fill path: fetch everything newer than the client's newest known msg.
        msgs = await svc.repo.messages_since(conv, since_id=since_id, limit=200)
        return MessageListResponse(
            data=[MessageOut.model_validate(m) for m in msgs], total=len(msgs)
        )
    cursor = before if before is not None else before_id
    msgs = await svc.repo.messages_page(conv, limit=page_size, before_id=cursor)
    return MessageListResponse(data=[MessageOut.model_validate(m) for m in msgs], total=len(msgs))


@router.post("/{conv_id}/take-over", response_model=ConversationOut)
async def take_over(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    conv = await _load(conv_id, db, user)
    try:
        conv = await ConversationService(db).state.take_over(conv, user)
    except ConversationConflict as exc:
        who = exc.owner_name or "nhân viên khác"
        raise ConflictError(f"Đã được {who} tiếp nhận")
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/release", response_model=ConversationOut)
async def release(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    svc = ConversationService(db)
    try:
        conv = await svc.release_and_enqueue_unanswered(
            await _load(conv_id, db, user),
            user,
            enqueue=enqueue_chat_turn,
        )
    except ConversationConflict as exc:
        who = exc.owner_name or "một nhân viên"
        raise ConflictError(
            f"Cần tiếp quản hội thoại trước khi trả lại ChatBot ({who})."
        )
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/semi-auto", response_model=ConversationOut)
async def semi_auto(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    conv = await _load(conv_id, db, user)
    try:
        conv = await ConversationService(db).state.semi_auto(conv, user)
    except ConversationConflict as exc:
        who = exc.owner_name or "nhân viên khác"
        raise ConflictError(f"Đã được {who} tiếp nhận")
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/close", response_model=ConversationOut)
async def close(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).state.close(await _load(conv_id, db, user), user)
    )


@router.post("/{conv_id}/reopen", response_model=ConversationOut)
async def reopen(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).state.reopen(await _load(conv_id, db, user), user)
    )


@router.post("/{conv_id}/read", response_model=ConversationOut)
async def mark_read(
    conv_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> ConversationOut:
    return ConversationOut.model_validate(
        await ConversationService(db).state.mark_read(await _load(conv_id, db, user))
    )


@router.delete("/{conv_id}/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation_history(
    conv_id: uuid.UUID,
    admin: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> Response:
    conv = await _load(conv_id, db)
    await ConversationService(db).state.clear_history(conv, admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conv_id}/messages", response_model=MessageOut)
async def send_recruiter_message(
    conv_id: uuid.UUID,
    body: SendMessageRequest,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> MessageOut:
    conv = await _load(conv_id, db, user)
    owns = conv.assigned_recruiter_id == user.id
    allowed = conv.mode in (
        ConversationMode.HUMAN,
        ConversationMode.SEMI_AUTO,
    ) and (owns or user.role == Role.admin)
    if not allowed:
        raise ConflictError("Bạn cần tiếp nhận hội thoại trước khi trả lời")
    # The RECRUITER message is persisted in both outcomes (FAILED rows are the
    # audit trail and surface in the thread via SSE); the HTTP status reports
    # whether the upstream Zalo delivery itself succeeded.
    msg, delivered = await ConversationService(db).deliver_recruiter_message(conv, user, body.body)
    response.status_code = status.HTTP_201_CREATED if delivered else status.HTTP_502_BAD_GATEWAY
    return MessageOut.model_validate(msg)


@router.post("/{conv_id}/messages/{message_id}/retry", response_model=MessageOut)
async def retry_recruiter_message(
    conv_id: uuid.UUID,
    message_id: int,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_request_db),
) -> MessageOut:
    """Retry one definite recruiter delivery failure without adding a message row."""
    conv = await _load(conv_id, db, user)
    owns = conv.assigned_recruiter_id == user.id
    allowed = conv.mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO) and (
        owns or user.role == Role.admin
    )
    if not allowed:
        raise ConflictError("Bạn cần tiếp nhận hội thoại trước khi trả lời")
    msg, delivered = await ConversationService(db).retry_recruiter_message(
        conv, message_id=message_id
    )
    if msg is None:
        raise ConflictError("Tin nhắn này không còn ở trạng thái có thể thử lại.")
    response.status_code = status.HTTP_201_CREATED if delivered else status.HTTP_502_BAD_GATEWAY
    return MessageOut.model_validate(msg)


@router.post("/{conv_id}/web-chat-turn")
async def web_chat_turn(
    conv_id: uuid.UUID,
    body: SendMessageRequest,
    user: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_request_db),
) -> dict:
    """Run a bot turn INLINE (not via RQ) for recruiter-side bot testing.

    Tech-Lead Directive §0: "For web chat, execute the turn directly in the
    async API and stream the response." This endpoint lets a recruiter submit a
    candidate-style message and see the bot's reply without enqueuing through
    RQ. Reuses every existing safety/grounding/ownership guard.

    Semantics:
    - Admin-only (require_admin). The recruiter is explicitly invoking the bot.
    - Bypasses takeover suppression: an admin testing the bot in a taken-over
      conversation still gets a bot reply (the recruiter CHOSE to invoke it).
    - Respects the per-conversation lock: a concurrent Zalo turn in flight
      returns 409 (don't run two turns on one conversation).
    - No streaming (option A from the plan) — returns the final reply as JSON.
      Streaming (option B) deferred until the LLM client supports it cheaply.

    The endpoint is for INTERNAL bot testing, not candidate-facing web chat
    (candidates chat via Zalo). A candidate-facing web-chat surface would need
    a different architecture (WebSocket-first, not HTTP).
    """
    conv = await _load(conv_id, db, user)
    # SEC-04: this runs a full bot turn inline, so it has to be budgeted per user.
    await enforce_web_chat_turn_rate_limit(user.id)
    return await run_inline_web_chat_turn(
        db=db,
        conversation=conv,
        conversation_id=conv_id,
        message_body=body.body,
        actor_id=user.id,
    )
