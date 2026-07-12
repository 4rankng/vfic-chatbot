"""Chatops assist view-model builders for leads (pure functions, no DB).

Extracted from ``LeadService``: the signal/summary/suggested-reply/next-action
presentation logic that feeds ``build_chatops_assist``. The service composes these
via thin delegates.
"""

from __future__ import annotations

from app.models.conversation import Conversation, ConversationMode, Message, MessageSender
from app.models.lead import Lead, LeadScore, LeadStage


def missing_fields(lead: Lead) -> list[str]:
    missing: list[str] = []
    if not (lead.name and lead.name.strip()):
        missing.append("tên")
    if not (lead.phone and lead.phone.strip()):
        missing.append("số điện thoại")
    if not (lead.desired_job and lead.desired_job.strip()):
        missing.append("vị trí mong muốn")
    if not (lead.region and lead.region.strip()) and not (
        lead.living_area and lead.living_area.strip()
    ):
        missing.append("khu vực")
    if not (lead.expected_salary and lead.expected_salary.strip()):
        missing.append("mức lương mong muốn")
    return missing


def assist_summary(lead: Lead, latest_worker: Message | None) -> str:
    if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
        return (
            "Ứng viên đã thể hiện không quan tâm. Nên dừng nhắn chủ động trừ khi có tín hiệu mới."
        )
    if latest_worker is not None:
        snippet = latest_worker.body.strip().replace("\n", " ")[:140]
        return f"Tin nhắn gần nhất của ứng viên: {snippet}"
    if lead.phone:
        return "Ứng viên đã có số điện thoại. Ưu tiên xác nhận nhu cầu, khu vực và chuyển sang bước đăng ký."
    return "Chưa có tin nhắn gần đây. Ưu tiên xin số điện thoại trước khi để bot tư vấn dài."


def suggested_reply(lead: Lead, missing: list[str]) -> str:
    if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
        return (
            "Cảm ơn bạn đã phản hồi. Nếu sau này bạn muốn tìm việc lại, mình luôn sẵn sàng hỗ trợ."
        )
    if missing:
        fields = " và ".join(missing[:2])
        return f"Mình hỗ trợ bạn nhanh hơn nếu bạn cho mình {fields} nhé."
    return "Mình đã có đủ thông tin chính. Bạn muốn tư vấn viên gọi xác nhận hồ sơ không?"


def next_action(lead: Lead) -> str:
    if lead.next_action_at:
        return "Đã có lịch follow-up. Kiểm tra lại trước khi gửi thêm tin."
    if lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED:
        return "Dừng follow-up tự động và chỉ mở lại khi ứng viên chủ động phản hồi."
    if lead.phone:
        return "Đặt follow-up gần nhất và chuyển ứng viên sang Đang liên hệ."
    return "Xin số điện thoại, sau đó tạo follow-up nếu ứng viên phản hồi."


def mode_label(conversation: Conversation | None) -> str:
    if conversation is None:
        return "Chưa có hội thoại"
    if conversation.mode == ConversationMode.HUMAN:
        return "Người xử lý"
    if conversation.mode == ConversationMode.SEMI_AUTO:
        return "Bán tự động"
    if conversation.mode == ConversationMode.CLOSED:
        return "Đã đóng"
    return "Chatbot"


def message_sender_label(sender: MessageSender) -> str:
    if sender == MessageSender.WORKER:
        return "candidate"
    if sender == MessageSender.RECRUITER:
        return "recruiter"
    if sender == MessageSender.BOT:
        return "bot"
    return "system"


def signals(lead: Lead, conversation: Conversation | None) -> list[dict]:
    not_interested = (
        lead.lead_score == LeadScore.not_interested or lead.lead_stage == LeadStage.SKIPPED
    )
    has_phone = bool(lead.phone and lead.phone.strip())
    needs_human = bool(
        conversation is not None
        and (conversation.needs_human or conversation.mode == ConversationMode.HUMAN)
    )
    return [
        {
            "key": "phone",
            "name": "Số điện thoại",
            "status": "Đã có thể liên hệ" if has_phone else "Chưa có dữ liệu",
            "active": has_phone,
            "action": "mark_contacting" if has_phone else None,
        },
        {
            "key": "not_interested",
            "name": "Không quan tâm",
            "status": "Nên dừng follow-up" if not_interested else "Chưa có tín hiệu",
            "active": not_interested,
            "action": "mark_not_interested" if not not_interested else None,
        },
        {
            "key": "followup",
            "name": "Follow-up",
            "status": "Đã có lịch" if lead.next_action_at else "Nên đặt lịch",
            "active": bool(lead.next_action_at),
            "action": None if lead.next_action_at else "schedule_followup",
        },
        {
            "key": "human",
            "name": "Cần người xử lý",
            "status": "Đang ưu tiên" if needs_human else "Theo dõi",
            "active": needs_human,
            "action": None,
        },
    ]
