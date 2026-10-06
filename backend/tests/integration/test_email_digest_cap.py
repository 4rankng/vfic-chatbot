"""The digest cap must never drop a reachable candidate.

Two bounds guard the same risk (an Excel that silently loses people):

* phoneless rows are filtered in the query itself — the conversation trigger
  creates one lead per conversation, so a flood of Messenger stubs must not
  even enter the candidate set, let alone consume the cap;
* ``MAX_CANDIDATES_PER_DIGEST`` still bounds the window, and when it binds it
  keeps the earliest candidates by latest-message time (the selection key).

Both shapes are built on a real database here.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.conversation import Conversation, Message, MessageSender
from app.models.lead import Lead
from app.services.email_digest.repository import (
    MAX_CANDIDATES_PER_DIGEST,
    collect_new_candidates,
)
from tests.integration._conv_factory import make_conversation

WINDOW_START = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(days=1)


async def _stub_lead(
    db, *, key: str, offset_minutes: int, phone: str | None = None
) -> Lead:
    conversation = await make_conversation(
        db,
        provider="facebook_messenger",
        account_key=f"cap-{key}",
        external_id=f"cap-{key}",
    )
    lead = (
        await db.scalars(
            select(Lead).where(Lead.contact_id == conversation.contact_id)
        )
    ).one()
    at = WINDOW_START + timedelta(minutes=offset_minutes)
    lead.created_at = at
    if phone is not None:
        lead.phone = phone
    # Selection keys on the candidate's latest message, not on lead creation:
    # every stub therefore needs a message inside the window to be a candidate.
    db.add(
        Message(
            conversation_id=conversation.id,
            sender=MessageSender.WORKER,
            body=f"ứng viên {key}",
            created_at=at,
        )
    )
    return lead


async def test_phoneless_flood_never_reaches_the_candidates(integration_session):
    """A flood of phoneless stubs is excluded in SQL, not after the cap."""
    db = integration_session

    early = await _stub_lead(db, key="early", offset_minutes=1, phone="0900000001")
    early.name = "Early Phone"
    for index in range(MAX_CANDIDATES_PER_DIGEST):
        await _stub_lead(db, key=f"stub-{index}", offset_minutes=2 + index)
    late_phones = []
    for index in range(4):
        late = await _stub_lead(
            db,
            key=f"late-{index}",
            offset_minutes=2 + MAX_CANDIDATES_PER_DIGEST + index,
            phone=f"090100000{index}",
        )
        late.name = f"Late Phone {index}"
        late_phones.append(late)
    await db.commit()

    # Same session, so the collection sees this test's uncommitted transaction.
    candidates = await collect_new_candidates(
        db, window_start=WINDOW_START, window_end=WINDOW_END
    )

    phones = {candidate.phone for candidate in candidates}
    assert len(candidates) <= MAX_CANDIDATES_PER_DIGEST
    assert "0900000001" in phones
    # Phoneless stubs are gone; the four reachable leads behind them survive.
    assert phones.issuperset({f"090100000{index}" for index in range(4)})
    assert phones == {"0900000001"} | {f"090100000{index}" for index in range(4)}
    # Presentation follows the selection key: latest candidate message asc.
    await _assert_ordered_by_latest_message(db, candidates)


async def test_cap_bounds_the_window_by_latest_message(integration_session):
    """When the window exceeds the cap, the earliest candidates stay in."""
    db = integration_session

    count = MAX_CANDIDATES_PER_DIGEST + 5
    for index in range(count):
        lead = await _stub_lead(
            db,
            key=f"many-{index}",
            offset_minutes=index,
            phone=f"09020000{index:04d}",
        )
        lead.name = f"Candidate {index:02d}"
    await db.commit()

    candidates = await collect_new_candidates(
        db, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert len(candidates) == MAX_CANDIDATES_PER_DIGEST
    # The earliest `count - 5` by latest message are the ones kept.
    kept = [candidate.phone for candidate in candidates]
    assert kept[0] == "090200000000"
    assert f"09020000{count - 1:04d}" not in kept
    await _assert_ordered_by_latest_message(db, candidates)


async def _assert_ordered_by_latest_message(db, candidates) -> None:
    """The sheet rows follow each candidate's latest message, oldest first."""
    lead_ids = [candidate.lead_id for candidate in candidates]
    rows = (
        await db.execute(
            select(Lead.id, func.max(Message.created_at))
            .join(Conversation, Conversation.contact_id == Lead.contact_id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Lead.id.in_(lead_ids))
            .where(Message.sender == MessageSender.WORKER)
            .group_by(Lead.id)
        )
    ).all()
    latest_by_lead = dict(rows)
    ordered = [latest_by_lead[lead_id] for lead_id in lead_ids]
    assert all(value is not None for value in ordered)
    assert ordered == sorted(ordered)
