"""Pure lead policy values used by recruitment application adapters."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

_TAG_META: dict[str, dict[str, str | bool]] = {
    "has_phone": {"label": "Có SĐT", "tone": "good", "system": True},
    "missing_phone": {"label": "Thiếu SĐT", "tone": "warn", "system": True},
    "needs_follow_up": {"label": "Cần follow-up", "tone": "info", "system": False},
    "not_interested": {"label": "Không quan tâm", "tone": "danger", "system": False},
    "registered": {"label": "Đã đăng ký", "tone": "good", "system": False},
    "salary_missing": {"label": "Thiếu lương", "tone": "warn", "system": False},
    "location_missing": {"label": "Thiếu khu vực", "tone": "warn", "system": False},
    "needs_human": {"label": "Cần người xử lý", "tone": "danger", "system": False},
}
_MANUAL_TAG_KEYS = {key for key, meta in _TAG_META.items() if not bool(meta.get("system"))}
_SYSTEM_TAG_KEYS = {key for key, meta in _TAG_META.items() if bool(meta.get("system"))}


@dataclass(frozen=True, slots=True)
class LeadPolicy:
    name: str | None = None
    phone: str | None = None
    desired_job: str | None = None
    region: str | None = None
    living_area: str | None = None
    expected_salary: str | None = None
    lead_score: str | None = None
    lead_stage: str = "NEW"
    next_action_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConversationPolicy:
    mode: str = "BOT"
    needs_human: bool = False


@dataclass(frozen=True, slots=True)
class MessagePolicy:
    sender: str
    body: str


def tag_payload(key: str, *, system: bool) -> dict:
    meta = _TAG_META[key]
    return {
        "key": key,
        "label": meta["label"],
        "tone": meta["tone"],
        "system": system,
    }


def system_tag_keys(
    lead: LeadPolicy,
    conversation: ConversationPolicy | None,
) -> list[str]:
    tags = ["has_phone" if lead.phone and lead.phone.strip() else "missing_phone"]
    if lead.next_action_at:
        tags.append("needs_follow_up")
    if lead.lead_score == "not_interested" or lead.lead_stage == "SKIPPED":
        tags.append("not_interested")
    if lead.lead_stage == "REGISTERED":
        tags.append("registered")
    if not (lead.expected_salary and lead.expected_salary.strip()):
        tags.append("salary_missing")
    if not (lead.region and lead.region.strip()) and not (
        lead.living_area and lead.living_area.strip()
    ):
        tags.append("location_missing")
    if conversation is not None and (
        conversation.needs_human or conversation.mode == "HUMAN"
    ):
        tags.append("needs_human")
    return tags


def normalize_manual_tag_keys(keys: list[str]) -> list[str]:
    return [payload["key"] for payload in normalize_manual_tag_payloads(keys, [])]


def normalize_manual_tag_payloads(
    keys: list[str],
    tags: list[dict],
) -> list[dict[str, str]]:
    payloads: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw_key: str, raw_label: str | None = None, tone: str = "info") -> None:
        source = (raw_label or raw_key or "").strip()
        if not source:
            return
        key = normalize_manual_tag_key(raw_key or source)
        if not key or key in _SYSTEM_TAG_KEYS or key in seen:
            return
        if key in _MANUAL_TAG_KEYS:
            meta = _TAG_META[key]
            label = str(meta["label"])
            tag_tone = str(meta["tone"])
        else:
            label = source[:64]
            tag_tone = tone if tone in {"good", "warn", "danger", "info"} else "info"
        payloads.append({"key": key, "label": label, "tone": tag_tone})
        seen.add(key)

    for key in keys:
        add(key)
    for tag in tags:
        raw_key = str(tag.get("key") or tag.get("label") or "")
        label = tag.get("label")
        add(raw_key, str(label) if label is not None else None, str(tag.get("tone") or "info"))
    return payloads[:12]


def normalize_manual_tag_key(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value in _TAG_META:
        return value
    if value.startswith("custom_") and re.fullmatch(r"custom_[a-z0-9_]{1,40}", value):
        return value
    vietnamese_safe = value.replace("đ", "d").replace("Đ", "D")
    ascii_value = (
        unicodedata.normalize("NFKD", vietnamese_safe)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    key = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
    if not key:
        key = re.sub(r"\s+", "_", value.lower()).strip("_")
        key = re.sub(r"[^\w]+", "_", key).strip("_")
    if not key:
        return ""
    custom_key = f"custom_{key[:40]}"
    return "" if custom_key in _SYSTEM_TAG_KEYS else custom_key


def missing_fields(lead: LeadPolicy) -> list[str]:
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


def assist_summary(lead: LeadPolicy, latest_worker: MessagePolicy | None) -> str:
    if lead.lead_score == "not_interested" or lead.lead_stage == "SKIPPED":
        return (
            "Ứng viên đã thể hiện không quan tâm. Nên dừng nhắn chủ động trừ khi có tín hiệu mới."
        )
    if latest_worker is not None:
        snippet = latest_worker.body.strip().replace("\n", " ")[:140]
        return f"Tin nhắn gần nhất của ứng viên: {snippet}"
    if lead.phone:
        return "Ứng viên đã có số điện thoại. Ưu tiên xác nhận nhu cầu, khu vực và chuyển sang bước đăng ký."
    return "Chưa có tin nhắn gần đây. Ưu tiên xin số điện thoại trước khi để bot tư vấn dài."


def suggested_reply(lead: LeadPolicy, missing: list[str]) -> str:
    if lead.lead_score == "not_interested" or lead.lead_stage == "SKIPPED":
        return (
            "Cảm ơn bạn đã phản hồi. Nếu sau này bạn muốn tìm việc lại, mình luôn sẵn sàng hỗ trợ."
        )
    if missing:
        fields = " và ".join(missing[:2])
        return f"Mình hỗ trợ bạn nhanh hơn nếu bạn cho mình {fields} nhé."
    return "Mình đã có đủ thông tin chính. Bạn muốn tư vấn viên gọi xác nhận hồ sơ không?"


def next_action(lead: LeadPolicy) -> str:
    if lead.next_action_at:
        return "Đã có lịch follow-up. Kiểm tra lại trước khi gửi thêm tin."
    if lead.lead_score == "not_interested" or lead.lead_stage == "SKIPPED":
        return "Dừng follow-up tự động và chỉ mở lại khi ứng viên chủ động phản hồi."
    if lead.phone:
        return "Đặt follow-up gần nhất và chuyển ứng viên sang Đang liên hệ."
    return "Xin số điện thoại, sau đó tạo follow-up nếu ứng viên phản hồi."


def mode_label(conversation: ConversationPolicy | None) -> str:
    if conversation is None:
        return "Chưa có hội thoại"
    return {
        "HUMAN": "Người xử lý",
        "SEMI_AUTO": "Bán tự động",
        "CLOSED": "Đã đóng",
    }.get(conversation.mode, "Chatbot")


def message_sender_label(sender: str) -> str:
    return {
        "WORKER": "candidate",
        "RECRUITER": "recruiter",
        "BOT": "bot",
    }.get(sender, "system")


def signals(
    lead: LeadPolicy,
    conversation: ConversationPolicy | None,
) -> list[dict]:
    not_interested = lead.lead_score == "not_interested" or lead.lead_stage == "SKIPPED"
    has_phone = bool(lead.phone and lead.phone.strip())
    needs_human = bool(
        conversation is not None
        and (conversation.needs_human or conversation.mode == "HUMAN")
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


__all__ = [
    "ConversationPolicy",
    "LeadPolicy",
    "MessagePolicy",
    "assist_summary",
    "message_sender_label",
    "missing_fields",
    "mode_label",
    "next_action",
    "normalize_manual_tag_key",
    "normalize_manual_tag_keys",
    "normalize_manual_tag_payloads",
    "signals",
    "suggested_reply",
    "system_tag_keys",
    "tag_payload",
]
