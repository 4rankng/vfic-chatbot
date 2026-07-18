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
    assert "list_active_jobs" in names
    assert "get_product_features" in names
    assert "search_bus_timetable" not in names


def test_job_advisory_registry_can_bind_active_job_listing_only_when_enabled():
    enabled = {
        schema["function"]["name"]
        for schema in filter_tool_schemas(
            ("list_active_jobs",), resolved_registry=frozenset({"list_active_jobs"})
        )
    }
    disabled = {
        schema["function"]["name"]
        for schema in filter_tool_schemas(
            ("list_active_jobs",), resolved_registry=frozenset({"search_knowledge"})
        )
    }

    assert enabled == {"list_active_jobs"}
    assert disabled == set()


def test_filter_unknown_tool_name_is_ignored_silently():
    """A future/typo tool name must not crash the filter."""
    names = {
        s["function"]["name"] for s in filter_tool_schemas(("recommend_projects", "no_such_tool"))
    }
    assert "recommend_projects" in names
    assert "no_such_tool" not in names


def test_resolved_registry_is_an_exact_tool_boundary_without_legacy_safety_floor():
    names = {
        schema["function"]["name"]
        for schema in filter_tool_schemas(
            None,
            resolved_registry=frozenset({"search_knowledge"}),
        )
    }

    assert names == {"search_knowledge"}


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


class _RequiredToolLLM:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.tool_choices: list[str | None] = []

    def bind_tools(self, tools, *, tool_choice=None):
        self.tool_choices.append(tool_choice)
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        return next(self.responses)


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


async def test_vacancy_knowledge_route_prefetches_evidence_for_llm(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    query = (
        "mình nhà ở quán toan _hp gần IG tràng duệ."
        "bên IG tràng duệ mình đang tuyển ạ"
    )
    evidence = "LG Display Tràng Duệ đang tuyển công nhân sản xuất."

    async def _search(retrieval, embedder, name, args, **kwargs):  # noqa: ARG001
        assert name == "search_knowledge"
        assert args == {"query": query}
        return evidence

    class _KnowledgeLLM(_RecordingLLM):
        def __init__(self) -> None:
            super().__init__()
            self.messages = []

        async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
            self.messages = messages
            return SimpleNamespace(content="LG Display Tràng Duệ đang tuyển.", tool_calls=None)

    monkeypatch.setattr("app.graph.clients._dispatch_tool", _search)
    llm = _KnowledgeLLM()

    result = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        query,
        system="sys",
        retrieval=object(),
        embedder=object(),
        allowed_tools=("search_knowledge",),
        lookup_query=query,
    )

    assert result == "LG Display Tràng Duệ đang tuyển."
    assert any(evidence in str(message.content) for message in llm.messages)
    assert llm.bound_names is None


async def test_required_vacancy_tool_uses_forced_args_then_renders_evidence():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    job_id = "11111111-1111-4111-8111-111111111111"
    llm = _RequiredToolLLM(
        [
            SimpleNamespace(
                content="",
                tool_calls=[
                    {
                        "name": "list_active_jobs",
                        "args": {"company": "hallucinated filter"},
                        "id": "call-1",
                    }
                ],
            ),
            SimpleNamespace(content="Bịa lương 30 triệu", tool_calls=None),
            SimpleNamespace(
                content="LG Display tuyển công nhân sản xuất, lương 10-14 triệu.",
                tool_calls=None,
            ),
        ]
    )

    class _Repo:
        received: dict | None = None

        async def list_active_jobs(self, **kwargs):
            self.received = kwargs
            return SimpleNamespace(
                status="matched",
                jobs=(
                    SimpleNamespace(
                        id=job_id,
                        title="Công nhân sản xuất",
                        company_name="LG Display",
                        factory_name="Tràng Duệ",
                        project_name="LG Display",
                        project_slug="lg-display",
                        province="Hải Phòng",
                        district="An Dương",
                        salary_min=10_000_000,
                        salary_max=14_000_000,
                        vacancy_count=20,
                    ),
                ),
            )

    repo = _Repo()
    result = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "giới thiệu các vị trí đang tuyển",
        system="sys",
        retrieval=repo,
        embedder=None,
        allowed_tools=("list_active_jobs",),
        required_tool="list_active_jobs",
        required_tool_args={"top_k": 10},
    )

    assert llm.tool_choices == ["list_active_jobs", None]
    assert result == "LG Display tuyển công nhân sản xuất, lương 10-14 triệu."
    assert repo.received == {
        "project_slug": None,
        "role": None,
        "company": None,
        "location": None,
        "top_k": 10,
    }


async def test_required_vacancy_tool_skip_fails_closed():
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    llm = _RequiredToolLLM(
        [
            SimpleNamespace(content="LG đang tuyển", tool_calls=None),
            SimpleNamespace(content="Chưa thể kiểm tra tuyển dụng.", tool_calls=None),
        ]
    )
    result = await MiniMaxAgent(llm, embedder=None, max_iters=1).agent(
        "LG đang tuyển gì?",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("list_active_jobs",),
        required_tool="list_active_jobs",
    )

    assert llm.tool_choices == ["list_active_jobs"]
    assert "chưa thể kiểm tra" in result.lower()


async def test_required_vacancy_tool_dispatch_error_fails_closed(monkeypatch):
    pytest.importorskip("langchain_core")
    from app.graph.clients import MiniMaxAgent

    async def _dispatch_error(*args, **kwargs):  # noqa: ARG001
        return "Lỗi khi gọi tool 'list_active_jobs': database unavailable"

    monkeypatch.setattr("app.graph.clients._dispatch_tool", _dispatch_error)

    llm = _RequiredToolLLM(
        [
            SimpleNamespace(
                content="",
                tool_calls=[{"name": "list_active_jobs", "args": {}, "id": "call-1"}],
            ),
            SimpleNamespace(content="Chưa thể kiểm tra tuyển dụng.", tool_calls=None),
        ]
    )

    result = await MiniMaxAgent(llm, embedder=None, max_iters=2).agent(
        "giới thiệu các vị trí đang tuyển",
        system="sys",
        retrieval=object(),
        embedder=None,
        allowed_tools=("list_active_jobs",),
        required_tool="list_active_jobs",
    )

    assert "chưa thể kiểm tra" in result.lower()
