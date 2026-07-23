from __future__ import annotations

from datetime import datetime, timezone

from app.recruitment.domain.lead import (
    ConversationPolicy,
    LeadPolicy,
    MessagePolicy,
    assist_summary,
    missing_fields,
    normalize_manual_tag_payloads,
    signals,
    system_tag_keys,
)


def test_lead_policy_is_orm_neutral_and_preserves_tag_rules() -> None:
    lead = LeadPolicy(
        phone="0909000000",
        lead_score="not_interested",
        lead_stage="SKIPPED",
        next_action_at=datetime(2026, 7, 6, 9, tzinfo=timezone.utc),
    )

    tags = system_tag_keys(lead, ConversationPolicy(mode="HUMAN", needs_human=True))

    assert tags == [
        "has_phone",
        "needs_follow_up",
        "not_interested",
        "salary_missing",
        "location_missing",
        "needs_human",
    ]


def test_lead_policy_preserves_vietnamese_view_and_custom_tag_values() -> None:
    lead = LeadPolicy(name="Anh")

    assert missing_fields(lead) == [
        "số điện thoại",
        "vị trí mong muốn",
        "khu vực",
        "mức lương mong muốn",
    ]
    assert assist_summary(
        lead,
        MessagePolicy(sender="WORKER", body="Tôi muốn tìm việc ca đêm"),
    ) == "Tin nhắn gần nhất của ứng viên: Tôi muốn tìm việc ca đêm"
    assert normalize_manual_tag_payloads(
        [],
        [{"label": "Ưu tiên ca đêm", "tone": "warn"}],
    ) == [
        {
            "key": "custom_uu_tien_ca_dem",
            "label": "Ưu tiên ca đêm",
            "tone": "warn",
        }
    ]


def test_lead_policy_signals_do_not_require_persistence_models() -> None:
    result = signals(LeadPolicy(phone="0909000000"), ConversationPolicy())
    by_key = {item["key"]: item for item in result}

    assert by_key["phone"]["active"] is True
    assert by_key["phone"]["action"] == "mark_contacting"
    assert by_key["human"]["active"] is False
