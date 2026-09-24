"""Behavioral proof for the reconcile sweep predicate (real PostgreSQL).

The sweep is the durable net behind the worker's newest-inbound hand-off. Its
predicate must recover a conversation whose newest candidate message never got a
turn — including the production shape where the turn that held the per-chat
mutex answered an OLDER inbound and wrote its own outcome row *after* the
dropped message, hiding the conversation from the sweep forever.

The only durable link between a BOT outcome row and the inbound it answered is
the ``quote_message_id`` of the outbound command written with that outcome
(``graph/runner._build_outbox_payload`` from ``BotRunState.reply_to_message_id``).
These tests seed real ``messages`` + ``outbound_outbox`` rows and assert what
``ConversationRepository.find_reconcile_candidates`` selects, so the loop-safety
invariants (a deliberate SUPPRESSED silence is never re-answered, grace, mode,
lock, max-age) are proven against the SQL rather than against its text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation_messaging.domain.statuses import ConversationMode
from app.models.conversation import (
    BotRun,
    Conversation,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.outbox import OutboxStatus, OutboundOutbox
from app.services.conversation.repository import ConversationRepository
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration

GRACE_SECONDS = 120
MAX_AGE_SECONDS = 86400


def _at(now: datetime, *, seconds_ago: float) -> datetime:
    return now - timedelta(seconds=seconds_ago)


def _inbound(conv: Conversation, *, body: str, provider_id: str, created_at: datetime) -> Message:
    return Message(
        conversation_id=conv.id,
        sender=MessageSender.WORKER,
        body=body,
        delivery_status=DeliveryStatus.SENT,
        zalo_message_id=provider_id,
        provider_message_id=provider_id,
        created_at=created_at,
    )


def _bot_outcome(
    conv: Conversation,
    *,
    body: str,
    status: DeliveryStatus,
    created_at: datetime,
    bot_run_id: int | None = None,
    external_error: str | None = None,
) -> Message:
    return Message(
        conversation_id=conv.id,
        sender=MessageSender.BOT,
        body=body,
        delivery_status=status,
        created_at=created_at,
        bot_run_id=bot_run_id,
        external_error=external_error,
    )


def _recruiter(conv: Conversation, *, body: str, created_at: datetime) -> Message:
    return Message(
        conversation_id=conv.id,
        sender=MessageSender.RECRUITER,
        body=body,
        delivery_status=DeliveryStatus.SENT,
        created_at=created_at,
    )


async def _seed_turn(db: AsyncSession, conv: Conversation, *, started_at: datetime) -> BotRun:
    """The BotRun a turn records alongside its outcome row (audit trail only)."""
    run = BotRun(
        conversation_id=conv.id,
        version_at_start=1,
        proposed_reply="",
        outcome="SENT",
        started_at=started_at,
        ended_at=started_at,
    )
    db.add(run)
    await db.flush()
    return run


async def _seed_command(
    db: AsyncSession, msg: Message, *, quote: str | None, status: OutboxStatus
) -> OutboundOutbox:
    """The outbound command an outcome row was written with (the durable link)."""
    payload: dict[str, str] = {"chat_id": "chat-1", "text": msg.body}
    if quote:
        payload["quote_message_id"] = quote
    outbox = OutboundOutbox(
        message_id=msg.id,
        channel="zalo_bot",
        payload=payload,
        status=status.value,
    )
    db.add(outbox)
    await db.flush()
    return outbox


async def _candidates(db: AsyncSession, *, now: datetime) -> list[Conversation]:
    return await ConversationRepository(db).find_reconcile_candidates(
        now=now,
        grace_seconds=GRACE_SECONDS,
        max_age_seconds=MAX_AGE_SECONDS,
        limit=50,
    )


async def _proven(db: AsyncSession, conv: Conversation, *, now: datetime) -> bool:
    """The reconcile tick's re-verification of the same proof, for one conversation.

    The sweep selects candidates in bulk SQL; the tick re-runs the per-conversation
    form against freshly read state before it enqueues. The two must agree, or a
    selected candidate would be released without being recovered.
    """
    return await ConversationRepository(db).latest_inbound_never_given_a_turn(
        conv,
        now=now,
        grace_seconds=GRACE_SECONDS,
        max_age_seconds=MAX_AGE_SECONDS,
    )


async def _conversation(db: AsyncSession, *, mode: ConversationMode = ConversationMode.BOT, **kw):
    return await make_zalo_conversation(
        db, zalo_chat_id=f"reconcile-{uuid.uuid4().hex[:10]}", mode=mode, **kw
    )


# --- the production shape: an outcome row written after the dropped inbound ---


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.SENT, DeliveryStatus.SUPPRESSED, DeliveryStatus.SEND_UNKNOWN],
)
async def test_outcome_that_answered_an_older_inbound_recovers_the_dropped_one(
    integration_session: AsyncSession, status: DeliveryStatus
) -> None:
    """WORKER 'in-a' → WORKER 'in-w' (dropped) → BOT outcome quoting 'in-a'.

    The outcome row is the newest message, so the pre-existing predicate skips
    the conversation and the dropped inbound waits for the candidate's next
    message. The command's quote proves the outcome answered an older inbound,
    so the newest candidate message never got a turn and must be recovered.
    """
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=status,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(
        integration_session, outcome, quote="in-a", status=OutboxStatus.SENT
    )

    found = await _candidates(integration_session, now=now)

    assert [c.id for c in found] == [conv.id]
    # The tick re-verifies before it enqueues; both SQL forms must agree.
    assert await _proven(integration_session, conv, now=now) is True


async def test_outcome_that_answered_the_newest_inbound_is_never_re_answered(
    integration_session: AsyncSession,
) -> None:
    """A turn that answered the newest inbound with silence stays silent.

    Recovering this conversation would re-answer a message the bot deliberately
    left unanswered — the candidate-spam failure the predicate must not cause.
    """
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="...", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    outcome = _bot_outcome(
        conv,
        body="",
        status=DeliveryStatus.SUPPRESSED,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(
        integration_session, outcome, quote="in-w", status=OutboxStatus.SUPPRESSED
    )

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


async def test_outcome_without_a_durable_command_is_left_to_the_handoff(
    integration_session: AsyncSession,
) -> None:
    """No command ⇒ no proof of which inbound was answered ⇒ stay conservative.

    A pre-send suppression (lost claim, silent terminal, LLM throttle) records
    its outcome without an outbound command, so the sweep cannot tell it from a
    dropped inbound. It must not guess: re-answering a suppressed turn is worse
    than leaving the message to the worker's newest-inbound hand-off.
    """
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    integration_session.add(
        _bot_outcome(
            conv,
            body="Dạ em chào anh",
            status=DeliveryStatus.SUPPRESSED,
            created_at=_at(now, seconds_ago=290),
            bot_run_id=run.id,
        )
    )
    await integration_session.flush()

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


async def test_answered_conversation_is_not_a_candidate(
    integration_session: AsyncSession,
) -> None:
    """The ordinary shape: the outcome quotes the newest candidate message."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    inbound = _inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600))
    integration_session.add(inbound)
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=595))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=590),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


# --- the existing loop-safety invariants, proven behaviorally ---


async def test_never_processed_inbound_is_still_recovered(
    integration_session: AsyncSession,
) -> None:
    """A WORKER-newest conversation keeps its fast lost-turn recovery."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(
        _inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=300))
    )
    await integration_session.flush()

    assert [c.id for c in await _candidates(integration_session, now=now)] == [conv.id]


async def test_stale_pending_placeholder_is_still_recovered(
    integration_session: AsyncSession,
) -> None:
    """A turn that started and never completed keeps its fast recovery path."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(
        _inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=300))
    )
    integration_session.add(
        _bot_outcome(
            conv,
            body="Đang soạn trả lời...",
            status=DeliveryStatus.PENDING,
            created_at=_at(now, seconds_ago=290),
        )
    )
    await integration_session.flush()

    assert [c.id for c in await _candidates(integration_session, now=now)] == [conv.id]


async def test_permanently_rejected_oa_recipient_is_not_retried(
    integration_session: AsyncSession,
) -> None:
    """Zalo's permanent OA recipient rejection must not enter the sweep."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session, zalo_channel="oa")
    integration_session.add(
        _inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=300))
    )
    integration_session.add(
        _bot_outcome(
            conv,
            body="",
            status=DeliveryStatus.FAILED,
            created_at=_at(now, seconds_ago=290),
            external_error="user_id is invalid",
        )
    )
    await integration_session.flush()

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


# --- guards: grace, max-age, human ownership, lock ---


async def test_in_grace_newest_inbound_is_not_recovered(
    integration_session: AsyncSession,
) -> None:
    """A dropped message younger than the grace window may still be handled."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=30)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=25))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=20),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


async def test_newest_inbound_past_the_max_age_cap_is_not_recovered(
    integration_session: AsyncSession,
) -> None:
    """Past the 24h cap the sweep stops touching the conversation."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=30 * 3600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=25 * 3600)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=25 * 3600))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=25 * 3600 - 5),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


async def test_recruiter_reply_newer_than_the_dropped_inbound_wins(
    integration_session: AsyncSession,
) -> None:
    """A human answered the newest candidate message: the bot must stay out."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    integration_session.add(
        _recruiter(conv, body="Dạ chị gọi lại sau nhé", created_at=_at(now, seconds_ago=295))
    )
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=294))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    assert await _candidates(integration_session, now=now) == []
    assert await _proven(integration_session, conv, now=now) is False


async def test_human_owned_conversation_is_not_swept(
    integration_session: AsyncSession,
) -> None:
    """HUMAN mode is out of the sweep's scope entirely."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session, mode=ConversationMode.HUMAN)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    assert await _candidates(integration_session, now=now) == []
    # The inbound proof itself holds — HUMAN mode is what keeps the bot out, and
    # the tick never consults the proof for a conversation the sweep skipped.
    assert await _proven(integration_session, conv, now=now) is True


async def test_live_lock_excludes_the_conversation(
    integration_session: AsyncSession,
) -> None:
    """A turn still holding the mutex owns the conversation; the sweep waits."""
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    conv.bot_locked_until = now + timedelta(seconds=60)
    conv.bot_lock_owner = uuid.uuid4()
    conv.bot_lock_heartbeat_at = now
    await integration_session.flush()

    assert await _candidates(integration_session, now=now) == []
    # Same layering: the proof holds, the live per-chat mutex is what excludes it.
    assert await _proven(integration_session, conv, now=now) is True


# --- why the sweep needs this branch: the hand-off cannot see this shape ---


async def test_handoff_cannot_recover_the_masked_shape(
    integration_session: AsyncSession,
) -> None:
    """The fast path refuses to hand over a conversation this branch recovers.

    ``chatbot_worker._handoff_to_newer_inbound`` enqueues through
    ``latest_unanswered_worker_message``, which treats ANY newer delivered
    BOT/RECRUITER row as an answer. In the masked shape that row answered an
    older inbound, so the hand-off finds nothing to hand over and the dropped
    message waits for the candidate's next message — unless the sweep recovers it.
    """
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    outcome = _bot_outcome(
        conv,
        body="Dạ em chào anh",
        status=DeliveryStatus.SENT,
        created_at=_at(now, seconds_ago=290),
        bot_run_id=run.id,
    )
    integration_session.add(outcome)
    await integration_session.flush()
    await _seed_command(integration_session, outcome, quote="in-a", status=OutboxStatus.SENT)

    repo = ConversationRepository(integration_session)

    assert await repo.latest_unanswered_worker_message(conv) is None
    assert await _proven(integration_session, conv, now=now) is True


async def test_handoff_still_covers_a_pre_send_suppression(
    integration_session: AsyncSession,
) -> None:
    """The shapes the sweep conservatively skips keep their fast path.

    A pre-send suppression records no outbound command, so it is indistinguishable
    from a dropped inbound and the sweep must not guess. It is not left uncovered:
    a SUPPRESSED row is not a delivered answer, so the hand-off still hands the
    newest candidate message over.
    """
    now = datetime.now(timezone.utc)
    conv = await _conversation(integration_session)
    integration_session.add(_inbound(conv, body="Chào em", provider_id="in-a", created_at=_at(now, seconds_ago=600)))
    integration_session.add(_inbound(conv, body="Còn vị trí nào không?", provider_id="in-w", created_at=_at(now, seconds_ago=300)))
    await integration_session.flush()

    run = await _seed_turn(integration_session, conv, started_at=_at(now, seconds_ago=295))
    integration_session.add(
        _bot_outcome(
            conv,
            body="Dạ em chào anh",
            status=DeliveryStatus.SUPPRESSED,
            created_at=_at(now, seconds_ago=290),
            bot_run_id=run.id,
        )
    )
    await integration_session.flush()

    repo = ConversationRepository(integration_session)

    unanswered = await repo.latest_unanswered_worker_message(conv)
    assert unanswered is not None
    assert unanswered.provider_message_id == "in-w"
    assert await _proven(integration_session, conv, now=now) is False
