"""Unit tests for the unevidenced-absence detector (app.graph.absence_guard)."""

from __future__ import annotations

import pytest

from app.graph.absence_guard import (
    GUARD_INTENTS,
    build_retry_kwargs,
    catalog_evidence_this_turn,
    enabled,
    hedge_route_hint,
    is_hedge_form,
    reply_asserts_place_absence,
    retry_route_hint,
)

pytestmark = pytest.mark.timeout(30)


# --- detector: fires on project-existence absences ---------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Dạ, hiện tại chưa có dự án nào làm việc tại VSIP ạ.",
        "Bên em không có nhà máy nào ở KCN VSIP.",
        "Tại VSIP hiện chưa có dự án nào ạ.",
        "chưa có công ty nào thuộc VSIP đang tuyển ạ.",
        "Hiện chưa có khu công nghiệp nào bên em hoạt động ở đó ạ.",
    ],
)
def test_fires_on_project_existence_absences(reply: str) -> None:
    assert reply_asserts_place_absence(reply) is True


# --- detector: stays silent on absences it must not claim --------------------


@pytest.mark.parametrize(
    "reply",
    [
        "AMTRAN chưa có ký túc xá ạ.",
        "AMTRAN chưa có xưởng nhựa ạ.",
        "Chưa có thông tin về lương tại VSIP ạ.",
        "Chưa có tuyến xe tới VSIP ạ.",
        "Chưa có việc nào ở AMTRAN hiện tại ạ.",
        "Theo dữ liệu hiện tại em chưa tìm thấy dự án nào ở VSIP ạ.",
        "",
    ],
)
def test_stays_silent_on_non_existence_absences(reply: str) -> None:
    assert reply_asserts_place_absence(reply) is False


def test_hedge_form_and_guard_intents() -> None:
    assert is_hedge_form(
        "Theo dữ liệu hiện tại em chưa tìm thấy dự án nào ở VSIP ạ."
    )
    assert is_hedge_form("Dạ anh/chị ơi") is False
    assert GUARD_INTENTS == frozenset({"general", "recommend", "faq_detail"})


# --- catalog-evidence signal --------------------------------------------------


@pytest.mark.parametrize(
    ("timings", "expected"),
    [
        (None, False),
        ({}, False),
        ({"tool_call_counts": {}}, False),
        ({"tool_call_counts": {"search_knowledge": 2}}, False),
        ({"tool_call_counts": {"list_active_projects": 1}}, True),
        ({"tool_breakdown": {"list_active_projects": 186}}, True),
        ({"tool_breakdown": {"search_knowledge": 1161}}, False),
    ],
)
def test_catalog_evidence_this_turn(
    timings: dict | None, expected: bool
) -> None:
    assert catalog_evidence_this_turn(timings) is expected


# --- retry kwargs surgery -----------------------------------------------------


def test_build_retry_kwargs_lifts_focus_and_forces_catalog() -> None:
    kwargs = {
        "system": "sys",
        "retrieval": object(),
        "embedder": None,
        "allowed_tools": ("search_knowledge",),
        "use_fast": False,
        "make_retrieval": None,
        "lookup_query": "gần núi đèo là vsip chứ",
        "metrics": {"tool_calls": 2},
        "forced_project_slug": "lg-display",
        "on_delta": lambda *_: None,
        "on_evidence": lambda *_: None,
        "resolved_tool_registry": frozenset({"list_active_projects"}),
    }

    retry = build_retry_kwargs(kwargs)

    assert "forced_project_slug" not in retry
    assert "on_delta" not in retry
    assert "on_evidence" not in retry
    assert retry["allowed_tools"] == ("list_active_projects", "search_knowledge")
    assert retry["required_tool"] == "list_active_projects"
    assert retry["required_tool_args"] is None
    # The original turn kwargs stay untouched.
    assert kwargs["allowed_tools"] == ("search_knowledge",)
    assert kwargs["forced_project_slug"] == "lg-display"
    # Shared keys ride along unchanged (metrics stays the same dict).
    assert retry["metrics"] is kwargs["metrics"]
    assert retry["system"] == "sys"


# --- hints --------------------------------------------------------------------


def test_retry_route_hint_carries_hotline_and_instructions() -> None:
    hint = retry_route_hint("1800 7228")
    assert "list_active_projects" in hint
    assert "search_knowledge" in hint
    assert "hotline 1800 7228" in hint
    assert "Theo dữ liệu hiện tại" in hint


def test_retry_route_hint_degrades_without_a_hotline() -> None:
    hint = retry_route_hint("")
    assert "hotline của bên em" in hint
    assert "hotline 1800" not in hint


def test_hedge_route_hint_mentions_hotline() -> None:
    assert "hotline 0914 827 988" in hedge_route_hint("0914 827 988")


# --- kill-switch --------------------------------------------------------------


def test_enabled_defaults_on_and_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABSENCE_GUARD_ENABLED", raising=False)

    class _SettingsWithoutFlag:
        pass

    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: _SettingsWithoutFlag()
    )
    assert enabled() is True

    monkeypatch.setenv("ABSENCE_GUARD_ENABLED", "false")
    assert enabled() is False
    monkeypatch.setenv("ABSENCE_GUARD_ENABLED", "0")
    assert enabled() is False

    monkeypatch.setenv("ABSENCE_GUARD_ENABLED", "true")
    assert enabled() is True


def test_enabled_prefers_the_settings_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SettingsWithFlag:
        absence_guard_enabled = False

    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: _SettingsWithFlag()
    )
    monkeypatch.setenv("ABSENCE_GUARD_ENABLED", "true")
    assert enabled() is False
