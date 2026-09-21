"""Turn routing policy for the chatbot brain.

The meaning judgments (intent, sort direction, vacancy listing, pleasantry
kind, context flags) come from the Jev fan-out (``graph/decisions.py``) behind
the ``TurnDecisionsPort``; this module owns only the policy that maps those
raw judgments onto a retrieval strategy, tool set, and trace label. It never
calls a model and does not decide the final answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.graph.ports import TurnDecisions

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

# Strategies eligible for the fast-tier model (Phase 5 model tiering). Only
# social chitchat and gentle redirects qualify: they carry no evidence and no
# conversion step. ``knowledge_lookup`` stays off the fast tier deliberately —
# it serves the detail questions (pay, shifts, dorm) most likely to produce a
# lead, where accuracy beats the seconds a faster model saves.
FAST_MODEL_STRATEGIES: frozenset[str] = frozenset({"template", "safe_redirect"})


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


# Machine protocol marker, not a user-language judgment: the retry-rewrite
# path re-enters the graph with this sentinel as the pseudo user text. No
# model call is spent classifying our own internal prompt.
_INTERNAL_RETRY_PREFIX = "ban can viet lai cau tra loi"


def route_from_decisions(user_text: str, decisions: TurnDecisions) -> TurnRoute:
    """Map the raw Jev judgments onto the first retrieval strategy.

    Mirrors the keyword router it replaced: a pure pleasantry wins first
    (template lane); ``vacancy_listing`` refines ``recommend``; contact-info
    presence upgrades an otherwise-unrouted turn to profile capture. Reason
    codes reuse the existing decision-trace literals (schemas/bot_run.py) so
    the trace contract stays intact.
    """
    text = (user_text or "").strip()
    if not text:
        return TurnRoute("general", "agent", reason="empty", confidence=0.1)

    if text.startswith(_INTERNAL_RETRY_PREFIX):
        return TurnRoute("general", "agent", reason="internal_retry_prompt", confidence=0.1)

    if decisions.pleasantry or decisions.intent == "small_talk":
        return TurnRoute(
            "small_talk",
            "template",
            reason="fast_lane_match",
            confidence=max(decisions.intent_confidence, 0.9 if decisions.pleasantry else 0.0),
        )

    intent = decisions.intent if decisions.intent in TURN_INTENTS else "general"
    if intent in {"general", "out_of_scope"} and decisions.contact_info:
        return TurnRoute(
            "profile_update",
            "profile",
            reason="phone_number",
            confidence=decisions.intent_confidence,
        )

    if intent == "recommend" and decisions.vacancy_listing:
        return TurnRoute(
            "recommend",
            "structured_lookup",
            tools=("list_active_jobs",),
            reason="vacancy_listing",
            confidence=decisions.intent_confidence,
        )

    strategy, tools, reason = _INTENT_ROUTES[intent]
    return TurnRoute(
        intent,  # type: ignore[arg-type]
        strategy,
        tools=tools,
        reason=reason,
        confidence=decisions.intent_confidence,
    )


# intent -> (strategy, tools, trace reason) — one place for the whole mapping.
_INTENT_ROUTES = {
    "recommend": (
        "recommendation",
        ("list_active_jobs", "recommend_jobs", "recommend_projects", "get_product_features"),
        "recommendation_terms",
    ),
    "profile_update": ("profile", (), "profile_terms"),
    "timetable": ("structured_lookup", ("search_bus_timetable",), "timetable_terms"),
    "contact": ("knowledge_lookup", ("search_knowledge",), "contact_terms"),
    "faq_detail": ("knowledge_lookup", ("get_product_features", "search_knowledge"), "job_detail_terms"),
    "out_of_scope": ("safe_redirect", (), "off_domain_terms"),
    "general": ("agent", (), "fallback"),
}

# Runtime-visible intent names (derived so the Literal stays the single source).
TURN_INTENTS: frozenset[str] = frozenset(
    TurnIntent.__metadata__[0].__args__  # type: ignore[attr-defined]
) if hasattr(TurnIntent, "__metadata__") else frozenset(_INTENT_ROUTES) | {"small_talk"}


# Vietnamese prompt hint per intent for the tool-calling agent (consumed by
# runner.build_agent_user_text via routing_instruction).
def routing_instruction(route: TurnRoute) -> str:
    if route.intent == "small_talk":
        return "Ý định: trò chuyện xã giao. Trả lời ngắn gọn, thân thiện; không cần tra cứu nếu không có câu hỏi tuyển dụng."
    if route.intent == "recommend":
        if route.reason == "vacancy_listing":
            return (
                "Ý định: xem toàn bộ việc đang tuyển. Bắt buộc gọi list_active_jobs không "
                "truyền bộ lọc, rồi trả nguyên danh sách việc ACTIVE từ kết quả công cụ; "
                "không bổ sung vị trí ngoài danh mục."
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
            "Ý định ngoài phạm vi hỗ trợ của VFIC (tuyển dụng + hỗ trợ nhân viên đang làm). "
            "Từ chối nhẹ nhàng và kéo cuộc trò chuyện về tìm việc, hồ sơ, lịch xe, hoặc vấn đề "
            "của nhân viên tại dự án VFIC."
        )
    return "Ý định chưa rõ. Trả lời theo mạch hội thoại và dùng công cụ tra cứu khi có câu hỏi tuyển dụng."
