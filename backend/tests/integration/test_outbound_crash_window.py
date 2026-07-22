"""Provider acceptance must leave a durable no-resend dispatch claim."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.conversation import DeliveryStatus, Message, MessageSender
from app.models.outbox import OutboundOutbox, OutboxStatus
from app.services.installation.repository import InstallationRepository
from app.services.integration_settings import IntegrationSettingsService
from app.services.conversation.state import ConversationState
from app.services.outbox_service import (
    DispatchResult,
    _refresh_oa_access_token_for_dispatch,
    dispatch_outbox,
)
from tests.integration._conv_factory import make_zalo_conversation
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        pass

    async def conversation_updated(self, _conversation) -> None:
        pass


async def test_provider_acceptance_survives_caller_rollback_as_sending(
    integration_database: IntegrationDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash before finalization must never expose the command as retryable."""

    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    provider_calls: list[int] = []
    provider_observed_statuses: list[str] = []
    try:
        async with sessions() as db:
            conversation = await make_zalo_conversation(
                db,
                zalo_chat_id="outbound-crash-window",
            )
            message = Message(
                conversation_id=conversation.id,
                sender=MessageSender.BOT,
                body="accepted provider payload",
                delivery_status=DeliveryStatus.PENDING,
            )
            db.add(message)
            await db.flush()
            outbox = OutboundOutbox(
                message_id=message.id,
                channel="zalo_bot",
                payload={"chat_id": "outbound-crash-window", "text": message.body},
                status=OutboxStatus.PENDING.value,
            )
            db.add(outbox)
            await db.commit()
            outbox_id = outbox.id

        async def fake_resolve_zalo(_service):
            return SimpleNamespace()

        async def fake_provider_dispatch(
            _db,
            candidate,
            _outbox,
            _cfg,
            _settings,
            _oa_refresh,
        ):
            provider_calls.append(candidate.outbox_id)
            async with sessions() as observer:
                durable = await observer.get(OutboundOutbox, candidate.outbox_id)
                assert durable is not None
                provider_observed_statuses.append(durable.status)
            return DispatchResult(
                outbox_id=candidate.outbox_id,
                message_id=candidate.message_id,
                ok=True,
                provider_message_id="provider-accepted",
            )

        monkeypatch.setattr(
            "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
            fake_resolve_zalo,
        )
        monkeypatch.setattr(
            "app.services.outbox_service._try_neutral_dispatch",
            fake_provider_dispatch,
        )

        async with sessions() as db:
            result = await dispatch_outbox(db, outbox_id=outbox_id)
            assert result is not None and result.ok
            assert provider_calls == [outbox_id]
            assert provider_observed_statuses == [OutboxStatus.SENDING.value]
            # Simulate process loss after the provider accepted the command but
            # before the caller could persist the final provider receipt.
            await db.rollback()

        async with sessions() as db:
            durable = await db.get(OutboundOutbox, outbox_id)
            assert durable is not None
            assert durable.status == OutboxStatus.SENDING.value
            assert durable.attempts == 1
    finally:
        await engine.dispose()


async def test_oa_refresh_reacquires_dispatch_authority_lock_after_commit(
    integration_database: IntegrationDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential rotation commits independently while the send fence stays held."""

    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def committed_refresh(service) -> str:
        await service.db.execute(text("SELECT 1"))
        await service.db.commit()
        return "rotated-access-token"

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.refresh_oa_access_token",
        committed_refresh,
    )

    try:
        async with sessions() as dispatch_db:
            await InstallationRepository(dispatch_db).acquire_runtime_dispatch_lock()

            integration_settings = IntegrationSettingsService(dispatch_db)

            async def revalidate() -> bool:
                await InstallationRepository(
                    dispatch_db
                ).acquire_runtime_dispatch_lock()
                return True

            assert (
                await _refresh_oa_access_token_for_dispatch(
                    integration_settings,
                    revalidate=revalidate,
                )
                == "rotated-access-token"
            )

            async with sessions() as activation_db:
                await activation_db.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(DBAPIError):
                    await InstallationRepository(activation_db).acquire_authority_lock()
                await activation_db.rollback()

            await dispatch_db.rollback()

        async with sessions() as activation_db:
            await activation_db.execute(text("SET LOCAL lock_timeout = '1s'"))
            await InstallationRepository(activation_db).acquire_authority_lock()
            await activation_db.rollback()
    finally:
        await engine.dispose()


async def test_receipt_wins_when_transport_finalization_arrives_late(
    integration_database: IntegrationDatabase,
) -> None:
    """A receipt-first READ row must not be duplicated or downgraded."""

    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            conversation = await make_zalo_conversation(
                db,
                zalo_chat_id="receipt-before-transport-finalization",
            )
            pending = Message(
                conversation_id=conversation.id,
                sender=MessageSender.BOT,
                body="pending reply",
                delivery_status=DeliveryStatus.READ,
                zalo_message_id="provider-confirmed",
            )
            db.add(pending)
            await db.commit()
            pending_id = pending.id
            conversation_id = conversation.id

        async with sessions() as db:
            conversation = await db.get(type(conversation), conversation_id)
            assert conversation is not None
            result = await ConversationState(
                db,
                repo=None,
                events=_NoopEvents(),
            ).record_bot_outcome(
                conversation,
                version_at_start=conversation.version,
                reply="final reply",
                started_at=datetime.now(timezone.utc),
                sent=False,
                pending_message_id=pending_id,
                external_error="provider response timed out",
                delivery_status=DeliveryStatus.SEND_UNKNOWN,
                outbox_channel="zalo_oa",
                outbox_payload={"chat_id": "oa:user", "text": "final reply"},
            )

            assert result.id == pending_id
            assert result.delivery_status == DeliveryStatus.READ
            assert result.external_error is None
            assert result.zalo_message_id == "provider-confirmed"

        async with sessions() as db:
            messages = (
                await db.execute(
                    text(
                        "SELECT id, delivery_status FROM messages "
                        "WHERE conversation_id = :conversation_id AND sender = 'BOT'"
                    ),
                    {"conversation_id": conversation_id},
                )
            ).all()
            assert messages == [(pending_id, DeliveryStatus.READ.value)]
            outbox = await db.scalar(
                text(
                    "SELECT status FROM outbound_outbox WHERE message_id = :message_id"
                ),
                {"message_id": pending_id},
            )
            assert outbox == OutboxStatus.SENT.value
    finally:
        await engine.dispose()
