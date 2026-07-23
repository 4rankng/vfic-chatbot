"""ORM adapter for pure recruitment lead view policy."""

from __future__ import annotations

from app.recruitment.domain.lead import (
    ConversationPolicy,
    LeadPolicy,
    MessagePolicy,
    assist_summary as _assist_summary,
    message_sender_label as _message_sender_label,
    missing_fields as _missing_fields,
    mode_label as _mode_label,
    next_action as _next_action,
    signals as _signals,
    suggested_reply as _suggested_reply,
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


def missing_fields(lead) -> list[str]:
    return _missing_fields(_lead_policy(lead))


def assist_summary(lead, latest_worker) -> str:
    message = (
        MessagePolicy(
            sender=_enum_value(latest_worker.sender) or "SYSTEM",
            body=latest_worker.body,
        )
        if latest_worker is not None
        else None
    )
    return _assist_summary(_lead_policy(lead), message)


def suggested_reply(lead, missing: list[str]) -> str:
    return _suggested_reply(_lead_policy(lead), missing)


def next_action(lead) -> str:
    return _next_action(_lead_policy(lead))


def mode_label(conversation) -> str:
    return _mode_label(_conversation_policy(conversation))


def message_sender_label(sender) -> str:
    return _message_sender_label(_enum_value(sender) or "SYSTEM")


def signals(lead, conversation) -> list[dict]:
    return _signals(_lead_policy(lead), _conversation_policy(conversation))


__all__ = [
    "assist_summary",
    "message_sender_label",
    "missing_fields",
    "mode_label",
    "next_action",
    "signals",
    "suggested_reply",
]
