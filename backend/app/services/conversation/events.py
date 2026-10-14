"""Realtime seam for conversation state changes.

The single place conversation/message realtime events are published. Extracts the
``publish_event(...)`` calls that were duplicated across every state transition in
``ConversationService``. Identical channels + payloads — just one definition now.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import inspect as sa_inspect

from app.core.incidents import count_incident, REALTIME_PAYLOAD_FAILURES
from app.schemas.conversation import ConversationOut, MessageOut
from app.services.realtime import publish_event

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[None]] = set()


def _release_background_task(task: asyncio.Task[None]) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logger.warning("realtime background publish failed", exc_info=error)


async def _ensure_realtime_ready(db, conv) -> None:
    """Load every relationship ``_conv_payload`` serializes, on this greenlet.

    ``ConversationOut`` walks ``contact`` → ``contact.primary_channel`` →
    ``channel_identities`` via ``from_attributes``. A conversation created on
    this session (``ensure_by_identity``'s create path) carries the
    ``contact``/``channel_identity`` references but leaves the contact's own
    columns and ``channel_identities`` unloaded — pydantic's attribute walk
    then triggers a lazy load outside the async greenlet and the publish dies
    with ``MissingGreenlet`` (2026-10-13/14 prod: ``conversation.updated``
    silently lost on new conversations). Loading here, before serialization,
    is the fix; a load failure only degrades the publish (counter + warning),
    never the caller's write path.
    """
    try:
        state = sa_inspect(conv)
    except Exception:  # noqa: BLE001 — not a mapped instance; serialization decides
        return
    try:
        if state.detached or state.session is None:
            return
        if "contact" in state.unloaded or "channel_identity" in state.unloaded:
            await db.refresh(conv, ["contact", "channel_identity"])
        contact = conv.__dict__.get("contact")
        # A created-path contact reaches here with ALL attributes unloaded
        # (only its PK was flushed); a fetched one is usually complete. A
        # full refresh loads the row and selectin-fires ``channel_identities``.
        if contact is not None and sa_inspect(contact).unloaded:
            await db.refresh(contact)
    except Exception:  # noqa: BLE001 — the load is armor, not a new failure mode
        logger.warning(
            "realtime eager load failed conversation=%s",
            getattr(conv, "id", "?"),
            exc_info=True,
        )
        count_incident(REALTIME_PAYLOAD_FAILURES)


def _conv_payload(conv) -> dict:
    """Serialize a conversation for the realtime `conversation.updated` payload.

    Shape is consumed verbatim by the frontend SSE/Socket.IO client — do not change.
    """
    return ConversationOut.model_validate(conv).model_dump(mode="json")


def _message_payload(msg) -> dict:
    """Serialize a message for the realtime `message.created` payload."""
    return MessageOut.model_validate(msg).model_dump(mode="json")


class ConversationEventBus:
    """Publishes conversation/message realtime events."""

    def __init__(self, db) -> None:
        self.db = db

    async def conversation_updated(self, conv) -> None:
        """Publish ``conversation.updated``; never raises.

        Payload serialization is armored end-to-end: relationships are
        eagerly loaded first (``_ensure_realtime_ready``), and a failure
        beyond that increments the visible failure counter instead of
        propagating — every caller (webhook ack, recruiter API, worker
        outcome writes) treats this event as best-effort bookkeeping.
        """
        await _ensure_realtime_ready(self.db, conv)
        try:
            payload = _conv_payload(conv)
        except Exception:  # noqa: BLE001 — the UI update must not fail the write
            logger.warning(
                "conversation.updated payload failed; skipping publish conversation=%s",
                getattr(conv, "id", "?"),
                exc_info=True,
            )
            count_incident(REALTIME_PAYLOAD_FAILURES)
            return
        await publish_event("conversation.updated", payload)

    async def message_created(self, msg, conv) -> None:
        await publish_event(
            "message.created",
            {
                "message_id": msg.id,
                "conversation_id": str(conv.id),
                "message": _message_payload(msg),
            },
        )

    async def ensure_realtime_ready(self, conv) -> None:
        """Public eager-load for callers that serialize via ``schedule_realtime``.

        The schedule path is synchronous and cannot await its own loads, so
        an async caller holding a freshly created conversation loads the
        payload relationships first — then ``schedule_realtime``'s eager
        serialization finds them present.
        """
        await _ensure_realtime_ready(self.db, conv)

    def schedule_realtime(self, msg, conv) -> None:
        """Fire-and-forget the post-commit realtime publishes for a new message.

        Payloads are serialized EAGERLY on the caller's coroutine; only the Redis
        publishes are deferred to a background task. This is required for
        correctness: ``expire_on_commit`` invalidates ``msg``/``conv`` after the
        commit in ``record_bot_pending``, so serializing them triggers lazy
        refreshes. Those refreshes are safe on the main greenlet but raise
        ``MissingGreenlet`` from a background task, which corrupts the shared
        session (``PendingRollbackError``) for the rest of the turn. Build here,
        publish there. The task is never awaited; with no running loop (a sync
        test path) the publishes are skipped rather than raising.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            message_payload = {
                "message_id": msg.id,
                "conversation_id": str(conv.id),
                "message": _message_payload(msg),
            }
            conversation_payload = _conv_payload(conv)
        except Exception:  # noqa: BLE001 — the UI update must not fail the write
            logger.warning(
                "realtime payload serialization failed; skipping publish",
                exc_info=True,
            )
            count_incident(REALTIME_PAYLOAD_FAILURES)
            return

        async def _emit() -> None:
            await publish_event("message.created", message_payload)
            await publish_event("conversation.updated", conversation_payload)

        task = loop.create_task(_emit())
        _background_tasks.add(task)
        task.add_done_callback(_release_background_task)
