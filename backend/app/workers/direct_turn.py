"""The direct (ASGI) chat-turn bridge.

An interactive inbound message never enters an RQ queue: the webhook has already
committed it and acquired the per-chat mutex, so the turn runs as a task on the
web process's own event loop. This module owns that bridge end to end — the
launcher, the shutdown drain, the durable lease heartbeat that keeps the lock
alive for as long as the turn runs, and the typing-indicator bridge that covers
the preamble before ``run_turn``'s own heartbeat takes over.

The turn body itself, the RQ enqueue policy and the crash guard stay in
``chatbot_worker.py``; this module only reaches across to the shared executor.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_direct_turn_tasks: set[asyncio.Task[None]] = set()
_DIRECT_TURN_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def start_direct_chat_turn(job: dict) -> bool:
    """Schedule an interactive turn on the current ASGI event loop.

    The webhook has already committed the inbound message and acquired the
    database lock. A process restart is therefore recoverable by the offline
    reconciliation sweep; normal user turns never enter an RQ queue.
    """
    from app.workers.chatbot_worker import _run_job_async

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.exception("direct chat turn could not be scheduled")
        return False
    task = loop.create_task(_run_job_async(job, source="direct"))
    _direct_turn_tasks.add(task)

    def _log_completion(completed: asyncio.Task[None]) -> None:
        _direct_turn_tasks.discard(completed)
        try:
            completed.result()
        except asyncio.CancelledError:
            logger.warning("direct chat turn cancelled conversation=%s", job.get("conversation_id"))
        except Exception:
            logger.exception("direct chat turn failed conversation=%s", job.get("conversation_id"))

    task.add_done_callback(_log_completion)
    return True


async def drain_direct_chat_turns(*, timeout_seconds: float | None = None) -> None:
    """Finish direct turns when possible, then cancel and drain stragglers."""
    timeout = (
        _DIRECT_TURN_SHUTDOWN_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    pending = {task for task in _direct_turn_tasks if not task.done()}
    if not pending:
        return
    _done, pending = await asyncio.wait(pending, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def renew_direct_lock(job: dict) -> None:
    """Keep a direct turn's durable lease fresh without sharing its DB session."""
    conversation_id = job.get("conversation_id")
    lock_owner = job.get("lock_owner")
    if not conversation_id or not lock_owner:
        return

    import uuid

    from app.core.config import get_settings
    from app.core.db import async_session
    from app.services.conversation.events import ConversationEventBus
    from app.services.conversation.repository import ConversationRepository
    from app.services.conversation.state import ConversationState

    settings = get_settings()
    try:
        conv_id = uuid.UUID(str(conversation_id))
    except ValueError:
        logger.warning("direct chat turn has invalid conversation id=%r", conversation_id)
        return

    while True:
        await asyncio.sleep(settings.direct_turn_heartbeat_seconds)
        try:
            async with async_session() as db:
                # The lease lives in conversation state, so the heartbeat builds
                # the same composition the service builds and calls the same
                # method — the lock SQL stays in exactly one place.
                state = ConversationState(
                    db, ConversationRepository(db), ConversationEventBus(db)
                )
                renewed = await state.renew_lock(conv_id, lock_owner=str(lock_owner))
        except Exception:  # noqa: BLE001
            # A short database blip must not permanently disable lease renewal.
            # Retrying on the regular cadence stays well inside stale-lock detection.
            logger.warning(
                "direct chat turn lease heartbeat failed conversation=%s",
                conversation_id,
                exc_info=True,
            )
            continue
        if not renewed:
            logger.info("direct chat turn lease no longer owned conversation=%s", conversation_id)
            return


async def bridge_typing(chat_id: str, bot_token: str | None = None) -> None:
    """Track native status throughout dependency setup, until the owner drains it.

    Each pulse resolves live credentials when no legacy token was supplied.
    Transient resolution/provider failures retry on the same bounded cadence;
    neither a fixed pulse limit nor a stale environment token ends the bridge.
    """
    from app.core.config import get_settings
    from app.graph.chat_status import native_status_heartbeat

    async def emit_typing() -> None:
        token = bot_token
        if token is None:
            from app.core.db import async_session
            from app.services.integration_settings import IntegrationSettingsService

            async with async_session() as db:
                cfg = await IntegrationSettingsService(db).resolve_zalo()
                token = cfg.bot_token
        if not token:
            return
        from app.services.webhook import _fire_typing

        await _fire_typing(chat_id, token)

    await native_status_heartbeat(
        emit_typing,
        interval_seconds=get_settings().typing_heartbeat_seconds,
    )
