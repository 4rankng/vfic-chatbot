"""Native Zalo chat status during outbound preparation windows.

The bot turn already pulses the temporary ``typing`` chat action for as long
as it prepares an answer (``app/graph/chat_status.py``). The recruiter reply
path had no equivalent: between the consultant pressing send and the provider
accepting the message, the candidate's chat stayed silent. Firing one status
pulse at preparation entry closes that gap.

Limits, all deliberate:

* Only the Zalo Bot Platform exposes ``sendChatAction``. Zalo OA and Facebook
  Messenger carry no typing operation on their adapters, so they are skipped
  before any config is resolved.
* The pulse is bounded by ``PREPARATION_CHAT_STATUS_TIMEOUT_SECONDS`` and
  every failure is swallowed: a cosmetic status must never delay or block the
  send it accompanies beyond that bound.
* One pulse, not a heartbeat — preparation is short. The long window (a whole
  agent turn) belongs to the graph's heartbeat.
"""

from __future__ import annotations

import asyncio
import logging

from app.channels import types as ct

logger = logging.getLogger(__name__)

# A status that has not landed within this window describes a preparation
# that is already over, so it is dropped instead of delaying the send.
PREPARATION_CHAT_STATUS_TIMEOUT_SECONDS = 2.0


async def fire_preparation_chat_status(
    db, *, channel: str, recipient_id: str | None
) -> None:
    """Pulse the native Zalo status once while a message is being prepared.

    Best-effort by contract: returns normally on any timeout, transport
    failure, or provider rejection.
    """
    if channel != ct.PROVIDER_ZALO_BOT or not recipient_id:
        # Zalo OA / Messenger: no typing operation to fire.
        return

    from app.channels.dispatch import build_zalo_registry_from_config
    from app.services.integration_settings import IntegrationSettingsService

    try:
        cfg = await IntegrationSettingsService(db).resolve_zalo()
        typing = build_zalo_registry_from_config(cfg).get_typing(channel)
        if typing is None:
            return
        result = await asyncio.wait_for(
            typing.send_typing(account_key="", recipient_id=recipient_id),
            timeout=PREPARATION_CHAT_STATUS_TIMEOUT_SECONDS,
        )
        if result is not None and not result.ok:
            logger.debug(
                "preparation chat status rejected error_type=%s",
                type(result.error).__name__,
            )
    except Exception as exc:  # noqa: BLE001 — status is cosmetic, never blocking
        logger.debug("preparation chat status failed error_type=%s", type(exc).__name__)
