"""Turn routing policy for the chatbot brain.

The meaning judgments (intent, sort direction, vacancy listing, pleasantry
kind, context flags) come from the Jev fan-out (``graph/decisions.py``) behind
the ``TurnDecisionsPort``; this module owns only the policy that maps those
raw judgments onto a retrieval strategy, tool set, and reason label. It never
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
    "employee_support",
    "out_of_scope",
    "general",
]

TurnStrategy = Literal[
    "recommendation",
    "profile",
    "structured_lookup",
    "knowledge_lookup",
    "safe_redirect",
    "agent",
]

# Strategies eligible for the fast-tier model (Phase 5 model tiering). Only
# gentle redirects qualify: they carry no evidence and no conversion step.
# ``knowledge_lookup`` stays off the fast tier deliberately — it serves the
# detail questions (pay, shifts, dorm) most likely to produce a lead, where
# accuracy beats the seconds a faster model saves.
FAST_MODEL_STRATEGIES: frozenset[str] = frozenset({"safe_redirect"})

# Reason code for a route decision: the label explaining why this strategy and
# tool set were chosen. "empty" is the unrouted default.
RouteReason = Literal[
    "empty",
    "internal_retry_prompt",
    "small_talk_terms",
    "off_domain_terms",
    "timetable_terms",
    "contact_terms",
    "vacancy_listing",
    "recommendation_terms",
    "job_detail_terms",
    "employee_support_terms",
    "employee_support_continuation",
    "employee_support_clarify",
    "phone_number",
    "profile_terms",
    "not_job_seeking",
    "fallback",
]


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
    # Why this strategy/tool set was chosen; "empty" is the unrouted default.
    reason: RouteReason = "empty"
    confidence: float = 0.0


# Machine protocol marker, not a user-language judgment: the retry-rewrite
# path re-enters the graph with this sentinel as the pseudo user text. No
# model call is spent classifying our own internal prompt.
_INTERNAL_RETRY_PREFIX = "ban can viet lai cau tra loi"


def route_from_decisions(user_text: str, decisions: TurnDecisions) -> TurnRoute:
    """Map the raw Jev judgments onto the first retrieval strategy.

    Mirrors the keyword router it replaced: a pure pleasantry wins first
    (small_talk intent, agent strategy); ``vacancy_listing`` refines
    ``recommend``; contact-info presence upgrades an otherwise-unrouted turn to
    profile capture. Reason codes label the chosen route.
    """
    text = (user_text or "").strip()
    if not text:
        return TurnRoute("general", "agent", reason="empty", confidence=0.1)

    if text.startswith(_INTERNAL_RETRY_PREFIX):
        return TurnRoute("general", "agent", reason="internal_retry_prompt", confidence=0.1)

    intent = decisions.intent if decisions.intent in TURN_INTENTS else "general"

    # Mid-flow continuity outranks the per-message reading: while the assistant's
    # last reply was part-way through an account-support step, a short follow-up
    # ("sao rồi", "ok", a bare phone number, or a restated profile detail) is an
    # answer to that step, not small talk and not a new lead — routing it as such
    # dropped the TingTing tools and left the employee with "vẫn đang chờ".
    if decisions.recent_account_support and intent in {
        "small_talk",
        "general",
        "out_of_scope",
        "profile_update",
    }:
        return employee_support_route(
            reason="employee_support_continuation",
            confidence=max(decisions.intent_confidence, 0.6),
        )

    if decisions.pleasantry or decisions.intent == "small_talk":
        return TurnRoute(
            "small_talk",
            "agent",
            reason="small_talk_terms",
            confidence=max(decisions.intent_confidence, 0.9 if decisions.pleasantry else 0.0),
        )

    # Real-intention gate (operator rule 2026-10-03): a confident "not looking
    # for new work" reading — an existing worker with a contract/HR matter or an
    # explicit stay-put — must never reach the recommendation lanes (the
    # "Hợp đồng thử việc cũng hết rồi" case answered with project pitches).
    # Placed before the phone-capture upgrade: a number does not turn a
    # non-seeker into a lead. Employee account support and contact questions
    # stay reachable whatever the job intention is; pleasantry and mid-flow
    # continuation already returned above.
    if decisions.job_seeking == "not_seeking" and intent not in _NOT_JOB_SEEKING_EXEMPT:
        return TurnRoute(
            intent,  # type: ignore[arg-type]
            "safe_redirect",
            tools=(),
            reason="not_job_seeking",
            confidence=decisions.intent_confidence,
        )

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
            tools=("list_active_projects",),
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


# intent -> (strategy, tools, reason) — one place for the whole mapping.
# Keys are runtime intent names, so the dict stays open (not keyed by TurnIntent).
_INTENT_ROUTES: dict[
    str, tuple[TurnStrategy, tuple[str, ...], RouteReason]
] = {
    "recommend": (
        "recommendation",
        ("list_active_projects", "get_product_features", "load_project_knowledge"),
        "recommendation_terms",
    ),
    "profile_update": ("profile", (), "profile_terms"),
    "timetable": ("structured_lookup", ("search_bus_timetable",), "timetable_terms"),
    "contact": ("knowledge_lookup", ("search_knowledge", "load_project_knowledge"), "contact_terms"),
    "faq_detail": (
        "knowledge_lookup",
        ("get_product_features", "search_knowledge", "load_project_knowledge"),
        "job_detail_terms",
    ),
    # Employees locked out of the TingTing app (forgot/reset password, no OTP)
    # must reach the reset API, never a refusal. ``search_knowledge`` rides along
    # so the turn can still cite published policy alongside the mechanic.
    "employee_support": (
        "knowledge_lookup",
        (
            "verify_tingting_identity",
            "send_tingting_otp",
            "confirm_tingting_otp",
            "reset_tingting_password",
            "search_knowledge",
        ),
        "employee_support_terms",
    ),
    "out_of_scope": ("safe_redirect", (), "off_domain_terms"),
    "general": ("agent", (), "fallback"),
}

# Runtime-visible intent names (derived so the Literal stays the single source).
TURN_INTENTS: frozenset[str] = frozenset(
    TurnIntent.__metadata__[0].__args__  # type: ignore[attr-defined]
) if hasattr(TurnIntent, "__metadata__") else frozenset(_INTENT_ROUTES) | {"small_talk"}

# Intents that say "the employee wants help here but has not named the problem"
# (or that Jev could not read at all). On the TingTing support OA these are not a
# reason to call a human: the bot asks the fixed confirm question (Anh/chị cần
# đặt lại mật khẩu ứng dụng TingTing phải không ạ?), so the reset flow can start
# from the answer (see ``lanes._agent_turn``).
_SUPPORT_CLARIFY_INTENTS: frozenset[str] = frozenset({"general", "small_talk"})

# Intents a "not looking for new work" message may still legitimately mean on
# this OA: account support and contact questions are in scope whatever the job
# intention is, so the hotline gate must not intercept them.
_NOT_JOB_SEEKING_EXEMPT: frozenset[str] = frozenset({"employee_support", "contact"})


def employee_support_route(*, reason: RouteReason, confidence: float) -> TurnRoute:
    """The employee-support route with the caller's own reason.

    Shared by the mid-flow continuation (``route_from_decisions``) and the
    support OA's clarifying turn (``lanes._agent_turn``) so the reset tool set
    and strategy live in exactly one place.
    """
    strategy, tools, _reason = _INTENT_ROUTES["employee_support"]
    return TurnRoute(
        "employee_support",
        strategy,
        tools=tools,
        reason=reason,
        confidence=confidence,
    )


# Vietnamese prompt hint per intent for the tool-calling agent (consumed by
# runner.build_agent_user_text via routing_instruction).
def requires_project_catalog(route: TurnRoute, decisions: TurnDecisions) -> bool:
    """Whether recruitment routing requires a complete catalog lookup."""
    return route.reason == "vacancy_listing" or (
        route.intent == "general" and decisions.recent_vacancy
    )


def routing_instruction(route: TurnRoute) -> str:
    if route.intent == "small_talk":
        return "Ý định: trò chuyện xã giao. Trả lời ngắn gọn, thân thiện; không cần tra cứu nếu không có câu hỏi tuyển dụng."
    if route.intent == "recommend":
        if route.reason == "vacancy_listing":
            return (
                "Ý định: ứng viên hỏi về việc làm. Bắt buộc gọi list_active_projects "
                "(truyền các tiêu chí ứng viên nêu: job_scope/location/salary_min_vnd/company/"
                "sort_by; chưa nêu thì gọi không bộ lọc). Trả lời theo hợp đồng trong safe_reply: "
                "nếu chưa rõ mong muốn và chưa yêu cầu xem lựa chọn → hỏi một câu ngắn; "
                "không bắt phải khai đủ công việc/khu vực/mức lương mới tư vấn. Khi đã có "
                "bất kỳ tiêu chí hoặc muốn xem lựa chọn → giới thiệu dự án theo fit_score, "
                "mỗi dự án một khối. Với yêu cầu tất cả/toàn bộ, phải nêu đủ mọi dự án "
                "trong projects của kết quả tool, không tự giới hạn số dự án."
            )
        return (
            "Ý định: gợi ý việc phù hợp. Ưu tiên gọi list_active_projects với các tiêu chí "
            "ứng viên nêu (job_scope/location/salary_min_vnd/company/sort_by); nếu chưa rõ "
            "mong muốn và chưa muốn xem lựa chọn thì hỏi một câu ngắn trước. Không bắt "
            "khai đủ các tiêu chí mới giới thiệu. Với yêu cầu tất cả/toàn bộ, nêu đủ từng "
            "dự án trong kết quả tool của phạm vi hiện tại. Sau đó "
            "gọi get_product_features cho slug dự án đã chọn để nêu lý do cụ thể. "
            "Chỉ gợi ý dự án có trong dữ liệu."
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
    if route.intent == "employee_support":
        return (
            "Ý định: nhân viên đang làm cần hỗ trợ tài khoản/hệ thống của dự án (quên mật khẩu, "
            "đổi/đặt lại mật khẩu, không nhận được OTP). Phải đọc mục "
            "API TINGTING và chạy đúng từng bước trong hướng dẫn, hỏi từng bước một thay vì tự đoán. "
            "XÁC MINH DANH TÍNH BẰNG TOOL: gọi verify_tingting_identity(phone, full_name, cccd) "
            "với đúng những gì nhân viên đã cung cấp — không tự so khớp bằng mắt và không tự "
            "kết luận trường nào khớp. Chỉ gửi OTP khi tool trả về ĐÃ XÁC MINH. Chưa xác minh thì "
            "hỏi đúng những trường ở mục 'cần hỏi lại' của tool: không hỏi lại trường đã khớp, "
            "không hỏi lại số điện thoại đã có trong hội thoại. "
            "Mỗi lượt phải nói rõ đang ở bước nào và cần gì tiếp theo; không trả lời chung chung "
            "kiểu 'đang chờ' và không hỏi lại thông tin đã có. "
            "Không được nói việc này ngoài phạm vi khi hướng dẫn đã có endpoint phù hợp. "
            "Chỉ nói lại đúng kết quả tool trả về; không tự nghĩ ra hotline, email hay mã."
        )
    if route.intent == "out_of_scope":
        return (
            "Ý định ngoài phạm vi hỗ trợ của VFIC (tuyển dụng + hỗ trợ nhân viên đang làm). "
            "TRƯỚC KHI TỪ CHỐI: nếu mục API TINGTING đang có sẵn cho việc đang được hỏi thì phải "
            "gọi verify_tingting_identity theo hướng dẫn và trả lời theo kết quả tool, không "
            "từ chối. "
            "Chỉ khi không có hướng dẫn phù hợp mới từ chối nhẹ nhàng và kéo cuộc trò chuyện về "
            "tìm việc, hồ sơ, lịch xe, hoặc vấn đề của nhân viên tại dự án VFIC. "
            "KHÔNG được trả lời nội dung câu hỏi (ví dụ cách tính thuế) hay hướng dẫn cách làm "
            "cho việc ngoài phạm vi — chỉ mời gọi. "
            "Khi phải từ chối, PHẢI mời ứng viên gọi đúng số hotline VFIC đã nêu trong mục "
            "SỰ THẬT CỐ ĐỊNH của system prompt; không nêu hotline, email hay người liên hệ nào khác."
        )
    return "Ý định chưa rõ. Trả lời theo mạch hội thoại và dùng công cụ tra cứu khi có câu hỏi tuyển dụng."
