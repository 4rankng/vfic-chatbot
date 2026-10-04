"""Migration oracles for the current non-universal runtime.

These tests intentionally describe behavior that later universal-platform
phases must remove. They do not endorse the fallback behavior.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.graph.ports import TurnDecisions
from app.graph.router import route_from_decisions
from app.graph.context import build_system_prompt
from app.graph.types import BotRunState
from app.services.knowledge.pipeline import KnowledgePipeline, _fallback_unit
from tests.fixtures.universal_platform.factories import (
    empty_installation_fixture,
    installation_fixture,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "universal_platform"
FORBIDDEN_FIXTURE_TEXT = (
    "vfic",
    "lg display",
    "bot.tingting.vip",
    "admin@vfic.dev",
    "admin123",
    "recruitment_factory_builtin",
)
# The recruitment behaviour these oracles describe is only protected while the
# baseline suite that exercises it still runs in this lane. TEST-17 replaced
# the old "grep these marker strings inside those test files" pin with a real
# import: `importlib.import_module` returns the very module object pytest
# collected, so "the baseline is present and selected" is answered by the
# import graph instead of by the file's wording. A reworded docstring or a
# renamed local no longer fails here; a deleted, emptied, or renamed baseline
# still does.
REQUIRED_BEHAVIORAL_BASELINES: dict[str, tuple[str, ...]] = {
    # module stem -> production entry points the baseline must reach.
    "test_graph_decisions": ("route_from_decisions",),
    "test_graph_runner_turn": ("run_turn",),
    "test_graph_factories": ("build_deps",),
    "test_lead_extraction": ("CandidateExtractionService",),
    "test_dashboard_attention": ("AttentionDashboardOut",),
}
# Symbols the baseline reaches through a module object (`runner.run_turn`) or
# that live behind an alias; resolved against the owning module so the check is
# "this callable exists in production", not "this word appears in a test file".
_RESOLVED_IN_PRODUCTION = {
    "run_turn": "app.graph.runner",
    "build_deps": "app.graph.factories",
}


def _baseline_test_functions(module: ModuleType) -> list[str]:
    return [
        name
        for name, value in vars(module).items()
        if name.startswith("test_") and callable(value)
    ]


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "empty_installation.json",
        "recruitment_installation.json",
    ],
)
def test_universal_fixtures_are_explicit_and_contain_no_current_customer_data(name: str):
    raw = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    lowered = raw.casefold()

    assert not any(value in lowered for value in FORBIDDEN_FIXTURE_TEXT)
    assert "token" not in lowered
    assert "password" not in lowered
    assert "phone" not in lowered


def test_empty_installation_fixture_contains_no_business_configuration_or_rows():
    fixture = _load_fixture("empty_installation.json")

    assert fixture == empty_installation_fixture()


def test_recruitment_fixture_requires_explicit_identity_persona_template_and_capabilities():
    fixture = _load_fixture("recruitment_installation.json")
    built = installation_fixture(
        customer=fixture["customer"],
        pack=fixture["pack"],
        capabilities=fixture["capabilities"],
        persona=fixture["persona"],
        template=fixture["template"],
        golden_turns=fixture["golden_turns"],
        integrations=fixture["integrations"],
    )

    assert built["customer"]["display_name"]
    assert built["pack"] == "recruitment"
    assert built["capabilities"]
    assert built["persona"]["name"]
    assert built["persona"]["authority"] == "none"
    assert built["integrations"] == []


def test_installation_factory_has_no_implicit_business_defaults():
    with pytest.raises(TypeError):
        installation_fixture()  # type: ignore[call-arg]


def test_current_recruitment_router_is_a_migration_oracle_not_a_universal_router():
    route = route_from_decisions(
        "LG có xe đưa đón ca đêm mấy giờ?",
        TurnDecisions(intent="timetable", intent_confidence=0.99),
    )

    assert route.strategy == "structured_lookup"
    # The distance tool rides the timetable lane too: "từ A tới B" reads to the
    # classifier as a journey, so a distance question lands here (2026-10-03).
    assert route.tools == ("search_bus_timetable", "get_project_distance")


def test_explicit_recruitment_fixture_reproduces_current_route_and_tool_selection():
    fixture = _load_fixture("recruitment_installation.json")
    golden = next(item for item in fixture["golden_turns"] if item["kind"] == "route")

    route = route_from_decisions(
        golden["user_text"],
        TurnDecisions(intent="recommend", intent_confidence=0.94),
    )

    assert route.strategy == golden["expected_strategy"]
    assert list(route.tools) == golden["expected_tools"]


@pytest.mark.asyncio
async def test_explicit_recruitment_fixture_reproduces_grounded_vacancy_agent_path(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.graph import runner
    from tests.test_graph_runner_turn import _FakeConv, _FakeZalo, _deps, _stub_svc

    fixture = _load_fixture("recruitment_installation.json")
    golden = next(item for item in fixture["golden_turns"] if item["kind"] == "reply")

    async def _grounded_agent(_state, _deps, user_text, **_kwargs):
        assert user_text == golden["user_text"]
        return "Tôi sẽ kiểm tra các việc ACTIVE bằng công cụ tuyển dụng."

    monkeypatch.setattr(runner, "_agent_turn", _grounded_agent)
    conversation, _ = _stub_svc(conv=_FakeConv())
    sender = _FakeZalo()
    deps = _deps(sender, conversation=conversation)
    state = BotRunState(
        conversation_id="00000000-0000-0000-0000-000000000001",
        version_at_start=1,
        user_text=golden["user_text"],
    )

    result = await runner.run_turn(state, deps)

    assert golden["expected_reply_contract"] == "grounded_llm_tool_path"
    assert result == {
        "outcome": golden["expected_outcome"],
        "reply": "Tôi sẽ kiểm tra các việc ACTIVE bằng công cụ tuyển dụng.",
    }
    assert sender.sent == [
        ("z1", "Tôi sẽ kiểm tra các việc ACTIVE bằng công cụ tuyển dụng.")
    ]


def test_knowledge_fallback_keeps_only_source_context():
    unit = _fallback_unit("Lương cơ bản là 8 triệu đồng.", 0)

    assert unit["content"] == "Lương cơ bản là 8 triệu đồng."
    assert unit["questions"] == ["Thông tin này nói gì về thu nhập, giá hoặc hỗ trợ?"]


def test_digest_fallback_is_source_grounded_and_domain_neutral():
    pipeline = object.__new__(KnowledgePipeline)

    summary, units = pipeline._fallback_digest_section("Lương cơ bản là 8 triệu đồng.")

    assert summary == "Lương cơ bản là 8 triệu đồng."
    assert units[0]["source_quote"] == "Lương cơ bản là 8 triệu đồng."
    assert units[0]["content"] == "Lương cơ bản là 8 triệu đồng."


@pytest.mark.asyncio



@pytest.mark.asyncio
async def test_current_system_prompt_uses_the_code_persona_and_appends_recruitment_rules(
    monkeypatch: pytest.MonkeyPatch,
):
    async def uncached(assemble, *, key_suffix="default"):
        from app.graph.context import _PROMPT_TEXT_REVISION

        assert key_suffix == f"zalo_bot:r{_PROMPT_TEXT_REVISION}"
        return await assemble(), False

    # No persona method on the retrieval port at all: the persona is a code
    # constant, so the lane that would have fetched it no longer has one.
    retrieval = SimpleNamespace(active_projects_with_card=AsyncMock(return_value=[]))
    monkeypatch.setattr("app.graph.context.cached_system_prompt", uncached)

    prompt, cache_hit = await build_system_prompt(retrieval, provider="zalo_bot")

    from app.graph.prompts import AGENT_SYSTEM_PROMPT

    assert prompt.startswith(AGENT_SYSTEM_PROMPT)
    assert "đang tuyển" in prompt
    assert "search_knowledge" in prompt
    assert "list_active_projects là nguồn kiểm tra" in prompt
    assert "Không bắt phải có vị trí Job riêng" in prompt
    assert "không được suy ra tình trạng tuyển dụng từ danh mục tên" in prompt.lower()
    assert "NGỮ CẢNH RIÊNG TƯ" in prompt
    assert cache_hit is False


@pytest.mark.asyncio
async def test_system_prompt_allows_company_identity_from_persona_without_tool_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    """Meta questions about VFIC-the-company (province, address, who we are) must
    be answerable from the persona intro. Grounding rules forbid inferring job
    facts without KB evidence, but those rules over-fired on company-identity
    questions, producing the generic "chưa thể xác minh" fallback. The carve-out
    coexists with — never weakens — the recruitment-grounding rule.
    """

    async def uncached(assemble, *, key_suffix="default"):
        return await assemble(), False

    retrieval = SimpleNamespace(active_projects_with_card=AsyncMock(return_value=[]))
    monkeypatch.setattr("app.graph.context.cached_system_prompt", uncached)

    prompt, _ = await build_system_prompt(retrieval)

    # Carve-out present: company-identity questions may use the persona.
    assert "CHÍNH VFIC" in prompt
    assert "không cần gọi search_knowledge" in prompt.lower()
    # Grounding rule preserved alongside the carve-out (regression guard).
    assert "không được suy ra tình trạng tuyển dụng" in prompt.lower()


def test_required_recruitment_behavioral_baselines_are_present_and_selected():
    """Every recruitment baseline is importable, non-empty, and reaches its entry point.

    The previous version read each baseline's source and asserted marker
    substrings, so rewording a docstring or renaming a local broke an unrelated
    oracle. This imports the module pytest actually collected and checks three
    things instead: it is importable under `tests.` (so it is part of the unit
    lane, not an uncollected file), it still declares tests, and the production
    entry point it is meant to guard still exists and is callable.
    """
    for module_name, entry_points in REQUIRED_BEHAVIORAL_BASELINES.items():
        baseline = importlib.import_module(f"tests.{module_name}")

        assert _baseline_test_functions(baseline), f"{module_name} declares no tests"

        for entry_point in entry_points:
            owner = _RESOLVED_IN_PRODUCTION.get(entry_point)
            if owner is not None:
                target = getattr(importlib.import_module(owner), entry_point)
            else:
                assert entry_point in vars(baseline), (
                    f"{module_name} no longer references {entry_point}"
                )
                target = vars(baseline)[entry_point]
            assert callable(target), f"{module_name}: {entry_point} is not callable"
