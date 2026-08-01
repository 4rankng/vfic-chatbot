"""Integration tests for the Phase 4 Facebook Page lifecycle state machine.

Drives :class:`FacebookPageLifecycle` and :class:`FacebookAccountResolver`
against the disposable integration database. Exercises the recoverable
state-machine transitions: activate, reactivate (same-Page reuse + generation
advance), replacement (prior Page archived), and disconnect (inactive, history
preserved). No external HTTP — OAuth/Graph calls are not invoked here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.fixture
def sessions(integration_database):
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_resolver_returns_none_for_unknown_page(integration_database):
    from app.channels.providers.facebook_account import FacebookAccountResolver
    from app.core.db import async_session

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        assert (
            await resolver.resolve_active(provider="facebook_messenger", account_key="page-unknown")
            is None
        )
        assert (
            await resolver.resolve_any(provider="facebook_messenger", account_key="page-unknown")
            is None
        )
        assert await resolver.active_facebook_page() is None


async def test_lifecycle_activate_then_resolve_active(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin@vfic.test",
            password_hash="x",
            full_name="FB Admin",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        account = await lifecycle.activate_or_reactivate(
            page_id="page-111",
            page_name="Công ty ABC",
            page_access_token="EAAB-page-111-token",
            admin_id=admin_id,
        )
        assert account.status == "ACTIVE"
        assert account.account_key == "page-111"
        assert account.generation == 1

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        active = await resolver.active_facebook_page()
        assert active is not None
        assert active.is_active
        assert active.account_key == "page-111"
        assert active.generation == 1


async def test_pending_messenger_outbox_persists_active_page_generation(
    integration_database,
):
    """The durable command is fenced to the Page generation at creation time."""
    from app.channels.providers.facebook_account import FacebookPageLifecycle
    from app.core.db import async_session
    from app.models.contact import Contact, ContactChannelIdentity
    from app.models.conversation import (
        Conversation,
        ConversationMode,
        DeliveryStatus,
        Message,
        MessageSender,
    )
    from app.services.outbox_service import create_pending_outbox

    async with async_session() as db:
        admin = User(
            email="fb-outbox-generation@vfic.test",
            password_hash="x",
            full_name="FB Outbox Generation",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        account = await FacebookPageLifecycle(db).activate_or_reactivate(
            page_id="page-outbox-generation",
            page_name="Outbox Generation",
            page_access_token="EAAB-page-outbox-generation",
            admin_id=admin.id,
        )

        contact = Contact()
        db.add(contact)
        await db.flush()
        identity = ContactChannelIdentity(
            contact_id=contact.id,
            provider="facebook_messenger",
            account_key=account.account_key,
            external_id="PSID-outbox-generation",
        )
        db.add(identity)
        await db.flush()
        conversation = Conversation(
            zalo_channel="facebook_messenger",
            contact_id=contact.id,
            channel_identity_id=identity.id,
            mode=ConversationMode.BOT,
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            conversation_id=conversation.id,
            sender=MessageSender.BOT,
            body="reply",
            delivery_status=DeliveryStatus.PENDING,
        )
        db.add(message)
        await db.flush()

        outbox = await create_pending_outbox(
            db,
            message_id=message.id,
            channel="facebook_messenger",
            payload={"chat_id": identity.external_id, "text": message.body},
        )

        assert outbox.channel_account_generation == account.generation


async def test_messenger_outbox_dispatches_and_finalizes_through_production_route(
    integration_database,
    monkeypatch,
):
    """Creation, Page fence, policy, adapter dispatch, and finalization stay connected."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from app.channels import types as ct
    from app.channels.dispatch import ChannelAdapterRegistry
    from app.channels.providers.facebook_account import FacebookPageLifecycle
    from app.core.db import async_session
    from app.models.contact import Contact, ContactChannelIdentity
    from app.models.conversation import (
        Conversation,
        ConversationMode,
        DeliveryStatus,
        Message,
        MessageSender,
    )
    from app.models.outbox import OutboxStatus
    from app.services.conversation import ConversationService
    from app.services.outbox_service import create_pending_outbox, dispatch_outbox

    class _RecordingMessengerAdapter:
        provider = ct.PROVIDER_FACEBOOK_MESSENGER

        def __init__(self) -> None:
            self.sent: list[ct.OutboundTextCommand] = []
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send_text(self, command: ct.OutboundTextCommand) -> ct.ChannelSendResult:
            self.sent.append(command)
            self.entered.set()
            await self.release.wait()
            return ct.ChannelSendResult(ok=True, provider_message_id="mid-production-route")

    adapter = _RecordingMessengerAdapter()
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    monkeypatch.setattr(
        "app.channels.dispatch.build_facebook_registry",
        lambda config: registry,
    )

    async with async_session() as db:
        admin = User(
            email="fb-production-route@vfic.test",
            password_hash="x",
            full_name="FB Production Route",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        account = await FacebookPageLifecycle(db).activate_or_reactivate(
            page_id="page-production-route",
            page_name="Production Route",
            page_access_token="EAAB-page-production-route",
            admin_id=admin.id,
        )
        contact = Contact()
        db.add(contact)
        await db.flush()
        identity = ContactChannelIdentity(
            contact_id=contact.id,
            provider=ct.PROVIDER_FACEBOOK_MESSENGER,
            account_key=account.account_key,
            external_id="PSID-production-route",
        )
        db.add(identity)
        await db.flush()
        conversation = Conversation(
            zalo_channel=ct.PROVIDER_FACEBOOK_MESSENGER,
            contact_id=contact.id,
            channel_identity_id=identity.id,
            mode=ConversationMode.BOT,
            last_inbound_at=datetime.now(timezone.utc),
        )
        db.add(conversation)
        await db.flush()
        message = Message(
            conversation_id=conversation.id,
            sender=MessageSender.BOT,
            body="reply",
            delivery_status=DeliveryStatus.PENDING,
        )
        db.add(message)
        await db.flush()
        outbox = await create_pending_outbox(
            db,
            message_id=message.id,
            channel=ct.PROVIDER_FACEBOOK_MESSENGER,
            payload={"chat_id": identity.external_id, "text": message.body},
        )
        await db.commit()

        dispatch_task = asyncio.create_task(dispatch_outbox(db, outbox_id=outbox.id))
        await asyncio.wait_for(adapter.entered.wait(), timeout=2)

        async with async_session() as lifecycle_db:
            disconnect_task = asyncio.create_task(
                FacebookPageLifecycle(lifecycle_db).disconnect(
                    page_id=account.account_key,
                    admin_id=admin.id,
                )
            )
            done, _pending = await asyncio.wait({disconnect_task}, timeout=0.1)
            assert not done, "Page disconnect bypassed the in-flight dispatch authority lock"

            adapter.release.set()
            attempt = await dispatch_task

            assert attempt is not None and attempt.ok
            assert len(adapter.sent) == 1
            assert adapter.sent[0].channel_account_generation == account.generation
            conversation_service = ConversationService(db)
            conversation_service.events.message_created = AsyncMock()
            conversation_service.events.conversation_updated = AsyncMock()
            finalized = await conversation_service.finalize_outbound_dispatch(
                conversation,
                message_id=attempt.message_id,
                outbox_id=attempt.outbox_id,
                delivered=attempt.ok,
                zalo_message_id=attempt.zalo_message_id,
                external_error=attempt.error,
                error_class=attempt.error_class,
                suppressed=attempt.suppressed,
                telemetry=attempt.telemetry,
            )
            disconnected = await asyncio.wait_for(disconnect_task, timeout=2)
            assert disconnected is not None
        await db.refresh(outbox)

        assert finalized.delivery_status == DeliveryStatus.SENT
        assert finalized.provider_message_id == "mid-production-route"
        assert outbox.status == OutboxStatus.SENT.value
        assert outbox.provider_message_id == "mid-production-route"


async def test_lifecycle_reactivate_same_page_reuses_account_and_advances_generation(
    integration_database,
):
    """Same-Page reactivation reuses the existing account and rotates the token;
    generation advances so stale queued commands are suppressed."""
    from app.channels.providers.facebook_account import FacebookPageLifecycle
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin2@vfic.test",
            password_hash="x",
            full_name="FB Admin 2",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        first = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t1", admin_id=admin_id
        )
        first_generation = first.generation  # capture before second activation
        second = await lifecycle.activate_or_reactivate(
            page_id="page-222", page_name="P", page_access_token="t2", admin_id=admin_id
        )
        assert first.id == second.id  # same account reused
        # NOTE: first and second are the same ORM object (row reused), so
        # first.generation now reads the post-second value. Compare against the
        # captured pre-second generation.
        assert second.generation > first_generation  # generation advanced


async def test_lifecycle_replacement_archives_prior_active_page(integration_database):
    """Selecting a different Page archives the prior active Page as INACTIVE
    (distinct read-only history scope). V1 enforces at most one active."""
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin3@vfic.test",
            password_hash="x",
            full_name="FB Admin 3",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-A", page_name="A", page_access_token="tA", admin_id=admin_id
        )
        await lifecycle.activate_or_reactivate(
            page_id="page-B", page_name="B", page_access_token="tB", admin_id=admin_id
        )

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        accounts = await resolver.list_facebook_accounts()
        active = [a for a in accounts if a.is_active]
        inactive = [a for a in accounts if not a.is_active]
        assert len(active) == 1
        assert active[0].account_key == "page-B"
        assert len(inactive) == 1
        assert inactive[0].account_key == "page-A"


async def test_lifecycle_disconnect_marks_inactive_keeps_history(integration_database):
    from app.channels.providers.facebook_account import (
        FacebookAccountResolver,
        FacebookPageLifecycle,
    )
    from app.core.db import async_session

    async with async_session() as db:
        admin = User(
            email="fb-admin4@vfic.test",
            password_hash="x",
            full_name="FB Admin 4",
            role="admin",
        )
        db.add(admin)
        await db.flush()
        admin_id = admin.id

        lifecycle = FacebookPageLifecycle(db)
        await lifecycle.activate_or_reactivate(
            page_id="page-D", page_name="D", page_access_token="tD", admin_id=admin_id
        )
        account = await lifecycle.disconnect(page_id="page-D", admin_id=admin_id)
        assert account is not None
        assert account.status == "INACTIVE"

    async with async_session() as db:
        resolver = FacebookAccountResolver(db)
        # resolve_active returns None (disconnected); resolve_any returns it.
        assert (
            await resolver.resolve_active(provider="facebook_messenger", account_key="page-D")
            is None
        )
        archived = await resolver.resolve_any(provider="facebook_messenger", account_key="page-D")
        assert archived is not None
        assert not archived.is_active


async def test_lifecycle_activate_audit_failure_does_not_commit_account_or_token(
    integration_database, monkeypatch
):
    from sqlalchemy import select

    import app.channels.providers.facebook_account as facebook_account_mod
    from app.core.db import async_session
    from app.models.channel_account import ChannelAccount
    from app.models.integration import IntegrationSetting

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(facebook_account_mod, "record_audit", fail_audit)

    async with async_session() as db:
        admin = User(
            email="fb-audit-fail@vfic.test",
            password_hash="x",
            full_name="FB Audit Fail",
            role="admin",
        )
        db.add(admin)
        await db.flush()

        lifecycle = facebook_account_mod.FacebookPageLifecycle(db)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await lifecycle.activate_or_reactivate(
                page_id="page-audit-fail",
                page_name="Broken Audit",
                page_access_token="EAAB-audit-fail-token",
                admin_id=admin.id,
            )
        await db.rollback()

    async with async_session() as db:
        account = await db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.provider == "facebook_messenger",
                ChannelAccount.account_key == "page-audit-fail",
            )
        )
        token = await db.scalar(
            select(IntegrationSetting).where(
                IntegrationSetting.key == "facebook_page_token:page-audit-fail"
            )
        )
        assert account is None
        assert token is None


async def test_page_token_round_trip_set_then_resolve_decrypts_correctly(
    integration_database,
):
    """The critical round-trip the Phase 4 review flagged was untested.

    Drives set_facebook_page_token → resolve_facebook against the real DB so a
    double-encryption bug (C2), a missing-method bug (C1), or a context-binding
    bypass (H1) cannot ship silently. The decrypted token must equal the input.
    """
    from app.core.db import async_session
    from app.services.integration_settings import IntegrationSettingsService
    from app.models.user import User

    async with async_session() as db:
        admin = User(
            email="fb-roundtrip@vfic.test",
            password_hash="x",
            full_name="Roundtrip",
            role="admin",
        )
        db.add(admin)
        await db.flush()

        service = IntegrationSettingsService(db)
        await service.set_facebook_page_token(
            "page-RT", "EAAB-secret-page-token-XYZ", updated_by=admin.id
        )

    async with async_session() as db:
        service = IntegrationSettingsService(db)
        cfg = await service.resolve_facebook("page-RT")
        assert cfg is not None, "resolve_facebook returned None — token decrypt failed"
        assert cfg.page_access_token == "EAAB-secret-page-token-XYZ"
        assert cfg.page_id == "page-RT"


async def test_page_token_wrong_context_does_not_decrypt(integration_database):
    """A token encrypted for page-A must NOT resolve under page-B (Red Team #7).

    This is the runtime enforcement of the context-binding: even if a row were
    copied between Pages, resolve_facebook(page-B) must return None.
    """
    from app.core.db import async_session
    from app.services.integration_settings import IntegrationSettingsService
    from app.models.user import User

    async with async_session() as db:
        admin = User(email="fb-ctx@vfic.test", password_hash="x", full_name="Ctx", role="admin")
        db.add(admin)
        await db.flush()
        service = IntegrationSettingsService(db)
        await service.set_facebook_page_token("page-A", "EAAB-token-A", updated_by=admin.id)
        # Copy the page-A ciphertext into a page-B key (simulating a row move).
        from app.models.integration import IntegrationSetting
        from sqlalchemy import select

        row = await db.scalar(
            select(IntegrationSetting).where(IntegrationSetting.key == "facebook_page_token:page-A")
        )
        assert row is not None
        db.add(
            IntegrationSetting(
                key="facebook_page_token:page-B",
                encrypted_value=row.encrypted_value,
                is_secret=True,
            )
        )
        await db.commit()

    async with async_session() as db:
        service = IntegrationSettingsService(db)
        # page-B should NOT decrypt — the ciphertext was bound to page-A.
        cfg = await service.resolve_facebook("page-B")
        assert cfg is None, "wrong-context token decrypted — context binding failed"


async def test_receipt_is_scoped_by_page_account_no_cross_contamination(
    integration_database,
):
    """C1 regression (Phase 5 review): a delivery receipt for page-A's mid must
    NOT advance a page-B outbound row that happens to share the same
    provider_message_id. The receipt query joins Conversation→
    ContactChannelIdentity and filters by provider + account_key.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.conversation_messaging.infrastructure.webhook_delivery import (
        apply_messenger_receipt,
    )
    from app.channels.types import ChannelReceipt
    from app.core.db import async_session
    from app.models.contact import Contact, ContactChannelIdentity
    from app.models.conversation import (
        Conversation,
        ConversationMode,
        DeliveryStatus,
        Message,
        MessageSender,
    )

    async with async_session() as db:
        # Two Pages, each with contact + identity + conversation + a SENT
        # outbound message sharing the SAME provider_message_id.
        for page in ("page-A", "page-B"):
            contact = Contact()
            db.add(contact)
            await db.flush()
            ident = ContactChannelIdentity(
                contact_id=contact.id,
                provider="facebook_messenger",
                account_key=page,
                external_id=f"PSID-{page}",
            )
            db.add(ident)
            await db.flush()
            conv = Conversation(
                zalo_channel="facebook_messenger",
                contact_id=contact.id,
                channel_identity_id=ident.id,
                mode=ConversationMode.BOT,
            )
            db.add(conv)
            await db.flush()
            db.add(
                Message(
                    conversation_id=conv.id,
                    sender=MessageSender.BOT,
                    body="reply",
                    delivery_status=DeliveryStatus.SENT,
                    provider_message_id="mid-colliding",  # SAME mid on both pages
                )
            )
        await db.commit()

    # Apply a DELIVERED receipt for page-A's mid. page-B's row must stay SENT.
    async with async_session() as db:
        receipt = ChannelReceipt(
            provider="facebook_messenger",
            account_key="page-A",
            provider_message_ids=("mid-colliding",),
            kind="delivered",
            occurred_at=datetime.now(timezone.utc),
        )
        await apply_messenger_receipt(db, receipt, account_key="page-A")

    async with async_session() as db:
        rows = (
            await db.scalars(select(Message).where(Message.provider_message_id == "mid-colliding"))
        ).all()
        # Exactly one row advanced to DELIVERED (page-A); the other stays SENT.
        delivered = [r for r in rows if r.delivery_status == DeliveryStatus.DELIVERED]
        sent = [r for r in rows if r.delivery_status == DeliveryStatus.SENT]
        assert len(delivered) == 1, (
            f"expected 1 delivered, got {[(r.delivery_status) for r in rows]}"
        )
        assert len(sent) == 1, f"expected 1 still-sent, got {[(r.delivery_status) for r in rows]}"
