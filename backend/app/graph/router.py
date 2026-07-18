"""Deterministic turn routing for the chatbot brain.

The router is intentionally cheap and conservative: it never calls an LLM and it
does not decide the final answer. It annotates the turn with an intent/strategy
so the existing tool-calling agent can start from the right retrieval path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.core.text import normalize_vietnamese_text
from app.graph.fast_lane import match as fast_lane_match

TurnIntent = Literal[
    "small_talk",
    "recommend",
    "profile_update",
    "timetable",
    "contact",
    "faq_detail",
    "out_of_scope",
    "general",
]

TurnStrategy = Literal[
    "template",
    "recommendation",
    "profile",
    "structured_lookup",
    "knowledge_lookup",
    "safe_redirect",
    "agent",
]

# Strategies eligible for the fast-tier model (Phase 5 model tiering). These are
# low-complexity paths where a non-reasoning model suffices: social chitchat
# (template), contact-info lookups, and simple single-fact FAQ detail questions.
# Recommendation / profile / general-agent paths always use the reasoning model.
FAST_MODEL_STRATEGIES: frozenset[str] = frozenset({"template", "knowledge_lookup", "safe_redirect"})


def should_use_fast_model(route: "TurnRoute") -> bool:
    """Whether this route's strategy qualifies for the fast-tier model.

    The caller still checks that a fast model is actually configured before
    switching; this predicate only encodes *eligibility* so the policy lives
    in one place (alongside the intent taxonomy).
    """
    return route.strategy in FAST_MODEL_STRATEGIES


@dataclass(frozen=True)
class TurnRoute:
    intent: TurnIntent
    strategy: TurnStrategy
    tools: tuple[str, ...] = ()
    reason: str = ""
    confidence: float = 0.0


_PHONE_RE = re.compile(r"(?:\+?84|0)(?:\D*\d){8,10}\b")

_CONTACT_TERMS = (
    "lien he",
    "admin",
    "hotline",
    "so dien thoai",
    "sdt",
    "zalo",
    "den cong ty",
    "gap ai",
)

_TIMETABLE_TERMS = (
    "xe dua don",
    "tuyen xe",
    "lich xe",
    "diem don",
    "gio don",
    "xe may gio",
    "xe buyt",
    "bus",
)

_RECOMMEND_TERMS = (
    "goi y",
    "phu hop",
    "tim viec",
    "viec nao",
    "con viec",
    "muon lam",
    "ung tuyen",
    "can viec",
    "kiem viec",
)

_PROFILE_TERMS = (
    "toi ten",
    "minh ten",
    "em ten",
    "ten la",
    "toi o",
    "minh o",
    "song o",
    "dang song",
    "khu vuc",
    "mong muon luong",
    "luong mong muon",
    "kinh nghiem",
)

_DETAIL_TERMS = (
    "luong",
    "thu nhap",
    "phu cap",
    "ktx",
    "ky tuc xa",
    "nha tro",
    "khu tro",
    "cho o",
    "luu tru",
    "o xa",
    "ho so",
    "ca lam",
    "ca ngay",
    "ca dem",
    "tang ca",
    "thuong",
    "bao hiem",
    "dia diem",
    "yeu cau",
    "dieu kien",
    "quy trinh",
    "do tuoi",
    "gioi tinh",
)

_CURRENT_OPENING_PHRASES = (
    "dang tuyen",
    "con tuyen",
    "co tuyen",
    "can tuyen",
)

_VACANCY_PHRASES = (
    *_CURRENT_OPENING_PHRASES,
    "tuyen vi tri",
    "tuyen cong viec",
    "tuyen nhan vien",
    "tuyen dung vi tri",
    "tuyen dung cong viec",
)

_GENERIC_VACANCY_LISTING_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^(?:gioi thieu|cho (?:minh|toi|em) xem) (?:tat ca )?(?:cac |nhung )?"
        r"(?:vi tri|cong viec|viec lam) (?:hien )?dang tuyen$",
        r"^(?:hien tai |hien gio |bay gio )?(?:co |con )?(?:nhung |cac )?"
        r"(?:cong viec|viec lam|vi tri)(?: gi| nao)? (?:dang|con) tuyen$",
        r"^(?:ben (?:minh|ban) )?(?:dang|con|co|can) tuyen(?: dung)?"
        r"(?: (?:nhung|cac))?(?: (?:cong viec|viec lam|vi tri))?(?: gi| nao)?$",
        r"^(?:ben (?:minh|ban) )?(?:hien )?(?:co|con) "
        r"(?:viec|viec lam|cong viec|vi tri)(?: gi| nao)?(?: khong| ko)?$",
    )
)

_LISTING_CUE_TERMS = frozenset({"cac", "gi", "job", "nao", "nhung", "viec"})
_ROLE_TAIL_GENERIC_TERMS = frozenset(
    {
        "a",
        "ah",
        "cac",
        "duoc",
        "dung",
        "gi",
        "khong",
        "ko",
        "nao",
        "nhi",
        "nhung",
        "the",
        "tri",
        "vay",
        "vi",
        "viec",
    }
)
_PROPER_SUBJECT_STOPWORDS = frozenset(
    {
        "anh",
        "ban",
        "ben",
        "cho",
        "co",
        "cong",
        "da",
        "dang",
        "don",
        "em",
        "hien",
        "hoi",
        "minh",
        "toi",
        "xin",
    }
)
_ROLE_TAIL = re.compile(r"\b(?:tuyen|nhan)\s+(?P<role>.+)$")

_NON_ROLE_ACCEPTANCE_PREFIXES = (
    "vien",  # normalized "nhân viên": avoids treating "có nhân viên" as "có nhận"
    "ho so",
    "cuoc goi",
    "tin nhan",
    "dien thoai",
    "thanh toan",
    "don hang",
    "hang ",
)

_INTERNAL_RETRY_PREFIX = "ban can viet lai cau tra loi"

_OUT_OF_SCOPE_TERMS = (
    "viet code",
    "debug code",
    "lam bai tap",
    "ke chuyen cuoi",
    "ke chuyen",
    "lam tho",
    "choi game",
    "hack",
    "jailbreak",
    "system prompt",
)


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalize(text: str) -> str:
    clean = normalize_vietnamese_text(text or "")
    return re.sub(r"\s+", " ", clean).strip()


def is_vacancy_lookup(user_text: str) -> bool:
    """Whether a turn asks the LLM to check recruitment knowledge for openings."""
    text = _normalize(user_text)
    if not text:
        return False
    has_detail = _has_any(text, _DETAIL_TERMS)
    if _has_any(text, _TIMETABLE_TERMS):
        return False
    if _has_any(text, _CURRENT_OPENING_PHRASES):
        return True
    if "tuyen" in text.split() and has_detail:
        return False
    if "tuyen" in text.split() or _has_any(text, _VACANCY_PHRASES):
        return True
    if re.search(
        r"\b(?:hien\s+)?(?:co|con)\s+(?:viec(?:\s+lam)?|cong\s+viec|vi\s+tri)"
        r"(?:\s+(?:gi|nao|trong))?\s+(?:khong|ko)\b",
        text,
    ):
        return True
    accepting = re.search(
        r"\b(?:co|con|dang) nhan\s+(?P<object>.+?)(?:\s+(?:khong|ko))?[?.!]*$",
        text,
    )
    if accepting is None:
        return False
    candidate_object = accepting.group("object").strip()
    return not candidate_object.startswith(_NON_ROLE_ACCEPTANCE_PREFIXES)


def _explicit_role_terms(text: str) -> set[str]:
    match = _ROLE_TAIL.search(text)
    if match is None:
        return set()
    return {
        term
        for term in re.findall(r"[a-z0-9]+", match.group("role"))
        if term not in _ROLE_TAIL_GENERIC_TERMS
    }


def has_specific_vacancy_target(user_text: str) -> bool:
    """Whether a turn positively names a company/location or a role target."""
    normalized = _normalize(user_text)
    if _explicit_role_terms(normalized):
        return True
    if "lg" in re.findall(r"[a-z0-9]+", normalized):
        return True
    for token in re.findall(r"[^\W\d_]+", user_text or "", flags=re.UNICODE):
        normalized_token = normalize_vietnamese_text(token)
        if (
            token[:1].isupper()
            and normalized_token not in _PROPER_SUBJECT_STOPWORDS
            and len(normalized_token) >= 2
        ):
            return True
    return False


def is_generic_vacancy_listing(user_text: str) -> bool:
    """Whether the user asks for the full current catalog without a named target."""
    text = re.sub(r"[?.!,;:]+$", "", _normalize(user_text)).strip()
    if not is_vacancy_lookup(text):
        return False
    if any(pattern.fullmatch(text) for pattern in _GENERIC_VACANCY_LISTING_PATTERNS):
        return True
    if has_specific_vacancy_target(user_text):
        return False
    if _LISTING_CUE_TERMS & set(re.findall(r"[a-z0-9]+", text)):
        return True
    return bool(
        re.fullmatch(
            r"(?:ben (?:minh|ban) )?(?:dang|con|co|can) tuyen(?: dung)?"
            r"(?: khong| ko)?",
            text,
        )
    )


def route_turn(user_text: str) -> TurnRoute:
    """Classify a user turn into the first retrieval strategy to try.

    Priority order matters: bus/timetable and contact lookups are deterministic
    evidence paths, so they beat broader recommendation/detail intents.
    """
    raw = user_text or ""
    text = _normalize(raw)
    if not text:
        return TurnRoute("general", "agent", reason="empty", confidence=0.1)

    if text.startswith(_INTERNAL_RETRY_PREFIX):
        return TurnRoute("general", "agent", reason="internal_retry_prompt", confidence=0.1)

    if _has_any(text, _OUT_OF_SCOPE_TERMS):
        return TurnRoute(
            "out_of_scope", "safe_redirect", reason="off_domain_terms", confidence=0.85
        )

    if fast_lane_match(raw) is not None:
        return TurnRoute("small_talk", "template", reason="fast_lane_match", confidence=0.95)

    has_recommendation = _has_any(text, _RECOMMEND_TERMS)
    has_detail = _has_any(text, _DETAIL_TERMS)
    vacancy_lookup = is_vacancy_lookup(raw)
    has_phone = bool(_PHONE_RE.search(raw))

    if _has_any(text, _TIMETABLE_TERMS):
        return TurnRoute(
            "timetable",
            "structured_lookup",
            tools=("search_bus_timetable",),
            reason="timetable_terms",
            confidence=0.9,
        )

    if _has_any(text, _CONTACT_TERMS) and not has_phone:
        return TurnRoute(
            "contact",
            "knowledge_lookup",
            tools=("search_knowledge",),
            reason="contact_terms",
            confidence=0.9,
        )

    if vacancy_lookup:
        if is_generic_vacancy_listing(raw):
            return TurnRoute(
                "recommend",
                "structured_lookup",
                tools=("list_active_jobs",),
                reason="vacancy_listing",
                confidence=0.94,
            )
        return TurnRoute(
            "recommend",
            "knowledge_lookup",
            tools=("search_knowledge",),
            reason="vacancy_terms",
            confidence=0.92,
        )

    if has_recommendation:
        return TurnRoute(
            "recommend",
            "recommendation",
            tools=(
                "list_active_jobs",
                "recommend_jobs",
                "recommend_projects",
                "get_product_features",
            ),
            reason="recommendation_terms",
            confidence=0.86,
        )

    if has_detail:
        return TurnRoute(
            "faq_detail",
            "knowledge_lookup",
            tools=("get_product_features", "search_knowledge"),
            reason="job_detail_terms",
            confidence=0.8,
        )

    if has_phone or _has_any(text, _PROFILE_TERMS):
        reason = "phone_number" if has_phone else "profile_terms"
        return TurnRoute("profile_update", "profile", reason=reason, confidence=0.78)

    return TurnRoute("general", "agent", reason="fallback", confidence=0.45)


def routing_instruction(route: TurnRoute) -> str:
    """Vietnamese prompt hint for the tool-calling agent."""
    if route.intent == "small_talk":
        return "Ý định: trò chuyện xã giao. Trả lời ngắn gọn, thân thiện; không cần tra cứu nếu không có câu hỏi tuyển dụng."
    if route.intent == "recommend":
        if route.reason == "vacancy_listing":
            return (
                "Ý định: xem toàn bộ việc đang tuyển. Bắt buộc gọi list_active_jobs không "
                "truyền bộ lọc, rồi trả nguyên danh sách việc ACTIVE từ kết quả công cụ; "
                "không bổ sung vị trí ngoài danh mục."
            )
        if route.reason == "vacancy_terms":
            return (
                "Ý định: kiểm tra thông tin việc làm đang tuyển. Dùng search_knowledge để tra "
                "cứu KB tuyển dụng được gán cho agent, rồi trả lời tự nhiên chỉ từ bằng chứng "
                "tìm thấy; không suy đoán vị trí hoặc quyền lợi không có trong KB."
            )
        return (
            "Ý định: gợi ý việc phù hợp. Nếu đã có hồ sơ ứng viên (lương/khu vực/vị trí), "
            "ưu tiên gọi recommend_jobs(chat_id) để gợi ý việc theo hồ sơ; nếu chưa đủ hồ sơ "
            "thì dùng recommend_projects. Sau đó gọi get_product_features cho slug dự án đã "
            "chọn để nêu lý do cụ thể. Chỉ gợi ý việc/dự án có trong dữ liệu."
        )
    if route.intent == "profile_update":
        return (
            "Ý định: ứng viên đang bổ sung hồ sơ/nhu cầu. Ghi nhận thông tin trong mạch hội thoại, "
            "trả lời xác nhận ngắn và chỉ hỏi thêm một trường còn thiếu nếu cần."
        )
    if route.intent == "timetable":
        return (
            "Ý định: hỏi lịch xe/tuyến/điểm đón/giờ đón. Phải dùng search_bus_timetable trước; "
            "không suy đoán giờ hoặc điểm dừng nếu tool không có dữ liệu."
        )
    if route.intent == "contact":
        return (
            "Ý định: hỏi liên hệ/admin/hotline/Zalo. Phải dùng search_knowledge trước; "
            "chỉ trả lời số điện thoại hoặc người liên hệ có trong KB."
        )
    if route.intent == "faq_detail":
        return (
            "Ý định: hỏi chi tiết tuyển dụng. Nếu đã xác định dự án, ưu tiên get_product_features; "
            "nếu cần dẫn chứng rộng hơn thì dùng search_knowledge. Dữ liệu chưa có thì nói chưa ghi rõ."
        )
    if route.intent == "out_of_scope":
        return (
            "Ý định ngoài phạm vi tuyển dụng. Từ chối nhẹ nhàng và kéo cuộc trò chuyện về tìm việc, "
            "hồ sơ, lịch xe hoặc thông tin VFIC."
        )
    return "Ý định chưa rõ. Trả lời theo mạch hội thoại và dùng công cụ tra cứu khi có câu hỏi tuyển dụng."
