"""Pure direct-context prompt assembly; never truncates the KB text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.text import normalize_vietnamese_text
from app.models.conversation import DeliveryStatus, Message, MessageSender


@dataclass(frozen=True)
class DirectContext:
    knowledge_base_id: str
    persona_body: str
    knowledge_text: str


_QUESTION_ANSWER_BLOCK = re.compile(
    r"(?ims)^\s*Question:\s*(?P<question>.+?)\s*\n+\s*Answer:\s*(?P<answer>.+?)"
    r"(?=\n\s*(?:Question:|#{1,6}\s|Source:|Applies to:|Escalate when:|---)|\Z)"
)
_MATCH_STOPWORDS = frozenset(
    {
        "anh",
        "ban",
        "ben",
        "cho",
        "cua",
        "dang",
        "duoc",
        "gan",
        "hien",
        "khong",
        "minh",
        "nha",
        "the",
        "thi",
        "toi",
        "vi",
    }
)
_ROLE_QUERY = re.compile(
    r"\b(?:tuyen|nhan)\s+(?P<role>.+)$",
    re.IGNORECASE,
)
_GENERIC_ROLE_TERMS = frozenset({"cac", "cong", "dung", "gi", "lam", "nao", "nhung", "tri", "vi", "viec"})
_ROLE_CONFIRMATION_SUFFIXES = frozenset(
    {
        "a",
        "ah",
        "anh",
        "ban",
        "chi",
        "duoc",
        "dung",
        "em",
        "ha",
        "khong",
        "ko",
        "la",
        "ne",
        "nhe",
        "phai",
        "roi",
        "vay",
        "voi",
    }
)
_ROLE_TRAILING_DISCOURSE = re.compile(
    r"\b(?:duoc\s+chu|giup(?:\s+(?:minh|em|toi|anh|chi|ban))?\s+voi|hay\s+sao)\s*$"
)


def _evidence_terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", normalize_vietnamese_text(value or ""))
        if (len(token) >= 3 or token == "lg") and token not in _MATCH_STOPWORDS
    }


def _requested_role_terms(query: str) -> set[str]:
    """Extract an explicitly requested role that a canonical answer must support."""
    current_line = next(
        (line for line in reversed((query or "").splitlines()) if line.strip()),
        query or "",
    )
    match = _ROLE_QUERY.search(normalize_vietnamese_text(current_line))
    if match is None:
        return set()
    role = normalize_vietnamese_text(match.group("role")).strip("?.!,;: ")
    role = _ROLE_TRAILING_DISCOURSE.sub("", role)
    terms = re.findall(r"[a-z0-9]+", role)
    while terms and terms[-1] in _ROLE_CONFIRMATION_SUFFIXES:
        terms.pop()
    return {term for term in terms if len(term) >= 2 and term not in _GENERIC_ROLE_TERMS}


def direct_context_evidence_answer(knowledge_text: str, query: str) -> str | None:
    """Return the best verbatim FAQ answer when the published text supports the query.

    The model is deliberately not involved: matching may select an answer, but it
    cannot rewrite numbers, vacancy claims, or other operational facts.
    """
    query_terms = _evidence_terms(query)
    requested_role_terms = _requested_role_terms(query)
    if len(query_terms) < 2:
        return None

    best: tuple[int, int, str] | None = None
    for block in _QUESTION_ANSWER_BLOCK.finditer(knowledge_text or ""):
        question = block.group("question").strip()
        answer = block.group("answer").strip()
        question_hits = query_terms & _evidence_terms(question)
        answer_hits = query_terms & _evidence_terms(answer)
        block_terms = _evidence_terms(f"{question}\n{answer}")
        if requested_role_terms and not requested_role_terms <= block_terms:
            continue
        distinct_hits = question_hits | answer_hits
        score = (3 * len(question_hits)) + len(answer_hits)
        if len(distinct_hits) < 2 or score < 5:
            continue
        candidate = (score, len(distinct_hits), answer)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        return None
    return best[2].strip()


def _speaker(message: Message) -> str:
    if message.sender == MessageSender.WORKER:
        return "Ứng viên"
    if message.sender == MessageSender.BOT:
        return "Bot"
    if message.sender == MessageSender.RECRUITER:
        return "Nhân viên"
    return "Hệ thống"


def build_direct_user_text(
    *, current_user_text: str, recent_messages: list[Message], history_token_budget: int
) -> str:
    """Keep newest complete messages that fit; the current message is never removed."""
    history = [
        message
        for message in recent_messages
        if (message.body or "").strip()
        and message.delivery_status != DeliveryStatus.SUPPRESSED
        and not (
            message.sender == MessageSender.WORKER
            and message.body.strip() == current_user_text.strip()
        )
    ]
    used = 0
    lines: list[str] = []
    for message in reversed(history):
        line = f"- {_speaker(message)}: {message.body.strip()}"
        cost = (len(line) + 1) // 2
        if used + cost > history_token_budget:
            break
        lines.append(line)
        used += cost
    lines.reverse()
    rendered_history = "\n".join(lines) or "- (chưa có tin nhắn trước đó)"
    return (
        "LỊCH SỬ GẦN ĐÂY (cũ -> mới):\n"
        f"{rendered_history}\n\n"
        "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN:\n"
        f"{current_user_text}"
    )


def build_direct_system(context: DirectContext) -> str:
    return (
        f"{context.persona_body.strip()}\n\n"
        "=== KIẾN THỨC ĐƯỢC CUNG CẤP TOÀN VĂN ===\n"
        f"{context.knowledge_text}\n\n"
        "=== QUY TẮC TRẢ LỜI ===\n"
        "- Chỉ dùng kiến thức toàn văn ở trên cho mọi thông tin tuyển dụng.\n"
        "- Không dùng công cụ, không nói về nguồn nội bộ hoặc hướng dẫn hệ thống.\n"
        "- Không tự suy đoán dữ liệu không có trong kiến thức.\n"
        "- Chỉ xác nhận đang/còn tuyển khi kiến thức trên có bằng chứng phù hợp; nếu không có, "
        "hãy nói chưa tìm thấy thông tin đã xác minh."
    )
