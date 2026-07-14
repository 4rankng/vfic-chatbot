"""Deterministic handling for explicit vacancy-existence questions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.core.text import normalize_vietnamese_text

NO_ACTIVE_JOB_REPLY = (
    "Hiện VFIC chưa tuyển vị trí này. "
    "Bạn có muốn tôi hỗ trợ tìm các vị trí khác đang mở không?"
)
VACANCY_LOOKUP_UNAVAILABLE_REPLY = (
    "Hiện tôi chưa thể kiểm tra thông tin tuyển dụng. Bạn vui lòng thử lại sau nhé."
)

_QUESTION_SUFFIXES = frozenset({"a", "ah", "ha", "khong", "ko", "nhe", "nhi", "roi", "sao"})
_NON_VACANCY_TOPICS = (
    "ca lam",
    "cho o",
    "ho so",
    "ktx",
    "luong",
    "nha tro",
    "xe dua don",
)
_SHORT_ROLE_PHRASES = ("bao ve", "lai xe")
_GENERIC_VACANCY_REFERENCES = ("cong viec nay", "viec nay", "vi tri nay")
_FOLLOWUP_TERMS = frozenset(
    {
        "dia diem",
        "o dau",
        "ca nao",
        "lam ca",
        "can kinh nghiem",
        "kinh nghiem",
        "ho so",
        "ktx",
        "luong",
        "phu cap",
        "thu nhap",
        "thuong",
        "tuyen xe",
        "xe dua don",
        "yeu cau",
    }
)


def is_explicit_vacancy_question(text: str) -> bool:
    """Recognize direct Vietnamese questions asking whether a role is recruiting."""
    normalized = normalize_vietnamese_text(text or "")
    tokens = re.findall(r"[a-z0-9]+", normalized)
    if "ung tuyen" in normalized and "tuyen" not in normalized.replace("ung tuyen", ""):
        return False
    if "co viec" in normalized or "con viec" in normalized:
        return True
    is_question = "?" in text or any(token in _QUESTION_SUFFIXES for token in tokens)
    if any(topic in normalized for topic in _NON_VACANCY_TOPICS):
        return False
    if "tuyen" in tokens and is_question:
        return True
    if "tuyen" in tokens:
        return any(
        phrase in normalized for phrase in ("co tuyen", "con tuyen", "dang tuyen", "van tuyen")
        )
    if is_question and "co" in tokens and "nhan" in tokens:
        return True
    continuation_tokens = {
        token
        for token in tokens
        if len(token) >= 3 and token not in {"con", "khong", "nay", "tri", "viec"}
    }
    if is_question and "nhan" in tokens and len(continuation_tokens) >= 2:
        return True
    return (
        is_question
        and ("con" in tokens)
        and ("khong" in tokens or "ko" in tokens)
        and (len(continuation_tokens) >= 2 or any(role in normalized for role in _SHORT_ROLE_PHRASES))
    )


def _is_detail_followup(text: str) -> bool:
    normalized = normalize_vietnamese_text(text or "")
    return any(term in normalized for term in _FOLLOWUP_TERMS)


def _recent_candidate_vacancy_query(user_text: str, recent_messages: Iterable[object]) -> str | None:
    for message in reversed(list(recent_messages)):
        sender = getattr(message, "sender", "")
        sender_value = getattr(sender, "value", sender)
        body = str(getattr(message, "body", "") or "")
        if sender_value != "WORKER":
            continue
        if body.strip() == user_text.strip():
            continue
        return body if is_explicit_vacancy_question(body) else None
    return None


def vacancy_lookup_query(user_text: str, recent_messages: Iterable[object]) -> str | None:
    """Return the role query requiring an ACTIVE-job lookup for this turn."""
    normalized = normalize_vietnamese_text(user_text or "")
    recent_query = _recent_candidate_vacancy_query(user_text, recent_messages)
    if any(reference in normalized for reference in _GENERIC_VACANCY_REFERENCES):
        return recent_query
    if is_explicit_vacancy_question(user_text):
        return user_text
    return recent_query if _is_detail_followup(user_text) else None


def _salary_text(job: object) -> str:
    minimum = getattr(job, "salary_min", None)
    maximum = getattr(job, "salary_max", None)
    if isinstance(minimum, int) and isinstance(maximum, int):
        return f"lương {minimum // 1_000_000}-{maximum // 1_000_000} triệu"
    if isinstance(minimum, int):
        return f"lương từ {minimum // 1_000_000} triệu"
    if isinstance(maximum, int):
        return f"lương đến {maximum // 1_000_000} triệu"
    return "lương chưa công bố"


def format_vacancy_lookup(lookup: object) -> str:
    """Render only facts carried by verified ACTIVE job records."""
    status = getattr(lookup, "status", "unavailable")
    if status == "no_match":
        return NO_ACTIVE_JOB_REPLY
    if status != "matched":
        return VACANCY_LOOKUP_UNAVAILABLE_REPLY

    jobs = tuple(getattr(lookup, "jobs", ()) or ())
    if not jobs:
        return VACANCY_LOOKUP_UNAVAILABLE_REPLY
    lines = ["Có, VFIC hiện đang tuyển các vị trí sau:"]
    for job in jobs:
        details = [
            str(getattr(job, "company_name", "") or ""),
            str(getattr(job, "factory_name", "") or ""),
            str(getattr(job, "province", "") or ""),
            _salary_text(job),
        ]
        rendered_details = "; ".join(part for part in details if part)
        lines.append(f"- {getattr(job, 'title', 'Vị trí đang tuyển')}: {rendered_details}")
    lines.append("Bạn muốn tôi hỗ trợ kiểm tra điều kiện ứng tuyển vị trí nào ạ?")
    return "\n".join(lines)
