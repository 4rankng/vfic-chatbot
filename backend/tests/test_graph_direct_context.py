"""Deterministic evidence selection for direct-context recruitment knowledge."""

from app.graph.direct_context import direct_context_evidence_answer


_KNOWLEDGE = """
Question: LG Display Hải Phòng tuyển vị trí gì?

Answer: LG Display Hải Phòng tuyển công nhân thời vụ làm sản xuất tại Khu công nghiệp Tràng Duệ.

Question: Lương của công nhân LG Display là bao nhiêu?

Answer: Lương cơ bản hiện tại là 6.030.000 VNĐ/tháng; thu nhập ước tính 10-13 triệu khi có tăng ca.
"""


def test_exact_reported_vacancy_query_returns_verbatim_job_answer():
    answer = direct_context_evidence_answer(
        _KNOWLEDGE,
        "mình nhà ở quoán toan _hp gần lG tràng duệ."
        "bên lG tràng duệ mình đang tuyển ạ",
    )

    assert answer is not None
    assert answer.startswith("LG Display Hải Phòng tuyển công nhân thời vụ")


def test_salary_followup_selects_salary_answer_from_same_vacancy_thread():
    answer = direct_context_evidence_answer(
        _KNOWLEDGE,
        "bên lG tràng duệ mình đang tuyển ạ\nluong bao nhieu da",
    )

    assert answer is not None
    assert "6.030.000 VNĐ/tháng" in answer
    assert "10-13 triệu" in answer


def test_unrelated_query_does_not_select_recruitment_evidence():
    assert direct_context_evidence_answer(_KNOWLEDGE, "thời tiết hôm nay") is None


def test_requested_role_absent_from_evidence_does_not_select_generic_vacancy_answer():
    for query in (
        "LG có tuyển kế toán không?",
        "LG tuyển thợ hàn không?",
        "LG đang tuyển bảo vệ không?",
    ):
        assert direct_context_evidence_answer(_KNOWLEDGE, query) is None


def test_matched_evidence_answer_is_never_silently_truncated():
    full_answer = "LG Display " + ("điều kiện đã xác minh. " * 100)
    knowledge = "Question: LG Display thông báo đầy đủ?\n\n" f"Answer: {full_answer}"

    assert direct_context_evidence_answer(knowledge, "LG Display thông báo đầy đủ?") == full_answer.rstrip()
