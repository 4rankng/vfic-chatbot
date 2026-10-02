"""Detect candidate-facing replies that assert a project absence unverified.

The catalog tool (``list_active_projects``) is the matching authority for
"does any project work at X?". A reply asserting the opposite — "chưa có dự án
nào ở X" — on a turn that never ran that tool can ship a confident false
negative: the catalog card may carry only the city, the KB search may miss the
industrial park, and the candidate is told no project exists where one is live.
This module is detection-only: the agent lane in ``lanes.py`` turns a detected,
unevidenced absence into one forced catalog self-check, and ships the
model-authored hedge when the check agrees.
"""

from __future__ import annotations

import os
import re

from app.shared.domain.text import normalize_vietnamese_text

# Routes whose answers may legitimately state project existence. Timetable,
# profile, support, and small-talk turns never assert it.
GUARD_INTENTS: frozenset[str] = frozenset({"general", "recommend", "faq_detail"})

# ASCII-folded "chưa có / không có" followed by a project-unit noun. The noun
# set is the load-bearing precision device: feature absences about one project
# ("AMTRAN chưa có ký túc xá"), bus routes ("chưa có tuyến xe"), and KB
# coverage ("chưa có thông tin") must not match — only the existence of
# project units counts as a claim this guard needs verified.
_ABSENCE_RE = re.compile(
    r"\b(?:chua|khong) co (?:du an|nha may|cong ty|khu cong nghiep)\b"
)

# The hedge opening the retry hint prescribes; a reply carrying it is the
# guard's own product and is never re-checked.
_HEDGE_MARKER = "theo du lieu hien tai"

_KILL_SWITCH_VALUES = {"0", "false", "no", "off"}


def enabled() -> bool:
    """Kill-switch: a Settings field when present, the env override otherwise."""
    from app.core.config import get_settings

    flag = getattr(get_settings(), "absence_guard_enabled", None)
    if flag is not None:
        return bool(flag)
    return os.getenv("ABSENCE_GUARD_ENABLED", "true").strip().lower() not in (
        _KILL_SWITCH_VALUES
    )


def reply_asserts_place_absence(reply: str) -> bool:
    """Whether ``reply`` asserts that no project exists at some place/company."""
    normalized = normalize_vietnamese_text(reply or "")
    if _HEDGE_MARKER in normalized:
        return False
    return _ABSENCE_RE.search(normalized) is not None


def is_hedge_form(reply: str) -> bool:
    """Whether ``reply`` opens with the guard's prescribed hedge."""
    return _HEDGE_MARKER in normalize_vietnamese_text(reply or "")


def catalog_evidence_this_turn(timings: dict | None) -> bool:
    """Whether this turn already ran the catalog tool.

    Prefetch routes never run the catalog, so the dispatch counters are the
    complete signal. ``tool_breakdown`` (per-tool milliseconds, keyed only for
    tools that actually dispatched) is accepted too, so an agent that predates
    the counters still counts as evidence.
    """
    if not timings:
        return False
    counts = timings.get("tool_call_counts") or {}
    if int(counts.get("list_active_projects") or 0) > 0:
        return True
    return "list_active_projects" in (timings.get("tool_breakdown") or {})


def build_retry_kwargs(agent_kwargs: dict) -> dict:
    """Re-arm one agent call as a forced catalog self-check.

    Focus is lifted for exactly this call: dropping ``forced_project_slug``
    un-blocks the catalog dispatch and un-scopes the knowledge search, while
    the stored conversation focus stays untouched. Streaming hooks are dropped
    — the retry must never append to a live progressive stream.
    """
    kwargs = dict(agent_kwargs)
    kwargs.pop("forced_project_slug", None)
    kwargs.pop("on_delta", None)
    kwargs.pop("on_evidence", None)
    kwargs["allowed_tools"] = ("list_active_projects", "search_knowledge")
    kwargs["required_tool"] = "list_active_projects"
    kwargs["required_tool_args"] = None
    return kwargs


def _hotline_tail(hotline: str) -> str:
    return f"gọi hotline {hotline}" if hotline else "gọi hotline của bên em"


def retry_route_hint(hotline: str) -> str:
    """Mandatory instruction for the self-check round; the model authors the reply."""
    return (
        "LƯU Ý BẮT BUỘC: bản nháp trước đó khẳng định \"chưa có dự án ...\" "
        "trong khi lượt này CHƯA tra danh mục dự án — không được gửi bản nháp đó. "
        "Trước hết hãy gọi list_active_projects (lượt này được tra toàn bộ các "
        "dự án); nếu danh mục không cho thấy khu vực ứng viên hỏi, gọi thêm "
        "search_knowledge (KHÔNG truyền project_slug) với từ khóa khu vực/công ty "
        "đó. Nếu có dự án phù hợp: giới thiệu theo dữ liệu vừa tra, không nhắc "
        "lại câu trả lời sai. Nếu quả thật không có dự án nào: trả lời mở đầu "
        "\"Theo dữ liệu hiện tại em chưa tìm thấy dự án nào ...\" và mời ứng viên "
        f"{_hotline_tail(hotline)} để chuyên viên hỗ trợ thêm; không hứa gọi "
        "lại, không bịa số."
    )


def hedge_route_hint(hotline: str) -> str:
    """Mandatory hedge instruction for the tool-free fallback round."""
    return (
        "LƯU Ý BẮT BUỘC: không được khẳng định \"chưa có dự án ...\" khi chưa có "
        "dữ liệu tra cứu. Hãy trả lời mở đầu \"Theo dữ liệu hiện tại em chưa tìm "
        "thấy dự án nào ...\" và mời ứng viên "
        f"{_hotline_tail(hotline)} để chuyên viên hỗ trợ thêm; không hứa gọi "
        "lại, không bịa số."
    )
