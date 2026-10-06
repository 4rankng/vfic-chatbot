

def test_collapse_repeated_sentences_drops_the_third_identical_reading():
    """Regression pin for the 2026-10-06 "cam on" answer.

    The turn degenerated and shipped the same opener four times in one
    message. Sentences said once or twice survive (genuine emphasis); the
    third identical normalized reading is dropped.
    """
    from app.graph.answer_repair import _join_answer_parts

    once = "Dạ không có gì ạ 😊 Anh cứ nhắn cho em khi cần tìm hiểu thêm dự án nào nhé."
    answer = _join_answer_parts(
        [f"{once} {once}", f"{once} Thời vụ vẫn cần hồ sơ đơn giản ạ."]
    )
    assert answer.count("Dạ không có gì ạ") == 2
    assert answer.count("Thời vụ vẫn cần hồ sơ") == 1
    # The answer is still one readable block, not an emptied one.
    assert "Anh cứ nhắn cho em" in answer


def test_collapse_repeated_sentences_keeps_distinct_sentences():
    from app.graph.answer_repair import _join_answer_parts

    answer = _join_answer_parts(
        ["LG Display làm ca ngày 08:00-20:00. Ca đêm 20:00-08:00.",
         "Tổng thu nhập khoảng 10-13 triệu tăng ca."]
    )
    assert answer == (
        "LG Display làm ca ngày 08:00-20:00. Ca đêm 20:00-08:00."
        "Tổng thu nhập khoảng 10-13 triệu tăng ca."
    )
