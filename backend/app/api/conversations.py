"""Conversation API: list/get/messages + mode changes/close/reopen/read + recruiter reply.

The recruiter-reply endpoint (POST /{id}/messages) enforces JWT + ownership +
human-capable mode, sends via Zalo, inserts the recruiter message + audit, and
fans out events.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, require_admin
from app.core.db import get_db
from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.user import Role, User
from app.schemas.bot_run import BotRunTraceSummaryListResponse
from app.schemas.conversation import (
    ConversationListResponse,
    ConversationOut,
    MessageListResponse,
    MessageOut,
    SendMessageRequest,
)
from app.schemas.dashboard import AttentionReason
from app.services.bot_run_service import BotRunService
from app.services.conversation import ConversationConflict, ConversationService
from app.workers.chatbot_worker import enqueue_chat_run

router = APIRouter(prefix="/conversations", tags=["conversations"])

ChannelProvider = Literal["zalo_bot", "zalo_oa"]


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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    svc = ConversationService(db)
    if reason is not None:
        # Validate against the canonical enum; FastAPI does not do this for a
        # plain str param, so reject unknown values with 422 explicitly.
        if reason not in AttentionReason._value2member_map_:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid reason")
        rows, total = await svc.list_by_attention_reason(
            viewer=user,
            reason=reason,
            page=page,
            per_page=per_page,
            channel_provider=channel_provider,
        )
        return ConversationListResponse(
            data=[ConversationOut.model_validate(r) for r in rows], total=total
        )
    rows, total = await svc.list(
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
    channel_provider: ChannelProvider | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Count of conversations where the latest user message is still unanswered,
    scoped to the viewer. Lightweight count for the topbar notification badge —
    replaces the previous useGetList(perPage=500) + client-side filter.

    Registered BEFORE the ``/{conv_id}`` routes so the literal ``needs-attention``
    segment is never shadowed by the uuid path param.
    """
    count = await ConversationService(db).needs_attention_count(
        viewer=user, channel_provider=channel_provider
    )
    return {"count": count}


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    return ConversationOut.model_validate(await _load(conv_id, db, user))


@router.get("/{conv_id}/bot-runs", response_model=BotRunTraceSummaryListResponse)
async def list_conversation_bot_runs(
    conv_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BotRunTraceSummaryListResponse:
    await _load(conv_id, db)
    rows, total = await BotRunService(db).list_conversation_trace_summaries(
        conversation_id=conv_id,
        page=page,
        per_page=per_page,
    )
    return BotRunTraceSummaryListResponse(data=rows, total=total)


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Permanently remove a spam or test conversation from the inbox.

    Database foreign keys cascade to messages and bot runs. The candidate lead is
    intentionally retained so a future Zalo message can start a clean thread.
    """
    await ConversationService(db).delete(await _load(conv_id, db), admin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        raise HTTPException(status.HTTP_409_CONFLICT, f"Đã được {who} tiếp nhận")
    return ConversationOut.model_validate(conv)


@router.post("/{conv_id}/release", response_model=ConversationOut)
async def release(
    conv_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ConversationOut:
    svc = ConversationService(db)
    try:
        conv = await svc.release_and_enqueue_unanswered(
            await _load(conv_id, db, user),
            user,
            enqueue=enqueue_chat_run,
        )
    except ConversationConflict as exc:
        who = exc.owner_name or "một nhân viên"
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cần tiếp quản hội thoại trước khi trả lại ChatBot ({who}).",
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
        raise HTTPException(status.HTTP_409_CONFLICT, f"Đã được {who} tiếp nhận")
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


@router.post("/{conv_id}/messages/{message_id}/retry", response_model=MessageOut)
async def retry_recruiter_message(
    conv_id: uuid.UUID,
    message_id: int,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    """Retry one definite recruiter delivery failure without adding a message row."""
    conv = await _load(conv_id, db, user)
    owns = conv.assigned_recruiter_id == user.id
    allowed = conv.mode in (ConversationMode.HUMAN, ConversationMode.SEMI_AUTO) and (
        owns or user.role == Role.admin
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Bạn cần tiếp nhận hội thoại trước khi trả lời"
        )
    msg, delivered = await ConversationService(db).retry_recruiter_message(
        conv, message_id=message_id
    )
    if msg is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Tin nhắn này không còn ở trạng thái có thể thử lại.",
        )
    response.status_code = status.HTTP_201_CREATED if delivered else status.HTTP_502_BAD_GATEWAY
    return MessageOut.model_validate(msg)


@router.post("/{conv_id}/web-chat-turn")
async def web_chat_turn(
    conv_id: uuid.UUID,
    body: SendMessageRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
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
    import time

    conv = await _load(conv_id, db, user)
    # Build the BotRunState. execution_source="web_chat" so the turn stamps it
    # into stage_timings and the SLO dashboard can filter it out of the
    # candidate-facing latency SLOs (web-chat turns are recruiter-initiated,
    # not candidate-visible).
    from app.core.config import get_settings
    from app.graph.factories import build_deps
    from app.graph.runner import run_turn
    from app.graph.types import BotRunState
    from app.services.installation.service import InstallationService

    settings = get_settings()
    active = await InstallationService(db).resolve_active()
    if active is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Chatbot chưa được bật. Hãy hoàn tất cấu hình rồi bật chatbot trước khi thử hội thoại.",
        )
    authority = active.fingerprint
    now = time.time()
    state = BotRunState(
        conversation_id=str(conv_id),
        version_at_start=conv.version,
        user_text=body.body,
        user_name="",
        reply_to_message_id="",
        lock_owner="web_chat",
        received_at_epoch=now,
        deadline_at_epoch=now + settings.sla_seconds,
        preamble_start_epoch=now,
        queue_depth=None,
        execution_source="web_chat",
        trace_id=f"webchat-{user.id.hex}-{int(now)}",
        runtime_revision_id=str(authority.revision_id),
        authority_generation=authority.authority_generation,
        runtime_fingerprint=authority.checksum(),
    )
    try:
        outcome = await run_turn(state, deps=await build_deps(db))
    except Exception as exc:  # noqa: BLE001 — surface as 500 with detail
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return {
        "outcome": outcome.get("outcome"),
        "reply": outcome.get("reply"),
        "conversation_id": str(conv_id),
    }
