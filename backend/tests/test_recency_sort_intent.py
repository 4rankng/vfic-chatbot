"""Tests for ``detect_recency_sort_intent`` (plan 260722-2300, Phase 4a).

Covers the diacritic-insensitive detection of "gần nhất" / "mới nhất" intent and its
wiring through ``_vacancy_required_args`` into forced ``list_active_jobs`` args.
"""

from __future__ import annotations

from app.graph.router import detect_recency_sort_intent
from app.graph.runner import _vacancy_required_args


def test_detect_recency_gan_nhat():
    assert detect_recency_sort_intent("việc làm gần nhất") == "created_at"


def test_detect_recency_moi_nhat():
    assert detect_recency_sort_intent("Có việc mới nhất không?") == "created_at"


def test_detect_recency_vua_moi():
    assert detect_recency_sort_intent("việc vừa mới đăng") == "created_at"


def test_detect_recency_returns_none_for_salary_question():
    # "bao nhiêu tiền" is a salary/amount question, not a recency question.
    assert detect_recency_sort_intent("bao nhiêu tiền") is None


def test_detect_recency_returns_none_for_generic_question():
    assert detect_recency_sort_intent("cho tôi xem việc làm") is None


def test_vacancy_required_args_includes_created_at_for_recency_phrasing():
    args = _vacancy_required_args("việc làm gần nhất")
    assert args["sort_by"] == "created_at"
    assert args["top_k"] == 10


def test_vacancy_required_args_prefers_salary_when_both_present():
    # Salary takes precedence in _vacancy_required_args (checked first).
    args = _vacancy_required_args("việc lương cao nhất gần nhất")
    assert args["sort_by"] == "salary_desc"


def test_vacancy_required_args_omits_sort_by_when_no_intent():
    args = _vacancy_required_args("cho tôi xem danh sách việc làm")
    assert "sort_by" not in args
