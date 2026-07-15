"""PostgreSQL proof that concurrent extraction handoffs create one review event."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.audit import AuditEvent
from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    Message,
    MessageSender,
)
from app.models.user import Role, User
from app.services.conversation.state import ConversationState
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


class _NoopEvents:
    async def message_created(self, _message, _conversation) -> None:
        return None

    async def conversation_updated(self, _conversation) -> None:
        return None


async def test_concurrent_extraction_handoffs_create_one_review_event(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    taken_over_at = datetime.now(timezone.utc)
    try:
        async with sessions() as setup:
            recruiter = User(
                email="intent-concurrency@vfic.test",
                password_hash="not-a-real-password-hash",
                full_name="Concurrency reviewer",
                role=Role.recruiter,
            )
            setup.add(recruiter)
            await setup.flush()
            conversation = Conversation(
                zalo_chat_id="intent-concurrency-chat",
                mode=ConversationMode.BOT,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=taken_over_at,
            )
            setup.add(conversation)
            await setup.commit()
            conversation_id = conversation.id
            recruiter_id = recruiter.id

        async def escalate() -> bool:
            async with sessions() as session:
                conversation = await session.get(Conversation, conversation_id)
                assert conversation is not None
                return await ConversationState(
                    session,
                    repo=None,
                    events=_NoopEvents(),
                ).escalate_extracted_intent(
                    conversation,
                    reason="bot_testing",
                    confidence=0.99,
                    expected_version=1,
                )

        outcomes = await asyncio.gather(escalate(), escalate())
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
            assert conversation.unread_count == 0
            assert conversation.version == 2
            assert conversation.conversation_seq == 2

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
                    AuditEvent.action == "extraction_intent_human_review",
                    AuditEvent.target_id == str(conversation_id),
                )
            )
            assert worker_count == 0
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


async def test_stale_extraction_cannot_reopen_newer_closed_state(
    integration_database: IntegrationDatabase,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as setup:
            conversation = Conversation(
                zalo_chat_id="stale-intent-closed-chat",
                mode=ConversationMode.BOT,
            )
            setup.add(conversation)
            await setup.commit()
            conversation_id = conversation.id

        async with sessions() as stale_session:
            stale_conversation = await stale_session.get(Conversation, conversation_id)
            assert stale_conversation is not None
            assert stale_conversation.version == 1

            async with sessions() as operator_session:
                current = await operator_session.get(Conversation, conversation_id)
                assert current is not None
                current.status = ConversationStatus.CLOSED
                current.mode = ConversationMode.HUMAN
                current.version += 1
                current.conversation_seq += 1
                await operator_session.commit()

            transitioned = await ConversationState(
                stale_session,
                repo=None,
                events=_NoopEvents(),
            ).escalate_extracted_intent(
                stale_conversation,
                reason="bot_testing",
                confidence=0.99,
                expected_version=1,
            )
            assert transitioned is False

        async with sessions() as verify:
            conversation = await verify.get(Conversation, conversation_id)
            assert conversation is not None
            assert conversation.status == ConversationStatus.CLOSED
            assert conversation.mode == ConversationMode.HUMAN
            assert conversation.version == 2
            system_count = await verify.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id,
                    Message.sender == MessageSender.SYSTEM,
                )
            )
            audit_count = await verify.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "extraction_intent_human_review",
                    AuditEvent.target_id == str(conversation_id),
                )
            )
            assert system_count == 0
            assert audit_count == 0
            await verify.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await verify.commit()
    finally:
        await engine.dispose()
