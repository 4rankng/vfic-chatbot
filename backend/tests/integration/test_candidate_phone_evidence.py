"""Real multi-turn phone authority and audit evidence across CRM consumers."""

from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock
from sqlalchemy import func, select, update

from app.models.conversation import Message, MessageSender
from app.models.lead import Lead, LeadEvent
from app.recruitment.infrastructure.service_adapters import ServiceLeadContextAdapter
from app.services.lead.repository import LeadRepository
from app.services.lead.normalizers import normalize_lead
from app.services.lead.tags import system_tag_keys
from app.schemas.lead import LeadOut
from tests.integration._conv_factory import make_conversation, make_zalo_conversation

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _local_realtime(monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr("app.services.lead.events.LeadEventBus.lead_updated", publish)
    return publish


async def _candidate(db, chat_id, provider="zalo_bot"):
    if provider == "facebook_messenger":
        conversation = await make_conversation(
            db, provider=provider, account_key="phone-page", external_id=chat_id,
            zalo_chat_id=None, zalo_channel=provider,
        )
    else:
        conversation = await make_zalo_conversation(db, zalo_chat_id=chat_id)
    await db.execute(
        update(Lead).where(Lead.contact_id == conversation.contact_id).values(phone="0987654321")
    )
    await db.commit()
    return conversation


async def _inbound(db, conversation, text, offset):
    message = Message(
        conversation_id=conversation.id, sender=MessageSender.WORKER, body=text,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=offset),
    )
    db.add(message)
    await db.commit()
    return message


@pytest.mark.parametrize("replacement", ["0987654321", "0912345678"])
@pytest.mark.parametrize("provider", ["zalo_bot", "facebook_messenger"])
async def test_disavowed_phone_stays_missing_until_candidate_corrects_it(
    integration_session, replacement, provider,
):
    db = integration_session
    chat_id = f"disavowed-{replacement}-{provider}"
    conversation = await _candidate(db, chat_id, provider)
    adapter = ServiceLeadContextAdapter(db)
    contact_id = str(conversation.contact_id)
    original = await LeadRepository(db).by_contact_id(contact_id)

    denied = await _inbound(db, conversation, "0987654321 không phải số của em", 1)
    profile, question = await adapter.context(chat_id, denied.body, [denied], contact_id=contact_id)
    assert question
    assert "0987654321" not in profile
    saved = await LeadRepository(db).by_contact_id(contact_id)
    assert saved["phone"] is None
    assert saved["version"] == original["version"] + 1
    canonical = await db.get(Lead, saved["id"])
    assert LeadOut.model_validate(canonical).phone is None
    assert "missing_phone" in system_tag_keys(canonical, None)
    assert "has_phone" not in system_tag_keys(canonical, None)
    event = await LeadRepository(db).candidate_phone_evidence(saved["id"])
    assert event.payload["phone"] == "0987654321"
    assert event.payload["disavowed"] is True

    # A fresh adapter and unrelated turn must not forget the durable denial,
    # even when the message history provided for this turn omits that message.
    unrelated = await _inbound(db, conversation, "Dự án có xe đưa đón không?", 2)
    profile, question = await ServiceLeadContextAdapter(db).context(
        chat_id, unrelated.body, [unrelated], contact_id=contact_id,
    )
    assert question
    assert "0987654321" not in profile
    assert (await LeadRepository(db).by_contact_id(contact_id))["phone"] is None

    confirmed = await _inbound(db, conversation, f"Số của em là {replacement}", 3)
    _, question = await adapter.context(
        chat_id, confirmed.body, [confirmed], contact_id=contact_id,
    )
    assert question == ""
    saved = await LeadRepository(db).by_contact_id(contact_id)
    assert saved["phone"] == replacement
    assert saved["version"] == original["version"] + 2

    profile, question = await ServiceLeadContextAdapter(db).context(
        chat_id, "Lương thế nào?", [], contact_id=contact_id,
    )
    assert question == ""
    assert replacement in profile

    # Repeating the denial after a reconfirmation is a new transition; an
    # append-only free-text note with duplicate suppression cannot model this.
    denied_again = await _inbound(db, conversation, f"Em không dùng số {replacement} nữa", 4)
    await adapter.context(chat_id, denied_again.body, [denied_again], contact_id=contact_id)
    profile, question = await ServiceLeadContextAdapter(db).context(
        chat_id, "Có tăng ca không?", [], contact_id=contact_id,
    )
    assert question
    assert replacement not in profile
    assert (await LeadRepository(db).by_contact_id(contact_id))["phone"] is None


@pytest.mark.parametrize("text", [
    "Mẹ em không dùng số 0987654321 nữa",
    "Hotline 0987654321 không phải số công ty",
    "Số của mẹ em không phải 0987654321",
])
async def test_third_party_denial_does_not_disavow_candidate_phone(integration_session, text):
    db = integration_session
    chat_id = f"third-party-{text[:10]}"
    conversation = await _candidate(db, chat_id)
    message = await _inbound(db, conversation, text, 1)

    profile, question = await ServiceLeadContextAdapter(db).context(chat_id, text, [message])

    assert question == ""
    assert "0987654321" in profile
    assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0


@pytest.mark.parametrize("provider", ["zalo_bot", "facebook_messenger"])
async def test_same_message_phone_correction_updates_canonical_contact_and_fences_old_merge(
    integration_session, provider,
):
    db = integration_session
    chat_id = f"same-message-correction-{provider}"
    conversation = await _candidate(db, chat_id, provider)
    repo = LeadRepository(db)
    original = await repo.by_contact_id(str(conversation.contact_id))
    correction = await _inbound(
        db, conversation,
        "0987654321 không phải số của em. SĐT của em là 0912345678.", 1,
    )

    profile, question = await ServiceLeadContextAdapter(db).context(
        chat_id, correction.body, [correction], contact_id=str(conversation.contact_id),
    )

    assert question == ""
    assert "0912345678" in profile
    assert "0987654321" not in profile
    saved = await repo.by_contact_id(str(conversation.contact_id))
    assert saved["phone"] == "0912345678"
    assert saved["version"] == original["version"] + 1
    event = await repo.candidate_phone_evidence(saved["id"])
    assert event.payload["phone"] == "0912345678"
    assert event.payload["disavowed"] is False
    assert event.payload["message_id"] == correction.id

    await repo.upsert_by_contact(
        str(conversation.contact_id), normalize_lead({"phone": "0987654321"}, chat_id),
    )
    await db.commit()
    assert (await repo.by_contact_id(str(conversation.contact_id)))["phone"] == "0912345678"


async def test_phone_evidence_retry_and_late_old_turn_do_not_reverse_reconfirmation(
    integration_session,
):
    db = integration_session
    chat_id = "phone-evidence-order"
    conversation = await _candidate(db, chat_id)
    adapter = ServiceLeadContextAdapter(db)
    denied = await _inbound(db, conversation, "Em không dùng số 0987654321 nữa", 1)
    await adapter.context(chat_id, denied.body, [denied])
    await adapter.context(chat_id, denied.body, [denied])
    assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1

    confirmed = await _inbound(db, conversation, "Số của em là 0987654321", 2)
    await adapter.context(chat_id, confirmed.body, [confirmed])
    # The older turn reaches this seam again after the newer evidence committed.
    await adapter.context(chat_id, denied.body, [denied])

    profile, question = await ServiceLeadContextAdapter(db).context(chat_id, "Cần hồ sơ gì?", [])
    assert question == ""
    assert "0987654321" in profile
    assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 2


@pytest.mark.parametrize("write_key", ["zalo", "contact"])
async def test_deferred_phone_merge_cannot_restore_denial_or_reverse_correction(
    integration_session, write_key,
):
    db = integration_session
    chat_id = f"deferred-phone-{write_key}"
    conversation = await _candidate(db, chat_id)
    adapter = ServiceLeadContextAdapter(db)
    repo = LeadRepository(db)

    async def deferred_patch(phone):
        patch = normalize_lead({"phone": phone, "notes": "Có xe máy"}, chat_id)
        if write_key == "zalo":
            await repo.upsert(patch)
        else:
            await repo.upsert_by_contact(str(conversation.contact_id), patch)
        await db.commit()

    denied = await _inbound(db, conversation, "Em không dùng số 0987654321 nữa", 1)
    await adapter.context(chat_id, denied.body, [denied])
    await deferred_patch("0987654321")
    saved = await repo.by_zalo_id(chat_id)
    assert saved["phone"] is None
    assert saved["notes"] == "Có xe máy"  # Other explicit facts still merge normally.

    confirmed = await _inbound(db, conversation, "Số của em là 0912345678", 2)
    await adapter.context(chat_id, confirmed.body, [confirmed])
    await deferred_patch("0987654321")
    assert (await repo.by_zalo_id(chat_id))["phone"] == "0912345678"
    await deferred_patch(None)
    assert (await repo.by_zalo_id(chat_id))["phone"] == "0912345678"


async def test_repeated_or_other_number_denial_fences_late_confirmation_without_clearing_current(
    integration_session,
):
    db = integration_session
    chat_id = "phone-repeat-denial-order"
    conversation = await _candidate(db, chat_id)
    adapter = ServiceLeadContextAdapter(db)
    repo = LeadRepository(db)

    async def turn(text, offset):
        message = await _inbound(db, conversation, text, offset)
        await adapter.context(chat_id, text, [message])

    await turn("Em không dùng số 0987654321 nữa", 1)
    await turn("0987654321 không phải số của em", 3)
    # Processing an earlier affirmative message after a repeated denial must
    # not restore the number, even though the CRM phone was already NULL.
    await turn("Số của em là 0987654321", 2)
    assert (await repo.by_zalo_id(chat_id))["phone"] is None

    await turn("Số của em là 0912345678", 4)
    await turn("Em không dùng số 0987654321 nữa", 6)
    # The old number's denial must preserve the different current phone and
    # still fence an earlier affirmative delivery for that old number.
    await turn("Số của em là 0987654321", 5)
    assert (await repo.by_zalo_id(chat_id))["phone"] == "0912345678"
