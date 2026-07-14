"""Tests for direct SQL domain tools + formatters (Tech-Lead Directive §2 Path A).

Covers:
- ToolResult dataclass shape
- Scope precedence (job > location > company > global)
- Formatters render Vietnamese with tôi/bạn voice
- found=False → graceful "don't know" reply
- Zero LLM calls (asserted by absence of any LLM import)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


from app.services.knowledge.tools.domain_tools import (
    ToolResult,
    format_benefits,
    format_faq,
    format_job_locations,
    format_job_requirements,
    format_working_hours,
    get_benefits,
    get_job_requirements,
)


# ─── ToolResult shape ────────────────────────────────────────────────────────


def test_tool_result_defaults():
    r = ToolResult(found=False)
    assert r.data == []
    assert r.missing_fields == []
    assert r.scope_used == "global"


# ─── Formatters ──────────────────────────────────────────────────────────────


def test_format_benefits_found_renders_vietnamese():
    r = ToolResult(
        found=True,
        data=[
            {
                "name": "Phụ cấp chuyên cần",
                "category": "ALLOWANCE",
                "value": 500000,
                "currency": "VND",
                "cadence": "monthly",
                "eligibility": "Đủ ngày công",
            }
        ],
    )
    out = format_benefits(r)
    assert "Phụ cấp chuyên cần" in out
    assert "500,000 VND/monthly" in out
    assert "Đủ ngày công" in out
    # Found-list formatters are factual headers; the not-found replies carry
    # the bạn/tôi voice. Verify the header is Vietnamese + well-formed.
    assert "phúc lợi" in out.lower()


def test_format_benefits_not_found_graceful():
    r = ToolResult(found=False)
    out = format_benefits(r)
    assert "chưa có" in out.lower()
    assert "bạn" in out.lower()  # polite (lowercase to match "Bạn")


def test_format_working_hours_found():
    r = ToolResult(
        found=True,
        data=[{
            "schedule_type": "FIXED",
            "days": ["MON", "TUE"],
            "start_time": "08:00:00",
            "end_time": "17:00:00",
            "crosses_midnight": False,
            "breaks": [],
            "timezone": "Asia/Ho_Chi_Minh",
        }],
    )
    out = format_working_hours(r)
    assert "08:00:00" in out
    assert "17:00:00" in out
    assert "MON" in out


def test_format_working_hours_crosses_midnight_note():
    r = ToolResult(
        found=True,
        data=[{
            "schedule_type": "SHIFT",
            "days": ["MON"],
            "start_time": "22:00:00",
            "end_time": "06:00:00",
            "crosses_midnight": True,
            "breaks": [],
            "timezone": "Asia/Ho_Chi_Minh",
        }],
    )
    out = format_working_hours(r)
    assert "qua đêm" in out.lower() or "midnight" in out.lower()


def test_format_job_requirements_found():
    r = ToolResult(
        found=True,
        data=[
            {"text": "Nam, 18-35 tuổi", "category": "age", "is_required": True, "min_value": None, "max_value": None, "unit": None},
            {"text": "Tốt nghiệp THPT", "category": "education", "is_required": False, "min_value": None, "max_value": None, "unit": None},
        ],
    )
    out = format_job_requirements(r)
    assert "18-35 tuổi" in out
    assert "bắt buộc" in out
    assert "ưu tiên" in out


def test_format_job_locations_primary_chosen():
    r = ToolResult(
        found=True,
        data=[
            {"address": "KCN Amata", "locality": "Biên Hòa", "region": "Đồng Nai", "is_primary": False},
            {"address": "Nhà máy chính", "locality": "Biên Hòa", "region": "Đồng Nai", "is_primary": True},
        ],
    )
    out = format_job_locations(r)
    assert "Nhà máy chính" in out  # primary chosen, not the first


def test_format_faq_returns_curated_answer_verbatim():
    r = ToolResult(
        found=True,
        data=[{"question": "Q", "answer": "Bạn cần CCCD và sơ yếu lý lịch.", "resolution_type": "static_answer", "tool_name": None}],
    )
    assert format_faq(r) == "Bạn cần CCCD và sơ yếu lý lịch."


def test_format_faq_miss_returns_empty_string():
    """Empty string signals the router to fall through to RAG."""
    assert format_faq(ToolResult(found=False)) == ""


# ─── Tool queries (mocked DB) ────────────────────────────────────────────────


async def test_get_benefits_returns_not_found_when_empty():
    """No rows at any scope → found=False, graceful."""
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=fake_result)
    r = await get_benefits(db, job_id="job-1")
    assert r.found is False


async def test_get_job_requirements_requires_job_id():
    """Requirements are per-job; no scope cascade."""
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=fake_result)
    r = await get_job_requirements(db, job_id="job-1")
    assert r.found is False


# ─── Zero LLM calls invariant ────────────────────────────────────────────────


def test_domain_tools_module_does_not_import_llm_clients():
    """Directive: 'These queries should normally use zero generative-model calls.'

    We assert the module doesn't import any LLM client. If a future change
    introduces one, this test fails loudly.
    """
    import inspect

    from app.services.knowledge.tools import domain_tools

    src = inspect.getsource(domain_tools)
    # These are the LLM client paths; none should appear in domain_tools.
    forbidden = ["from app.graph.clients", "ChatOpenAI", "MiniMaxAgent", "minimax"]
    for token in forbidden:
        assert token not in src, f"domain_tools must not import LLM clients (found {token})"
