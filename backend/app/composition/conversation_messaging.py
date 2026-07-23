"""Composition root for conversation and durable messaging use cases."""

from __future__ import annotations

import logging

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
from app.conversation_messaging.infrastructure.zalo_ingress import (
    LegacyZaloIngressAdapter,
)
from app.conversation_messaging.application.zalo_ingress import ZaloIngressUseCases

logger = logging.getLogger(__name__)


def build_delivery_status_values() -> SqlAlchemyDeliveryStatusValues:
    return SqlAlchemyDeliveryStatusValues()


def enqueue_chat_turn(job) -> bool | None:
    from app.workers.chatbot_worker import enqueue_chat_run

    return enqueue_chat_run(job)


def webhook_app_env() -> str:
    from app.core.config import get_settings

    return get_settings().app_env


async def run_zalo_ingress(
    db,
    payload,
    *,
    enqueue,
    channel: str = "bot",
    bot_token: str | None = None,
    runtime_authority=None,
):
    """Build the compatibility adapter at the HTTP composition boundary."""
    from app.workers.persistence_worker import enqueue_enrich_oa_profile

    return await ZaloIngressUseCases(LegacyZaloIngressAdapter(db)).handle(
        payload,
        enqueue=enqueue,
        channel=channel,
        bot_token=bot_token,
        runtime_authority=runtime_authority,
        enrich_oa_profile=enqueue_enrich_oa_profile,
    )


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
    "run_outbound_recovery",
    "run_zalo_ingress",
    "webhook_app_env",
]
