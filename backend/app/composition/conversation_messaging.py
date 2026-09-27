"""Composition root for conversation and durable messaging use cases."""

from __future__ import annotations

import asyncio
import logging
import time

from app.conversation_messaging.application.outbound_recovery import (
    OutboundRecoveryCandidate,
    recover_outbound_batch,
)
from app.conversation_messaging.infrastructure.outbound_recovery import (
    SqlAlchemyOutboundRecoveryAdapter,
)
from app.conversation_messaging.infrastructure.delivery_status import (
    SqlAlchemyDeliveryStatusValues,
)
from app.conversation_messaging.application.http import (
    ConversationHttpRecord,
    InlineWebChatTurnResult,
)
from app.shared.domain.errors import ConflictError, DomainError

logger = logging.getLogger(__name__)


def build_delivery_status_values() -> SqlAlchemyDeliveryStatusValues:
    return SqlAlchemyDeliveryStatusValues()


def enqueue_chat_turn(job) -> bool | None:
    from app.workers.chatbot_worker import enqueue_chat_run

    return enqueue_chat_run(job)


async def enqueue_chat_turn_async(job) -> bool | None:
    """Off-loop entry point for the single ``enqueue_chat_turn`` core.

    ``enqueue_chat_turn`` reaches Redis through the synchronous redis-py client,
    so awaiting it directly from an ASGI handler holds the event loop on network
    I/O. Async webhook handlers await this instead: it runs the identical call on
    the default executor. Return shape and backpressure semantics
    (``False``/``None`` -> the caller's 503 path) are unchanged.
    """
    return await asyncio.to_thread(enqueue_chat_turn, job)


def webhook_app_env() -> str:
    from app.core.config import get_settings

    return get_settings().app_env


async def run_inline_web_chat_turn(
    *,
    db,
    conversation: ConversationHttpRecord,
    conversation_id,
    message_body: str,
    actor_id,
) -> InlineWebChatTurnResult:
    from app.core.config import get_settings
    from app.graph.factories import build_deps
    from app.graph.runner import run_turn
    from app.graph.types import BotRunState
    from app.services.installation.service import InstallationService

    active = await InstallationService(db).resolve_active()
    if active is None:
        raise ConflictError(
            "Chatbot chưa được bật. Hãy hoàn tất cấu hình rồi bật chatbot trước khi thử hội thoại.",
        )
    authority = active.fingerprint
    now = time.time()
    state = BotRunState(
        conversation_id=str(conversation_id),
        version_at_start=conversation.version,
        user_text=message_body,
        user_name="",
        reply_to_message_id="",
        lock_owner="web_chat",
        received_at_epoch=now,
        deadline_at_epoch=now + get_settings().sla_seconds,
        preamble_start_epoch=now,
        queue_depth=None,
        execution_source="web_chat",
        trace_id=f"webchat-{actor_id.hex}-{int(now)}",
        runtime_revision_id=str(authority.revision_id),
        authority_generation=authority.authority_generation,
        runtime_fingerprint=authority.checksum(),
    )
    try:
        outcome = await run_turn(state, deps=await build_deps(db))
    except Exception as exc:  # noqa: BLE001 - surface the failure as a 500 with its detail
        raise DomainError(str(exc)) from exc
    return {
        "outcome": outcome.get("outcome"),
        "reply": outcome.get("reply"),
        "conversation_id": str(conversation_id),
    }


async def run_zalo_ingress(
    db,
    payload,
    *,
    enqueue,
    channel: str = "bot",
    bot_token: str | None = None,
    runtime_authority=None,
    account_key: str | None = None,
):
    """Execute the established Zalo transaction from the composition boundary."""
    from app.services.webhook import ZaloWebhookService
    from app.workers.persistence_worker import enqueue_enrich_oa_profile

    return await ZaloWebhookService.handle(
        db,
        payload,
        enqueue=enqueue,
        channel=channel,
        bot_token=bot_token,
        runtime_authority=runtime_authority,
        enrich_oa_profile=enqueue_enrich_oa_profile,
        account_key=account_key,
    )


def enqueue_messenger_profile_enrichment(*, psid: str, page_id: str) -> None:
    """Queue a Messenger profile lookup for one sender.

    Kept at the composition boundary for the same reason as the Zalo
    equivalent: the API layer stays free of direct worker imports.
    """
    from app.workers.persistence_worker import enqueue_enrich_messenger_profile

    enqueue_enrich_messenger_profile({"psid": psid, "page_id": page_id})


def _log_recovery_failure(candidate: OutboundRecoveryCandidate, error: Exception) -> None:
    logger.error(
        "outbound dispatcher failed for outbox id=%s",
        candidate.outbox_id,
        exc_info=(type(error), error, error.__traceback__),
    )


async def run_outbound_recovery() -> None:
    """Build production adapters and execute one bounded recovery sweep."""

    from app.core.config import get_settings
    from app.services.outbox_service import outbound_dispatch_stale_after_seconds
    from app.workers._db import worker_session

    settings = get_settings()
    adapter = SqlAlchemyOutboundRecoveryAdapter(
        session_factory=worker_session,
        stale_after_seconds=outbound_dispatch_stale_after_seconds(settings)
    )
    await recover_outbound_batch(adapter, on_failure=_log_recovery_failure)


__all__ = [
    "SqlAlchemyOutboundRecoveryAdapter",
    "build_delivery_status_values",
    "enqueue_chat_turn",
    "enqueue_chat_turn_async",
    "run_outbound_recovery",
    "run_inline_web_chat_turn",
    "run_zalo_ingress",
    "webhook_app_env",
]
