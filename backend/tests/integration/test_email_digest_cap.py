"""The digest cap must never drop a phone-having lead.

Regression: the per-digest cap sliced the window's OLDEST leads, so a busy
stretch of phoneless Messenger stubs (the conversation trigger creates one
lead per conversation) could push every reachable candidate past
``MAX_CANDIDATES_PER_DIGEST`` and the Excel went out without them. The cap now
orders phone-having leads first; this test builds exactly that flooding shape
on a real database.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.lead import Lead
from app.services.email_digest.repository import (
    MAX_CANDIDATES_PER_DIGEST,
    collect_new_candidates,
)
from tests.integration._conv_factory import make_conversation

WINDOW_START = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


async def _stub_lead(db, *, key: str, offset_minutes: int) -> Lead:
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
    lead.created_at = WINDOW_START + timedelta(minutes=offset_minutes)
    return lead


async def test_cap_keeps_phone_having_leads_over_phoneless_flood(integration_session):
    db = integration_session

    early = await _stub_lead(db, key="early", offset_minutes=1)
    early.name = "Early Phone"
    early.phone = "0900000001"
    for index in range(MAX_CANDIDATES_PER_DIGEST):
        await _stub_lead(db, key=f"stub-{index}", offset_minutes=2 + index)
    late_phones = []
    for index in range(4):
        late = await _stub_lead(
            db,
            key=f"late-{index}",
            offset_minutes=2 + MAX_CANDIDATES_PER_DIGEST + index,
        )
        late.name = f"Late Phone {index}"
        late.phone = f"090100000{index}"
        late_phones.append(late)
    await db.commit()

    # Same session, so the collection sees this test's uncommitted transaction.
    candidates = await collect_new_candidates(
        db,
        window_start=WINDOW_START,
        window_end=WINDOW_START + timedelta(days=1),
    )

    phones = {candidate.phone for candidate in candidates}
    assert len(candidates) <= MAX_CANDIDATES_PER_DIGEST
    assert "0900000001" in phones
    assert phones.issuperset({f"090100000{index}" for index in range(4)})
    # Presentation stays chronological within the capped slice.
    lead_ids = [candidate.lead_id for candidate in candidates]
    created = (
        await db.execute(select(Lead.created_at).where(Lead.id.in_(lead_ids)))
    ).all()
    created_by_id = dict(zip(lead_ids, (row[0] for row in created), strict=True))
    ordered = [created_by_id[lead_id] for lead_id in lead_ids]
    assert ordered == sorted(ordered)
