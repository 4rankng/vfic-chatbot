"""Unit coverage for backend ChatOps lead helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.conversation import Conversation, ConversationMode, MessageSender
from app.models.lead import Lead, LeadScore, LeadStage
from app.services.lead import LeadService


def _make_lead(**patch) -> Lead:
    lead = Lead(
        zalo_id="zalo-1",
        name="Anh",
        phone=None,
        desired_job=None,
        expected_salary=None,
        lead_score=None,
        lead_stage=LeadStage.NEW,
    )
    lead.id = 1
    lead.version = 1
    for key, value in patch.items():
        setattr(lead, key, value)
    return lead


def _make_conversation(**patch) -> Conversation:
    conv = Conversation(zalo_chat_id="zalo-1", mode=ConversationMode.BOT)
    for key, value in patch.items():
        setattr(conv, key, value)
    return conv


def test_chatops_system_tags_reflect_lead_and_conversation_state():
    service = LeadService(AsyncMock())
    lead = _make_lead(
        phone="0909000000",
        lead_score=LeadScore.not_interested,
        lead_stage=LeadStage.SKIPPED,
        next_action_at=datetime(2026, 7, 6, 9, tzinfo=timezone.utc),
    )
    conversation = _make_conversation(mode=ConversationMode.HUMAN, needs_human=True)

    tags = service._system_tag_keys(lead, conversation)

    assert "has_phone" in tags
    assert "missing_phone" not in tags
    assert "needs_follow_up" in tags
    assert "not_interested" in tags
    assert "needs_human" in tags


def test_chatops_manual_tag_normalization_ignores_system_and_dedupes_custom():
    service = LeadService(AsyncMock())

    tags = service._normalize_manual_tag_keys(
        ["has_phone", "registered", "registered", "ưu tiên ca đêm", "needs_follow_up"]
    )

    assert tags == ["registered", "custom_uu_tien_ca_dem", "needs_follow_up"]


def test_chatops_manual_tag_payloads_preserve_custom_labels():
    service = LeadService(AsyncMock())

    payloads = service._normalize_manual_tag_payloads(
        [],
        [{"key": "custom_uu_tien_ca_dem", "label": "Ưu tiên ca đêm", "tone": "info"}],
    )

    assert payloads == [{"key": "custom_uu_tien_ca_dem", "label": "Ưu tiên ca đêm", "tone": "info"}]


def test_chatops_signals_expose_real_actions_for_next_best_steps():
    service = LeadService(AsyncMock())
    lead = _make_lead(phone="0909000000", lead_stage=LeadStage.NEW)

    signals = service._signals(lead, _make_conversation())
    by_key = {signal["key"]: signal for signal in signals}

    assert by_key["phone"]["active"] is True
    assert by_key["phone"]["action"] == "mark_contacting"
    assert by_key["followup"]["action"] == "schedule_followup"
    assert by_key["not_interested"]["action"] == "mark_not_interested"


# ── build_chatops_assist / apply_chatops_action ──────────────────────────


@pytest.mark.asyncio
async def test_build_chatops_assist_assembles_dict_with_no_conversation():
    service = LeadService(AsyncMock())
    service._conversation_for_lead = AsyncMock(return_value=None)
    service._recent_messages = AsyncMock(return_value=[])
    lead = _make_lead()  # name present; phone/job/region/salary missing

    result = await service.build_chatops_assist(lead)

    assert set(result) == {
        "summary",
        "missing",
        "reply",
        "next_action",
        "mode_label",
        "signals",
        "recent_messages",
    }
    assert result["mode_label"] == "Chưa có hội thoại"
    assert result["recent_messages"] == []
    assert "số điện thoại" in result["missing"]
    assert {signal["key"] for signal in result["signals"]} == {
        "phone",
        "not_interested",
        "followup",
        "human",
    }
    assert result["summary"] and result["reply"] and result["next_action"]


@pytest.mark.asyncio
async def test_build_chatops_assist_labels_recent_messages_and_caps_to_six():
    service = LeadService(AsyncMock())
    service._conversation_for_lead = AsyncMock(return_value=_make_conversation())
    messages = [
        SimpleNamespace(
            sender=MessageSender.WORKER,
            body=f"tin {i}",
            created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        for i in range(7)
    ]
    service._recent_messages = AsyncMock(return_value=messages)
    lead = _make_lead(phone="0909000000")

    result = await service.build_chatops_assist(lead)

    # only the last six messages are surfaced; each sender is relabeled
    assert len(result["recent_messages"]) == 6
    assert result["recent_messages"][-1] == {
        "sender": "candidate",
        "body": "tin 6",
        "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_apply_chatops_action_rejects_unknown_action():
    service = LeadService(AsyncMock())
    lead = _make_lead()

    with pytest.raises(ValueError):
        await service.apply_chatops_action(lead, "bogus_action", actor=SimpleNamespace())
