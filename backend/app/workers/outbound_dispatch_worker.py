"""Bounded recovery sweep for durable outbound commands."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_outbound_dispatch_tick() -> None:
    """RQ scheduler entrypoint; dispatches commands left PENDING after a crash."""
    from app.workers.async_runner import run_async

    run_async(_dispatch_pending())


async def _dispatch_pending() -> None:
    from app.models.conversation import Conversation, Message
    from app.services.conversation import ConversationService
    from app.services.outbox_service import (
        DispatchResult,
        claim_stale_sending_unknown,
        dispatch_outbox,
        pending_outbox_ids,
        stale_sending_outbox_ids,
    )
    from app.workers._db import worker_session

    async with worker_session() as db:
        ids = await pending_outbox_ids(db)
        from app.core.config import get_settings

        stale_ids = await stale_sending_outbox_ids(
            db, stale_after_seconds=get_settings().chat_turn_job_timeout
        )

    candidates = [(outbox_id, False) for outbox_id in ids]
    candidates.extend((outbox_id, True) for outbox_id in stale_ids)
    for outbox_id, is_stale in candidates:
        async with worker_session() as db:
            try:
                if is_stale:
                    candidate = await claim_stale_sending_unknown(
                        db,
                        outbox_id=outbox_id,
                        stale_after_seconds=get_settings().chat_turn_job_timeout,
                    )
                    if candidate is None:
                        continue
                    result = DispatchResult(
                        outbox_id=candidate.outbox_id,
                        message_id=candidate.message_id,
                        ok=False,
                        error="outbound dispatch interrupted before receipt",
                        error_class="unknown",
                    )
                else:
                    result = await dispatch_outbox(db, outbox_id=outbox_id)
                if result is None:
                    continue
                msg = await db.get(Message, result.message_id)
                if msg is None:
                    logger.warning("outbound dispatcher: missing message id=%s", result.message_id)
                    continue
                conv = await db.get(Conversation, msg.conversation_id)
                if conv is None:
                    logger.warning(
                        "outbound dispatcher: missing conversation for message=%s", msg.id
                    )
                    continue
                await ConversationService(db).finalize_outbound_dispatch(
                    conv,
                    message_id=result.message_id,
                    outbox_id=result.outbox_id,
                    delivered=result.ok,
                    zalo_message_id=result.zalo_message_id,
                    external_error=result.error,
                    error_class=result.error_class,
                )
            except Exception:  # noqa: BLE001 - one command must not stop recovery
                logger.exception("outbound dispatcher failed for outbox id=%s", outbox_id)
