"""Unit tests for deterministic chatbot turn routing."""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.prompt_context import build_agent_user_text
from app.graph.router import route_turn, routing_instruction
from app.models.conversation import MessageSender


def test_route_recommendation_query_prefers_recommendation_tool_path():
    route = route_turn("Tôi ở Bình Dương, gợi ý việc phù hợp có ký túc xá")

    assert route.intent == "recommend"
    assert route.strategy == "recommendation"
    assert route.tools == (
        "list_active_jobs",
        "recommend_jobs",
        "recommend_projects",
        "get_product_features",
    )


def test_route_generic_vacancy_listing_exposes_active_job_tool():
    for query in (
        "giới thiệu các vị trí đang tuyển",
        "hiện tại có những công việc gì đang tuyển",
        "LG tuyển thợ hàn không?",
    ):
        route = route_turn(query)

        assert route.intent == "recommend"
        assert route.strategy == "recommendation"
        assert "list_active_jobs" in route.tools


def test_route_timetable_beats_broader_job_detail():
    route = route_turn("LG có xe đưa đón ca đêm mấy giờ?")

    assert route.intent == "timetable"
    assert route.strategy == "structured_lookup"
    assert route.tools == ("search_bus_timetable",)


def test_route_bare_shift_pay_question_stays_job_detail():
    route = route_turn("LG ca đêm lương bao nhiêu?")

    assert route.intent == "faq_detail"
    assert route.tools == ("get_product_features", "search_knowledge")


def test_route_housing_question_uses_grounded_faq_detail_path():
    route = route_turn("làm chỗ bạn có nhà trọ không?")

    assert route.intent == "faq_detail"
    assert route.strategy == "knowledge_lookup"
    assert route.tools == ("get_product_features", "search_knowledge")


def test_route_contact_requires_knowledge_lookup():
    route = route_turn("Đến công ty thì liên hệ admin nào?")

    assert route.intent == "contact"
    assert route.tools == ("search_knowledge",)


def test_route_profile_update_detects_phone_without_llm():
    route = route_turn("Số điện thoại của tôi là 0987 654 321")

    assert route.intent == "profile_update"
    assert route.strategy == "profile"


def test_route_rich_first_contact_prefers_recommendation_over_profile_only():
    route = route_turn("Em tên Lan, số 0987654321, muốn làm kho ở Bình Dương")

    assert route.intent == "recommend"
    assert route.strategy == "recommendation"


def test_route_out_of_scope_beats_fast_lane_help_keyword():
    route = route_turn("viết code giúp tôi")

    assert route.intent == "out_of_scope"
    assert route.strategy == "safe_redirect"


def test_route_internal_safety_retry_prompt_is_not_out_of_scope():
    # A safety retry prompt (built by the agent loop when re-generating a flagged
    # reply) contains the user's original text + instructions. The router must
    # classify it as general, not out_of_scope, so the retry isn't bounced.
    retry_prompt = (
        "Bạn cần viết lại câu trả lời cho người dùng cuối theo đúng guideline VFIC.\n\n"
        "Tin nhắn gốc của người dùng: tôi muốn tìm việc\n\n"
        "Yêu cầu bắt buộc:\n- Trả lời bằng tiếng Việt tự nhiên.\n"
    )
    route = route_turn(retry_prompt)

    assert route.intent == "general"
    assert route.reason == "internal_retry_prompt"


def test_route_small_talk_reuses_fast_lane_signal():
    route = route_turn("chào bạn")

    assert route.intent == "small_talk"
    assert route.strategy == "template"


def test_routing_instruction_is_injected_into_prompt_context():
    route = route_turn("gợi ý việc phù hợp")
    prompt = build_agent_user_text(
        chat_id="z1",
        current_user_text="gợi ý việc phù hợp",
        recent_messages=[],
        route_hint=routing_instruction(route),
    )

    assert "KẾ HOẠCH ĐIỀU PHỐI:" in prompt
    assert "recommend_projects" in prompt
    assert "list_active_jobs" in prompt
    assert "TIN NHẮN HIỆN TẠI CỦA ỨNG VIÊN:" in prompt


def test_prompt_context_marks_history_as_private_and_keeps_focus_on_current_message():
    prompt = build_agent_user_text(
        chat_id="z1",
        current_user_text="3+7=",
        recent_messages=[
            SimpleNamespace(
                sender=MessageSender.WORKER,
                body="Tôi là đầu bếp và muốn tìm việc ở Hải Phòng",
                delivery_status=None,
            )
        ],
    )

    assert "NGỮ CẢNH RIÊNG TƯ" in prompt
    assert "Không được trích dẫn, tóm tắt" in prompt
    assert "không gọi người dùng là 'ứng viên trước đó'" in prompt
    assert prompt.endswith("không chào lại hoặc hỏi lại thông tin đã có.")
