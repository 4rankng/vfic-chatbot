"""Digest selection: latest candidate message in the window + a phone number.

Operator rule (2026-10-06): "new candidate" = someone who CHATTED with the
bot inside the window and can be called back. The collector used to key on
``Lead.created_at`` instead, which is created by the conversation trigger for
every conversation whether or not anyone typed — the digest then missed
candidates who had talked earlier and counted silent lead stubs. Each case
below pins one half of that rule against a real database.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.conversation import Message, MessageSender
from app.models.lead import Lead
from app.services.email_digest.repository import collect_new_candidates
from tests.integration._conv_factory import make_conversation

WINDOW_START = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(days=1)


async def _candidate(
    db,
    *,
    name: str,
    phone: str | None = None,
    lead_created: datetime | None = None,
    messages: tuple[datetime, ...] = (),
    provider: str = "facebook_messenger",
    account_key: str | None = None,
) -> Lead:
    conversation = await make_conversation(
        db,
        provider=provider,
        account_key=account_key or f"sel-{name}",
        external_id=f"sel-{name}",
    )
    lead = (
        await db.scalars(
            select(Lead).where(Lead.contact_id == conversation.contact_id)
        )
    ).one()
    lead.name = name
    if phone is not None:
        lead.phone = phone
    if lead_created is not None:
        lead.created_at = lead_created
    for sent_at in messages:
        db.add(
            Message(
                conversation_id=conversation.id,
                sender=MessageSender.WORKER,
                body=f"allo {name}",
                created_at=sent_at,
            )
        )
    return lead


async def test_selection_is_latest_message_in_window_with_phone(integration_session):
    db = integration_session

    # Talked before the window and again inside it → in, even though the lead
    # is old (the old created_at rule dropped exactly this candidate).
    await _candidate(
        db,
        name="returning",
        phone="0900000001",
        lead_created=datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc),
        messages=(
            datetime(2026, 9, 20, 8, 5, tzinfo=timezone.utc),
            datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
        ),
    )
    # Fresh lead, talked inside the window, has a phone → in.
    await _candidate(
        db,
        name="fresh",
        phone="0900000002",
        lead_created=WINDOW_START + timedelta(hours=1),
        messages=(WINDOW_START + timedelta(hours=2),),
    )
    # Lead stubbed inside the window but never typed after the earlier touch
    # → out: lead creation is not activity (the old rule counted this one).
    await _candidate(
        db,
        name="silent",
        phone="0900000003",
        lead_created=WINDOW_START + timedelta(hours=5),
        messages=(datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc),),
    )
    # Talked inside the window but has no number → out (not actionable).
    await _candidate(
        db,
        name="nophone",
        lead_created=WINDOW_START + timedelta(hours=1),
        messages=(WINDOW_START + timedelta(hours=3),),
    )
    # Talked inside the window AND again after it → out: the newest message
    # decides, so a later conversation belongs to a later window.
    await _candidate(
        db,
        name="later",
        phone="0900000004",
        lead_created=WINDOW_START,
        messages=(
            WINDOW_START + timedelta(hours=8),
            WINDOW_END + timedelta(hours=1),
        ),
    )
    # Employee-support OA contact → out, never a recruitment candidate.
    await _candidate(
        db,
        name="support",
        phone="0900000005",
        lead_created=WINDOW_START,
        messages=(WINDOW_START + timedelta(hours=4),),
        provider="zalo_oa",
        account_key="tingting",
    )
    await db.commit()

    candidates = await collect_new_candidates(
        db, window_start=WINDOW_START, window_end=WINDOW_END
    )

    assert {candidate.name for candidate in candidates} == {"returning", "fresh"}
    assert {candidate.phone for candidate in candidates} == {"0900000001", "0900000002"}
