"""Lead-profile probing rules used by chatbot turns."""
from __future__ import annotations

import re

from app.models.conversation import Message, MessageSender

_PHONE_RE = re.compile(r"(?:\+?84|0)(?:\D*\d){8,10}\b")


def _last_bot_message(recent_messages: list[Message]) -> str:
    for msg in reversed(recent_messages):
        if msg.sender == MessageSender.BOT and (msg.body or "").strip():
            return msg.body.strip()
    return ""


def _bot_asked_for_name(text: str) -> bool:
    lowered = (text or "").casefold()
    return "tên" in lowered and any(token in lowered for token in ("bạn", "cho tôi", "cho mình", "xin"))


def _current_text_answers_name(current_user_text: str, recent_messages: list[Message]) -> bool:
    text = re.sub(r"\s+", " ", current_user_text or "").strip()
    if not text or _PHONE_RE.search(text):
        return False
    lowered = text.casefold()
    if any(marker in lowered for marker in ("tôi tên", "mình tên", "em tên", "anh tên", "chị tên", "tên là")):
        return True
    if _bot_asked_for_name(_last_bot_message(recent_messages)):
        return 1 <= len(text.split()) <= 5 and len(text) <= 50
    return False


def _lead_has_value(lead: dict | None, key: str) -> bool:
    if not lead:
        return False
    return bool(str(lead.get(key) or "").strip())


def lead_collection_instruction(*, question: str) -> str:
    return (
        "THU THẬP THÔNG TIN ỨNG VIÊN:\n"
        "- Sau khi trả lời nội dung chính, hãy kết thúc bằng câu hỏi thu thập "
        "(hoặc lồng ghép tự nhiên vào câu trả lời):\n"
        f"  → {question}\n"
        "- KHÔNG hỏi lại cùng một thông tin hai lần trong một tin nhắn. "
        "Nếu đã hỏi rồi (bằng bất kỳ cách nào), không hỏi lại nữa.\n"
        "- Ưu tiên giữ mạch hội thoại tự nhiên."
    )


# Askable fields: (db_key, question). Order = probing priority.
# ``notes`` is passive capture (never probed — no natural "what are your notes?" question).
ASKABLE_FIELDS: list[tuple[str, str]] = [
    ("name", "Bạn cho tôi xin tên để tiện hỗ trợ nhé?"),
    ("phone", "Bạn cho tôi xin số điện thoại để VFIC liên hệ hỗ trợ ứng tuyển nhé?"),
    ("desired_job", "Bạn muốn ứng tuyển vị trí công việc nào?"),
    ("region", "Bạn muốn làm việc ở tỉnh/thành nào?"),
    ("living_area", "Bạn đang sinh sống ở khu vực nào?"),
    ("expected_salary", "Bạn mong muốn mức lương khoảng bao nhiêu?"),
]


# Cheap keyword checks — if the current turn mentions any of these, assume the
# user already answered the corresponding field this turn (prevents re-asking
# before the async extraction worker updates the lead row).
FIELD_DETECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "desired_job": ("làm việc", "công việc", "vị trí", "ứng tuyển", "muốn làm", "tìm việc"),
    "region": (
        "tỉnh", "thành phố",
        "hải phòng", "hai phong",
        "hà nội", "ha noi",
        "đà nẵng", "da nang",
        "hcm", "hồ chí minh", "ho chi minh",
        "bình dương", "binh duong",
        "đồng nai", "dong nai",
        "bắc ninh", "bac ninh",
        "hưng yên", "hung yen",
    ),
    "living_area": ("sống ở", "đang sống", "sinh sống", "quê ở", "địa chỉ"),
    "expected_salary": ("lương", "triệu"),
}


def lead_collection_question(
    *,
    lead: dict | None,
    current_user_text: str,
    recent_messages: list[Message],
) -> str:
    text = current_user_text or ""
    for field, question in ASKABLE_FIELDS:
        if _lead_has_value(lead, field):
            continue
        # Per-field same-turn "already answered" guards.
        if field == "name" and _current_text_answers_name(text, recent_messages):
            continue
        if field == "phone" and bool(_PHONE_RE.search(text)):
            continue
        keywords = FIELD_DETECT_KEYWORDS.get(field)
        if keywords:
            lowered = text.casefold()
            if any(kw in lowered for kw in keywords):
                continue
        return question
    return ""


def _compact_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


# Per-field keyword fingerprints. If the model's reply already mentions any of
# these, the field is considered "already asked" — the canonical question is
# NOT appended (prevents the model asking in its own words + the system asking
# again in one message). Keys mirror ASKABLE_FIELDS.
_ALREADY_ASKED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "name": ("tên", "xưng hô"),
    "phone": ("số điện thoại", "sđt", "điện thoại", "số phone", "liên hệ"),
    "desired_job": ("vị trí", "công việc", "ứng tuyển vị trí", "muốn làm"),
    "region": ("tỉnh", "thành", "khu vực muốn", "làm việc ở"),
    "living_area": ("sinh sống", "đang ở", "đang sống"),
    "expected_salary": ("lương", "triệu"),
}


def _field_for_question(question: str) -> str | None:
    """Reverse-lookup which ASKABLE_FIELDS entry a canonical question belongs to."""
    lowered = (question or "").casefold()
    for field, q in ASKABLE_FIELDS:
        if _compact_for_match(q.rstrip("?")) == _compact_for_match(lowered.rstrip("?")):
            return field
    return None


def _reply_already_asks(reply: str, field: str) -> bool:
    """True if the reply already asks for ``field`` in any wording."""
    keywords = _ALREADY_ASKED_KEYWORDS.get(field)
    if not keywords:
        return False
    lowered = _compact_for_match(reply)
    return any(kw in lowered for kw in keywords)


def ensure_lead_collection_question(reply: str, question: str) -> str:
    if not question:
        return reply
    text = (reply or "").strip()
    if not text:
        return question
    # Exact-string match (legacy): model echoed the canonical question verbatim.
    if _compact_for_match(question.rstrip("?")) in _compact_for_match(text):
        return text
    # Semantic match: model asked for the same field in different wording.
    # Do NOT append — appending would produce two asks for the same field in one
    # message (the model's + the canonical one).
    field = _field_for_question(question)
    if field and _reply_already_asks(text, field):
        return text
    # Otherwise append — never replace the model's last paragraph.
    return f"{text}\n\n{question}"
