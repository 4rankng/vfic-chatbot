"""Tests for proactive opt-out detection in ConversationState.record_inbound().

When an inbound message body matches any phrase in
settings.proactive_optout_phrases_list, conv.followup_opted_out is set to True.
"""
import pytest

from app.models.conversation import Conversation
from app.services.conversation import ConversationService

pytestmark = pytest.mark.asyncio


async def _make_conv(db, zalo_id="optout-test-1"):
    conv = Conversation(zalo_chat_id=zalo_id)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def test_optout_vietnamese_phrase_dung(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-dung")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Tôi muốn dừng")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_vietnamese_phrase_khong_quan_tam(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-kqtam")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Không quan tâm nữa")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_english_phrase_stop(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-stop")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Stop sending me messages")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_english_phrase_unsubscribe(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-unsub")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Please unsubscribe")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_phrase_dung_nhan(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-dungnhan")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Đừng nhắn nữa")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_no_optout_normal_message(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-normal")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Xin chào, tôi muốn hỏi về công việc")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is False


async def test_no_optout_empty_body(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-empty")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is False


async def test_no_optout_whitespace_body(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-ws")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="   ")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is False


async def test_optout_case_insensitive(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-upper")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="DỪNG NHẮN ĐI")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_substring_match(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-substr")
    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Tôi bận rồi, nói chuyện sau nhé")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_optout_is_idempotent(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-idem")
    conv.followup_opted_out = True
    await db_session.commit()
    await db_session.refresh(conv)

    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Đừng nhắn nữa")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True


async def test_no_optout_after_optout_set(db_session):
    conv = await _make_conv(db_session, zalo_id="optout-sticky")
    conv.followup_opted_out = True
    await db_session.commit()
    await db_session.refresh(conv)

    svc = ConversationService(db_session)
    await svc.record_inbound(conv, body="Cảm ơn bạn nhiều")
    await db_session.refresh(conv)
    assert conv.followup_opted_out is True
