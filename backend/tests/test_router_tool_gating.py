"""Tool-gating: the router's hard gate on which tools the LLM may bind.

Phase 1 wires ``TurnRoute.tools`` into the agent's ``bind_tools`` call so a confident
route constrains the LLM's decision surface. These tests pin:

* ``filter_tool_schemas`` returns the routed subset + the always-available safety floor.
* Low-confidence / un-routed turns fall back to the full registry.
* A routed turn never exposes tools outside its lane (the core determinism guarantee).
* ``MiniMaxAgent.agent`` forwards ``allowed_tools`` to ``bind_tools`` (requires langchain).
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.graph.router import route_turn
from app.graph.schemas import (
    _ALWAYS_AVAILABLE,
    ROUTE_CONFIDENCE_FLOOR,
    TOOL_SCHEMAS,
    filter_tool_schemas,
)

_ALL_TOOL_NAMES = {s["function"]["name"] for s in TOOL_SCHEMAS}


# --- filter_tool_schemas -----------------------------------------------------


def test_filter_none_returns_full_registry():
    """No route → full toolset (current pre-routing behavior)."""
    assert filter_tool_schemas(None) == TOOL_SCHEMAS
    assert filter_tool_schemas(()) == TOOL_SCHEMAS


def test_filter_always_includes_safety_floor():
    """Even a tightly-routed turn can still call the safety-floor tools."""
    for routed in [("search_bus_timetable",), ("recommend_projects",), ("get_product_features",)]:
        names = {s["function"]["name"] for s in filter_tool_schemas(routed)}
        assert _ALWAYS_AVAILABLE <= names, f"safety floor missing for route {routed}"


def test_filter_timetable_route_excludes_recommend():
    """A timetable turn must never see recommend_projects."""
    route = route_turn("LG có xe đưa đón ca đêm mấy giờ?")
    assert route.confidence >= ROUTE_CONFIDENCE_FLOOR
    names = {s["function"]["name"] for s in filter_tool_schemas(route.tools)}
    assert "search_bus_timetable" in names
    assert "recommend_projects" not in names
    assert "get_product_features" not in names


def test_filter_recommend_route_excludes_timetable():
    """A recommend turn must never see search_bus_timetable."""
    route = route_turn("gợi ý việc phù hợp có ký túc xá")
    assert route.confidence >= ROUTE_CONFIDENCE_FLOOR
    names = {s["function"]["name"] for s in filter_tool_schemas(route.tools)}
    assert "recommend_projects" in names
    assert "get_product_features" in names
    assert "search_bus_timetable" not in names


def test_filter_unknown_tool_name_is_ignored_silently():
    """A future/typo tool name must not crash the filter."""
    names = {s["function"]["name"] for s in filter_tool_schemas(("recommend_projects", "no_such_tool"))}
    assert "recommend_projects" in names
    assert "no_such_tool" not in names


# --- confidence floor → full registry ---------------------------------------


def test_low_confidence_route_falls_back_to_full_toolset():
    """An uncertain route (confidence < floor) must not constrain the agent.

    The runner derives ``allowed_tools = route.tools if confidence >= floor else None``.
    Here we pin that the general/fallback route (conf 0.45) is below the floor and
    that ``filter_tool_schemas(None)`` yields the full registry.
    """
    route = route_turn("hôm nay thế nào")  # no recruitment signal → general fallback
    assert route.confidence < ROUTE_CONFIDENCE_FLOOR
    # The runner would pass allowed_tools=None here → full toolset.
    assert filter_tool_schemas(None) == TOOL_SCHEMAS


# --- MiniMaxAgent.agent forwards allowed_tools to bind_tools -----------------


class _RecordingLLM:
    """Captures the tool list handed to bind_tools and returns a no-tool final reply."""

    def __init__(self) -> None:
        self.bound_names: set[str] | None = None

    def bind_tools(self, tools):
        self.bound_names = {t["function"]["name"] for t in tools}
        return self

    async def ainvoke(self, messages, **kwargs):
        return SimpleNamespace(content="ok", tool_calls=None)


async def test_agent_passes_allowed_tools_to_bind_tools(monkeypatch):
    """MiniMaxAgent.agent must forward allowed_tools so a routed turn binds only its lane."""
    pytest.importorskip("langchain_core")  # agent imports langchain at call time
    from app.graph.clients import MiniMaxAgent

    recording = _RecordingLLM()
    agent = MiniMaxAgent(recording, embedder=None, max_iters=1)

    # A timetable route: only search_bus_timetable + the safety floor.
    await agent.agent(
        "xe đưa đón ca đêm",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("search_bus_timetable",),
    )

    assert recording.bound_names is not None
    assert "search_bus_timetable" in recording.bound_names
    assert "recommend_projects" not in recording.bound_names
    assert "get_product_features" not in recording.bound_names
    # Safety floor is always present.
    assert _ALWAYS_AVAILABLE <= recording.bound_names


async def test_agent_without_allowed_tools_binds_full_registry():
    """No allowed_tools → full TOOL_SCHEMAS (the pre-routing default)."""
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    recording = _RecordingLLM()
    agent = MiniMaxAgent(recording, embedder=None, max_iters=1)

    await agent.agent("hello", system="sys", retrieval=object(), embedder=None)

    assert recording.bound_names == _ALL_TOOL_NAMES
