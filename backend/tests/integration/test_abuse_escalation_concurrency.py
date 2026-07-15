"""PostgreSQL proof that concurrent abuse escalation creates one review event."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.audit import AuditEvent
from app.models.conversation import Conversation, ConversationMode, Message, MessageSender
from app.models.user import Role, User
from app.services.conversation.state import ConversationState
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        return None

    async def conversation_updated(self, _conversation) -> None:
        return None


async def test_concurrent_positive_messages_create_one_escalation(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    taken_over_at = datetime.now(timezone.utc)
    try:
        async with sessions() as setup:
            recruiter = User(
                email="abuse-concurrency@vfic.test",
                password_hash="not-a-real-password-hash",
                full_name="Concurrency reviewer",
                role=Role.recruiter,
            )
            setup.add(recruiter)
            await setup.flush()
            conversation = Conversation(
                zalo_chat_id="abuse-concurrency-chat",
                mode=ConversationMode.BOT,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=taken_over_at,
            )
            setup.add(conversation)
            await setup.commit()
            conversation_id = conversation.id
            recruiter_id = recruiter.id

        async def escalate(message_id: str) -> bool:
            async with sessions() as session:
                conversation = await session.get(Conversation, conversation_id)
                assert conversation is not None
                return await ConversationState(
                    session,
                    repo=None,
                    events=_NoopEvents(),
                ).record_inbound_and_escalate_abuse(
                    conversation,
                    body="Tôi đang kiểm tra bot",
                    zalo_message_id=message_id,
                    reason="explicit_bot_testing",
                )

        outcomes = await asyncio.gather(escalate("abuse-1"), escalate("abuse-2"))
        assert sorted(outcomes) == [False, True]

        async with sessions() as verify:
            conversation = await verify.get(Conversation, conversation_id)
            assert conversation is not None
            assert conversation.mode == ConversationMode.HUMAN
            assert conversation.needs_human is True
            assert conversation.assigned_recruiter_id == recruiter_id
            assert conversation.taken_over_at == taken_over_at
            assert conversation.bot_locked_until is None
            assert conversation.bot_lock_owner is None
            assert conversation.bot_lock_heartbeat_at is None
            assert conversation.unread_count == 2
            assert conversation.version == 4
            assert conversation.conversation_seq == 4

            worker_count = await verify.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id,
                    Message.sender == MessageSender.WORKER,
                )
            )
            system_count = await verify.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id,
                    Message.sender == MessageSender.SYSTEM,
                )
            )
            audit_count = await verify.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "auto_escalate_suspected_abuse",
                    AuditEvent.target_id == str(conversation_id),
                )
            )
            assert worker_count == 2
            assert system_count == 1
            assert audit_count == 1

            await verify.execute(
                delete(AuditEvent).where(AuditEvent.target_id == str(conversation_id))
            )
            await verify.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await verify.execute(delete(User).where(User.id == recruiter_id))
            await verify.commit()
    finally:
        await engine.dispose()
