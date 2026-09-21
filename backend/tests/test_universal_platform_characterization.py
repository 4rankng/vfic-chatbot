"""Migration oracles for the current non-universal runtime.

These tests intentionally describe behavior that later universal-platform
phases must remove. They do not endorse the fallback behavior.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import knowledge as knowledge_api
from app.graph.ports import TurnDecisions
from app.graph.router import route_from_decisions
from app.graph.context import build_system_prompt
from app.models.knowledge import KBVersionStatus
from app.graph.types import BotRunState
from app.services.ingestion.template_compiler import compile_template
from app.services.ingestion.template_service import TemplateService
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
REQUIRED_BEHAVIORAL_BASELINES = {
    "test_graph_decisions.py": ("test_", "route_from_decisions"),
    "test_graph_runner_turn.py": ("test_", "run_turn"),
    "test_graph_factories.py": ("test_build_deps_wires_graphdeps",),
    "test_lead_extraction.py": ("CandidateExtractionService",),
    "test_job_availability.py": ("vacancy",),
    "test_proactive_followup_rules.py": ("followup",),
    "test_dashboard_attention.py": ("Dashboard",),
}


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
    artifact, checksum = compile_template(built["template"])
    assert artifact["record_types"]
    assert len(checksum) == 64
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
    assert route.tools == ("search_bus_timetable",)


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
async def test_template_resolution_requires_an_explicit_assignment():
    service = TemplateService(object())  # type: ignore[arg-type]
    service.current_assignment = AsyncMock(return_value=None)  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="explicit published"):
        await service.pinned_version_for_project(
            uuid.UUID("00000000-0000-0000-0000-000000000001")
        )


@pytest.mark.asyncio
async def test_knowledge_version_creation_is_template_free(monkeypatch):
    project_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    actor_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    version = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=project_id,
        release_manifest_sha256=None,
        version_no=1,
        status=KBVersionStatus.DRAFT,
        created_by=actor_id,
        created_at=datetime.now(timezone.utc),
        published_at=None,
        error_message=None,
    )

    class PlainKnowledgeService:
        def __init__(self, _db: object) -> None:
            pass

        async def create_version(self, _project_id: uuid.UUID, *, actor: object) -> object:
            assert _project_id == project_id
            assert actor.id == actor_id
            return version

    audit_payloads: list[dict] = []

    async def record_audit(_db: object, **kwargs: object) -> None:
        audit_payloads.append(kwargs["payload"])

    class Database:
        async def commit(self) -> None:
            return None

    monkeypatch.setattr(knowledge_api, "KnowledgeService", PlainKnowledgeService)
    monkeypatch.setattr(knowledge_api, "record_audit", record_audit)

    result = await knowledge_api.create_kb_version(
        project_id,
        admin=SimpleNamespace(id=actor_id),
        db=Database(),
    )

    assert "template_version_id" not in result.model_dump()
    assert audit_payloads == [{"project_id": str(project_id)}]


@pytest.mark.asyncio
async def test_current_system_prompt_uses_database_persona_but_appends_recruitment_rules(
    monkeypatch: pytest.MonkeyPatch,
):
    async def uncached(assemble, *, key_suffix="default"):
        assert key_suffix == "zalo_bot"
        return await assemble(), False

    retrieval = SimpleNamespace(
        active_persona_body=AsyncMock(return_value="Neutral configured persona"),
        active_projects_with_card=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("app.graph.context.cached_system_prompt", uncached)

    prompt, cache_hit = await build_system_prompt(retrieval, provider="zalo_bot")

    assert prompt.startswith("Neutral configured persona")
    assert "đang tuyển" in prompt
    assert "search_knowledge" in prompt
    assert "danh mục Job có cấu trúc đang trống" in prompt
    assert "không được suy ra tình trạng tuyển dụng từ danh mục dự án" in prompt.lower()
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

    retrieval = SimpleNamespace(
        active_persona_body=AsyncMock(return_value="Persona giới thiệu VFIC."),
        active_projects_with_card=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("app.graph.context.cached_system_prompt", uncached)

    prompt, _ = await build_system_prompt(retrieval)

    # Carve-out present: company-identity questions may use the persona.
    assert "CHÍNH VFIC" in prompt
    assert "không cần gọi search_knowledge" in prompt.lower()
    # Grounding rule preserved alongside the carve-out (regression guard).
    assert "không được suy ra tình trạng tuyển dụng" in prompt.lower()


def test_template_service_source_contains_no_automatic_recruitment_fallback():
    source = (
        Path(__file__).parents[1]
        / "app"
        / "services"
        / "ingestion"
        / "template_service.py"
    ).read_text(encoding="utf-8")

    assert "ensure_builtin_recruitment" not in source
    assert "recruitment_factory_builtin" not in source


def test_required_recruitment_behavioral_baselines_are_present_and_selected():
    tests_dir = Path(__file__).parent
    for file_name, required_markers in REQUIRED_BEHAVIORAL_BASELINES.items():
        source = (tests_dir / file_name).read_text(encoding="utf-8")
        assert all(marker in source for marker in required_markers), file_name
