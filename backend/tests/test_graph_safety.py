"""Unit tests for graph/safety.py — the deterministic guards (off-topic/code
detection, verdict parsing, retry builder). These implement acceptance #5
(off-topic refusal) without needing an LLM."""
from app.graph.safety import (
    build_retry_prompt,
    fast_safety_filter,
    parse_verdict,
    retry_exhausted_fallback,
)


def test_fast_safety_clean_reply_needs_no_llm():
    out = fast_safety_filter("Chào bạn, bạn muốn tìm việc ở khu vực nào?")
    assert out["needs_llm_safety"] is False
    assert out["safe_to_send"] is True
    assert out["issue_type"] == "none"


def test_fast_safety_strips_markdown_and_flags_code():
    # markdown bold/headers get cleaned; mentions of code trigger LLM safety
    out = fast_safety_filter("Đây là **code** python: ```print(1)```")
    assert out["needs_llm_safety"] is True
    assert "```" not in out["output"]
    assert "**" not in out["output"]


def test_fast_safety_flags_internal_terms():
    out = fast_safety_filter("Tôi sẽ chạy workflow và gọi api database")
    assert out["needs_llm_safety"] is True


def test_fast_safety_too_long_flagged():
    out = fast_safety_filter("x" * 2000)
    assert out["needs_llm_safety"] is True


def test_parse_verdict_clean_json():
    v = parse_verdict('{"safe_to_send": true, "issue_found": false, "issue_type": "none", "final_answer": "ok"}')
    assert v["safe_to_send"] is True
    assert v["final_answer"] == "ok"


def test_parse_verdict_fenced_json():
    v = parse_verdict('```json\n{"safe_to_send": true, "final_answer": "hi"}\n```')
    assert v["safe_to_send"] is True and v["final_answer"] == "hi"


def test_parse_verdict_invalid_json():
    v = parse_verdict("not json at all")
    assert v["safe_to_send"] is False
    assert v["issue_type"] == "invalid_verdict_json"


def test_parse_verdict_vietnamese_bool_and_empty_final_blocks_send():
    # safe_to_send "có" but empty final_answer -> not safe
    v = parse_verdict('{"safe_to_send": "có", "final_answer": ""}')
    assert v["safe_to_send"] is False


def test_retry_exhausted_fallback_technical_vs_generic():
    assert "tuyển dụng" in retry_exhausted_fallback("viết code python giúp tôi")
    assert retry_exhausted_fallback("tôi muốn tìm việc") != retry_exhausted_fallback("viết code")


def test_build_retry_prompt_contains_user_text_and_rules():
    p = build_retry_prompt("viết code", "đây là ```print```", "code_detected")
    assert "viết code" in p
    assert "code_detected" in p
    assert "1 câu hỏi" in p
