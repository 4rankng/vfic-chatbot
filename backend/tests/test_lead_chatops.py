"""Unit coverage for backend ChatOps lead helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from app.models.conversation import Conversation, ConversationMode, MessageSender
from app.models.lead import Lead, LeadScore, LeadStage
from app.services.lead import LeadService
from app.shared.domain.errors import ConflictError


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


@pytest.mark.asyncio
async def test_schedule_followup_pins_due_at_to_vn_morning_and_applies_version_guard():
    """schedule_followup must land on the Vietnam business calendar and guard the
    lead write.

    The due morning is 09:00 Asia/Ho_Chi_Minh the next day (02:00 UTC) — the same
    calendar the dashboard's FOLLOWUP_TODAY counter compares on — and the
    ``next_action_at`` write goes through the optimistic-concurrency primitive
    like every other LeadService mutator.
    """
    service = LeadService(AsyncMock())
    lead = _make_lead()
    actor = SimpleNamespace(id=7, full_name="Recruiter")
    captured: dict = {}

    async def _create_followup(lead_id, due_at, note, created_by=None):
        captured["create_followup"] = (lead_id, due_at, note, created_by)
        return SimpleNamespace(id=1)

    async def _optimistic_apply(lead_id, current_version, **values):
        captured["optimistic_apply"] = (lead_id, current_version, values)
        return True

    service.repo.create_followup = _create_followup
    service.repo.optimistic_apply = _optimistic_apply
    service.db.add = Mock()  # plain sync add; AsyncMock would leak a coroutine
    service.db.refresh = AsyncMock()
    service.events.lead_updated = AsyncMock()

    await service.apply_chatops_action(lead, "schedule_followup", actor=actor)

    vn = ZoneInfo("Asia/Ho_Chi_Minh")
    due_at = captured["create_followup"][1]
    assert due_at.utcoffset() == timedelta(hours=7)
    assert (due_at.hour, due_at.minute) == (9, 0)
    assert due_at.astimezone(timezone.utc).hour == 2
    assert due_at.astimezone(vn).date() == datetime.now(vn).date() + timedelta(days=1)
    assert captured["create_followup"][0] == 1
    assert captured["create_followup"][3] == 7
    assert captured["optimistic_apply"] == (1, 1, {"next_action_at": due_at, "version": 2})


@pytest.mark.asyncio
async def test_schedule_followup_conflicts_when_lead_was_modified_concurrently():
    """A lost version race rejects the action like set_stage/assign instead of
    silently overwriting the concurrency token."""
    service = LeadService(AsyncMock())
    lead = _make_lead()
    service.repo.create_followup = AsyncMock(return_value=SimpleNamespace(id=1))
    service.repo.optimistic_apply = AsyncMock(return_value=False)
    service.db.refresh = AsyncMock()
    # The realtime bus is a transport seam; muting it keeps the only possible
    # regression signal "the action went through" instead of a serialization
    # error raised downstream of it.
    service.events.lead_updated = AsyncMock()

    with pytest.raises(ConflictError):
        await service.apply_chatops_action(
            lead, "schedule_followup", actor=SimpleNamespace(id=7, full_name="Recruiter")
        )

    # The guard IS the write path: the recruiter's stale version is the
    # precondition, and the bump it would have applied is what got refused.
    service.repo.optimistic_apply.assert_awaited_once_with(1, 1, next_action_at=ANY, version=2)
    service.db.refresh.assert_awaited_once_with(lead)
    # Refused, not applied — the lead still holds the recruiter's snapshot.
    assert lead.next_action_at is None
    assert lead.version == 1
    service.events.lead_updated.assert_not_awaited()
