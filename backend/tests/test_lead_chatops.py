"""Unit coverage for backend ChatOps lead helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.models.conversation import Conversation, ConversationMode
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

    assert payloads == [
        {"key": "custom_uu_tien_ca_dem", "label": "Ưu tiên ca đêm", "tone": "info"}
    ]


def test_chatops_signals_expose_real_actions_for_next_best_steps():
    service = LeadService(AsyncMock())
    lead = _make_lead(phone="0909000000", lead_stage=LeadStage.NEW)

    signals = service._signals(lead, _make_conversation())
    by_key = {signal["key"]: signal for signal in signals}

    assert by_key["phone"]["active"] is True
    assert by_key["phone"]["action"] == "mark_contacting"
    assert by_key["followup"]["action"] == "schedule_followup"
    assert by_key["not_interested"]["action"] == "mark_not_interested"
