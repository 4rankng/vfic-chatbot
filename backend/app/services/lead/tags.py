"""ORM adapter for pure recruitment lead-tag policy."""

from __future__ import annotations

from app.recruitment.domain.lead import (
    ConversationPolicy,
    LeadPolicy,
    normalize_manual_tag_key,
    normalize_manual_tag_keys,
    normalize_manual_tag_payloads,
    system_tag_keys as _system_tag_keys,
    tag_payload,
)


def _enum_value(value) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _lead_policy(lead) -> LeadPolicy:
    return LeadPolicy(
        name=lead.name,
        phone=lead.phone,
        desired_job=lead.desired_job,
        region=lead.region,
        living_area=lead.living_area,
        expected_salary=lead.expected_salary,
        lead_score=_enum_value(lead.lead_score),
        lead_stage=_enum_value(lead.lead_stage) or "NEW",
        next_action_at=lead.next_action_at,
    )


def _conversation_policy(conversation) -> ConversationPolicy | None:
    if conversation is None:
        return None
    return ConversationPolicy(
        mode=_enum_value(conversation.mode) or "BOT",
        needs_human=bool(conversation.needs_human),
    )


def system_tag_keys(lead, conversation) -> list[str]:
    return _system_tag_keys(_lead_policy(lead), _conversation_policy(conversation))


__all__ = [
    "normalize_manual_tag_key",
    "normalize_manual_tag_keys",
    "normalize_manual_tag_payloads",
    "system_tag_keys",
    "tag_payload",
]
