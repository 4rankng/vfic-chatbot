"""Deterministic handling for explicit vacancy-existence questions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.core.text import normalize_vietnamese_text

NO_ACTIVE_JOB_REPLY = (
    "Hiện VFIC chưa tuyển vị trí này. Bạn có muốn tôi hỗ trợ tìm các vị trí khác đang mở không?"
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
# De-accenting (normalize_vietnamese_text) collapses "nhận" (accept/recruit
# workers) and "nhắn" (send a message) into the same token "nhan". A messaging
# phrase like "nhắn tin" must not trip the nhận-based branches below — otherwise
# a complaint such as "nhắn tin cho shop mà mất 1 ngày mới hồi âm" is misread as
# a hiring question and answered with the canned NO_ACTIVE_JOB_REPLY. These fall
# through to the agent, which understands the real intent.
_ACCENT_COLLIDED_MESSAGING = ("nhan tin",)
_SHORT_ROLE_PHRASES = ("bao ve", "lai xe")
_GENERIC_VACANCY_REFERENCES = ("cong viec nay", "viec nay", "vi tri nay")
_VACANCY_SEGMENT = re.compile(r"[^.!?;\n]+(?:[.!?;]+|$)")
_VACANCY_CLAUSE_START = re.compile(r"(?i)(?=\b(?:bên|ben)\b)")
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
    # Messaging collocations (de-accented "nhắn tin") trip the "nhận"-based
    # branches below via accent collision; exclude them before those branches.
    if any(phrase in normalized for phrase in _ACCENT_COLLIDED_MESSAGING):
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
        and (
            len(continuation_tokens) >= 2 or any(role in normalized for role in _SHORT_ROLE_PHRASES)
        )
    )


def _is_detail_followup(text: str) -> bool:
    normalized = normalize_vietnamese_text(text or "")
    return any(term in normalized for term in _FOLLOWUP_TERMS)


def _has_vacancy_language(text: str) -> bool:
    normalized = normalize_vietnamese_text(text or "")
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    return (
        "tuyen" in tokens
        or "nhan" in tokens
        or "co viec" in normalized
        or "con viec" in normalized
        or is_explicit_vacancy_question(text)
    )


def _focused_vacancy_query(text: str) -> str:
    """Keep the hiring clause, not unrelated candidate-profile context."""
    stripped = (text or "").strip()
    if not stripped:
        return stripped

    segments = [part.strip() for part in _VACANCY_SEGMENT.findall(stripped) if part.strip()]
    focused = next(
        (segment for segment in reversed(segments) if _has_vacancy_language(segment)),
        stripped,
    )
    clauses = [part.strip() for part in _VACANCY_CLAUSE_START.split(focused) if part.strip()]
    return next(
        (clause for clause in reversed(clauses) if _has_vacancy_language(clause)),
        focused,
    )


def _recent_candidate_vacancy_query(
    user_text: str, recent_messages: Iterable[object]
) -> str | None:
    for message in reversed(list(recent_messages)):
        sender = getattr(message, "sender", "")
        sender_value = getattr(sender, "value", sender)
        body = str(getattr(message, "body", "") or "")
        if sender_value != "WORKER":
            continue
        if body.strip() == user_text.strip():
            continue
        return _focused_vacancy_query(body) if is_explicit_vacancy_question(body) else None
    return None


def vacancy_lookup_query(user_text: str, recent_messages: Iterable[object]) -> str | None:
    """Return the role query requiring an ACTIVE-job lookup for this turn."""
    normalized = normalize_vietnamese_text(user_text or "")
    recent_query = _recent_candidate_vacancy_query(user_text, recent_messages)
    if any(reference in normalized for reference in _GENERIC_VACANCY_REFERENCES):
        return recent_query
    if is_explicit_vacancy_question(user_text):
        return _focused_vacancy_query(user_text)
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


def _compact_fact(value: object, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return f"{clipped}…" if clipped else f"{text[: limit - 1]}…"


def _unique_job_parts(job: object, *names: str) -> list[str]:
    parts: list[str] = []
    normalized_parts: set[str] = set()
    for name in names:
        value = _compact_fact(getattr(job, name, ""), limit=100)
        normalized = normalize_vietnamese_text(value)
        if value and normalized not in normalized_parts:
            parts.append(value)
            normalized_parts.add(normalized)
    return parts


def _age_requirement(job: object) -> str:
    minimum = getattr(job, "age_min", None)
    maximum = getattr(job, "age_max", None)
    if isinstance(minimum, int) and isinstance(maximum, int):
        return f"{minimum}–{maximum} tuổi"
    if isinstance(minimum, int):
        return f"từ {minimum} tuổi"
    if isinstance(maximum, int):
        return f"đến {maximum} tuổi"
    return ""


def _single_job_advisory(job: object) -> str:
    title = _compact_fact(getattr(job, "title", ""), limit=100) or "vị trí đang tuyển"
    company = _compact_fact(getattr(job, "company_name", ""), limit=100) or "VFIC"
    location = ", ".join(_unique_job_parts(job, "factory_name", "district", "province"))
    location_text = f" tại {location}" if location else ""
    lines = [f"Chào anh/chị! Đúng rồi ạ, {company}{location_text} hiện đang tuyển {title}."]

    facts: list[str] = []
    description = _compact_fact(getattr(job, "description", ""))
    if description:
        facts.append(f"Công việc: {description}")

    age = _age_requirement(job)
    gender = _compact_fact(getattr(job, "gender_requirement", ""), limit=80)
    audience = "; ".join(part for part in (age, gender) if part)
    if audience:
        facts.append(f"Đối tượng: {audience}")

    experience = _compact_fact(getattr(job, "experience_required", ""))
    if experience:
        facts.append(f"Kinh nghiệm: {experience}")

    requirements = _compact_fact(getattr(job, "requirements", ""))
    if requirements:
        facts.append(f"Hồ sơ/yêu cầu: {requirements}")

    facts.append(f"Mức lương: {_salary_text(job).removeprefix('lương ')}")

    shift = _compact_fact(getattr(job, "shift", ""))
    if shift:
        facts.append(f"Ca làm: {shift}")

    support_labels = (
        ("transport_support", "xe đưa đón"),
        ("accommodation_support", "chỗ ở"),
        ("meal_support", "bữa ăn"),
    )
    supports = [label for field, label in support_labels if getattr(job, field, None) is True]
    if supports:
        facts.append(f"Hỗ trợ: {', '.join(supports)}")

    benefits = _compact_fact(getattr(job, "benefits", ""))
    if benefits:
        facts.append(f"Phúc lợi: {benefits}")

    if facts:
        lines.extend(["", "Thông tin chính:", *(f"- {fact}" for fact in facts)])
    lines.extend(
        [
            "",
            "Anh/chị muốn xem kỹ hơn về lương, ca làm, hồ sơ hay phúc lợi của vị trí này ạ?",
        ]
    )
    return "\n".join(lines)


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
    if len(jobs) == 1:
        return _single_job_advisory(jobs[0])
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
