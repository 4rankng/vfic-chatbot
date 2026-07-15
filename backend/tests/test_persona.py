"""Structural guard for the VFIC agent persona (persona.md).

The persona is hand-edited and config-driven (loaded from persona.md at import).
These tests guard against accidental deletion/corruption of persona.md and verify
the core operational rules survive any restructure. The persona was trimmed from
a verbose 7-section/9.3KB format to a dense ~3KB format — the section count is no
longer fixed, but every operational rule must remain present.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.graph.context import active_projects_index
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.schemas.personas import (
    PersonaFollowupRule,
    PersonaFollowupRules,
    PersonaUpdate,
    default_followup_rules_dict,
)
from app.services.errors import NotFoundError
from app.services.persona_service import PersonaService

# Operational rules that must survive any persona restructure. Each is a
# behavior the agent must follow — losing any of these changes the bot's
# product behavior in a way the dashboard/conversion metrics depend on.
CRITICAL_RULES = [
    "MỘT TIN NHẮN - MỘT CÂU HỎI",  # one-question-per-message cadence
    "Tra cứu lịch xe structured",  # bus-timetable structured-tool-first rule
    "CHỐNG ẢO GIÁC",  # anti-hallucination / no fabrication beyond data
    "tiếng Việt",  # Vietnamese-only
    "KHÔNG dùng Markdown",  # plain-text output format
]


def test_persona_loads_non_empty():
    assert AGENT_SYSTEM_PROMPT, "persona.md loaded empty"
    # The trimmed persona is ~2.5-3.5KB. This floor catches corruption
    # (empty/truncated file) without forcing a specific verbosity.
    assert len(AGENT_SYSTEM_PROMPT) > 1500


def test_persona_has_core_sections():
    """The persona must cover role, communication rules, tools, and limits.

    Section headers are flexible (the persona was restructured from a rigid
    7-part template), but these topics must all appear.
    """
    topics = [
        "Vai trò",  # who the bot is
        "Nguyên tắc giao tiếp",  # communication rules
        "Dùng tool",  # tool-usage rules
        "Tránh",  # what to avoid (hallucination, off-topic)
    ]
    for topic in topics:
        assert topic in AGENT_SYSTEM_PROMPT, f"persona missing topic: {topic!r}"


def test_persona_preserves_critical_rules():
    for needle in CRITICAL_RULES:
        assert needle in AGENT_SYSTEM_PROMPT, f"missing critical rule text: {needle!r}"


def test_persona_followup_rule_defaults_match_product_spec():
    rules = default_followup_rules_dict()

    assert rules["hot"] == {
        "enabled": True,
        "cadence_hours": [10, 22, 46],
        "eligible_stages": ["NEW"],
    }
    assert rules["warm"] == {
        "enabled": True,
        "cadence_hours": [22, 46],
        "eligible_stages": ["NEW"],
    }
    assert rules["not_interested"] == {
        "enabled": True,
        "cadence_hours": [46],
        "eligible_stages": ["NEW"],
    }


def test_persona_followup_rule_rejects_unsafe_cadence():
    with pytest.raises(ValidationError):
        PersonaFollowupRule(cadence_hours=[22, 10])

    with pytest.raises(ValidationError):
        PersonaFollowupRule(cadence_hours=[0])

    with pytest.raises(ValidationError):
        PersonaFollowupRule(cadence_hours=[48])

    with pytest.raises(ValidationError):
        PersonaFollowupRule(cadence_hours=[1, 2, 3, 4])

    with pytest.raises(ValidationError):
        PersonaFollowupRule(enabled=True, cadence_hours=[])

    assert PersonaFollowupRule(enabled=False, cadence_hours=[]).cadence_hours == []


def test_explicit_neutral_followup_policy_has_no_recruitment_stage_fallback():
    neutral = PersonaFollowupRules.model_validate(
        {
            score: {"enabled": False, "cadence_hours": [], "eligible_stages": []}
            for score in ("hot", "warm", "not_interested")
        }
    )

    for score in ("hot", "warm", "not_interested"):
        rule = getattr(neutral, score)
        assert rule.enabled is False
        assert rule.cadence_hours == []
        assert rule.eligible_stages == []


def test_enabled_followup_rule_still_requires_an_eligible_stage():
    with pytest.raises(ValidationError):
        PersonaFollowupRule(enabled=True, cadence_hours=[10], eligible_stages=[])


def test_neutral_policy_does_not_change_legacy_persona_defaults():
    assert default_followup_rules_dict() == {
        "hot": {
            "enabled": True,
            "cadence_hours": [10, 22, 46],
            "eligible_stages": ["NEW"],
        },
        "warm": {
            "enabled": True,
            "cadence_hours": [22, 46],
            "eligible_stages": ["NEW"],
        },
        "not_interested": {
            "enabled": True,
            "cadence_hours": [46],
            "eligible_stages": ["NEW"],
        },
    }


@pytest.mark.asyncio
async def test_active_projects_index_includes_project_persona_overrides():
    class _Repo:
        async def active_projects_with_card(self):
            return [
                SimpleNamespace(
                    slug="lg-display",
                    name="LG Display",
                    summary="Tuyển công nhân sản xuất",
                    index_card={"key_roles": ["Operator"], "location": "Hai Phong"},
                    persona_name="Persona LGD",
                    persona_body_md="### Vai trò\nTư vấn riêng cho LG Display.",
                )
            ]

    prompt = await active_projects_index(_Repo())

    assert "=== DANH MỤC SẢN PHẨM/DỰ ÁN ĐANG HOẠT ĐỘNG ===" in prompt
    assert "lg-display (LG Display)" in prompt
    assert "=== PERSONA RIÊNG THEO DỰ ÁN ===" in prompt
    assert "Slug: lg-display" in prompt
    assert "Agent: Persona LGD" in prompt
    assert "Tư vấn riêng cho LG Display." in prompt


@pytest.mark.asyncio
async def test_persona_service_update_returns_404_for_missing_id():
    """PersonaService.update raises NotFoundError when persona not found."""
    mock_db = AsyncMock()
    mock_db.get.return_value = None

    svc = PersonaService(mock_db)
    admin = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(NotFoundError):
        await svc.update(uuid.uuid4(), PersonaUpdate(), admin)
