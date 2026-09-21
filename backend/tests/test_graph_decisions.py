"""Unit pins for the Jev-backed turn decision layer.

Covers the question taxonomy contract, the route-mapping policy, client
parsing (including degraded fallbacks), the template lane, and the Jev
integration settings contract. No network access: the client's
``_system_one`` is stubbed, mirroring how the graph tests fake the ports.
"""

from unittest.mock import AsyncMock, patch

from app.graph.decisions import (
    _INTENT_CRITERIA,
    JevDecisionClient,
    build_turn_questions,
)
from app.graph.fast_lane import template_for
from app.graph.ports import TurnDecisions
from app.graph.router import route_from_decisions, should_use_fast_model
from app.services.integration_settings import JevRuntimeConfig

_KEY = "test-key"
_MODEL = "jev-1.13.0"


def _client() -> JevDecisionClient:
    return JevDecisionClient(api_key=_KEY, model=_MODEL)


def _choice(value: str, confidence: float = 0.9) -> dict:
    return {
        "type": "choice",
        "choice": value,
        "probabilities": {value: confidence},
        "confidence": confidence,
    }


def _noul(value: float) -> dict:
    return {"type": "noul", "noul": value}


def _answers(**overrides) -> dict:
    answers = {
        "intent": _choice("faq_detail", 0.97),
        "vacancy_listing": _noul(0.02),
        "sort_by": _choice("none", 0.8),
        "pleasantry": _noul(0.01),
        "pleasantry_kind": _choice("none", 0.6),
        "recent_vacancy": _noul(0.01),
        "contact_info": _noul(0.01),
    }
    answers.update(overrides)
    return answers


def _payload(answers: dict) -> dict:
    return {
        "model": _MODEL,
        "answers": answers,
        "usage": {"input_tokens": 650, "output_tokens": 100},
    }


async def test_questions_match_contract() -> None:
    questions = build_turn_questions()
    assert set(questions) == {
        "intent",
        "vacancy_listing",
        "sort_by",
        "pleasantry",
        "pleasantry_kind",
        "recent_vacancy",
        "contact_info",
    }
    assert set(_INTENT_CRITERIA) == {
        "small_talk",
        "recommend",
        "profile_update",
        "timetable",
        "contact",
        "faq_detail",
        "out_of_scope",
        "general",
    }
    for question in questions.values():
        assert question["type"] in {"choice", "noul"}
        assert question["instructions"]
        criteria = question.get("criteria") or {}
        assert 0 < len(criteria) <= 255


async def test_route_pleasantry_wins_first() -> None:
    route = route_from_decisions("chào bạn", TurnDecisions(pleasantry=True, intent_confidence=0.95))
    assert route.intent == "small_talk"
    assert route.strategy == "template"
    assert route.reason == "fast_lane_match"


async def test_route_vacancy_listing_refines_recommend() -> None:
    decisions = TurnDecisions(
        intent="recommend",
        intent_confidence=0.94,
        vacancy_listing=True,
    )
    route = route_from_decisions("công ty còn tuyển không", decisions)
    assert route.strategy == "structured_lookup"
    assert route.tools == ("list_active_jobs",)
    assert route.reason == "vacancy_listing"


async def test_route_contact_info_upgrades_general() -> None:
    decisions = TurnDecisions(intent="general", intent_confidence=0.4, contact_info=True)
    route = route_from_decisions("0901234567", decisions)
    assert route.intent == "profile_update"
    assert route.reason == "phone_number"


async def test_route_out_of_scope() -> None:
    route = route_from_decisions(
        "hôm nay trời đẹp", TurnDecisions(intent="out_of_scope", intent_confidence=0.9)
    )
    assert route.strategy == "safe_redirect"
    assert should_use_fast_model(route) is True


async def test_route_degraded_falls_to_agent() -> None:
    route = route_from_decisions("gì đó", TurnDecisions(degraded=True))
    assert route.intent == "general"
    assert route.strategy == "agent"
    assert route.reason == "fallback"


async def test_client_parses_full_fan_out() -> None:
    client = _client()
    client._system_one = AsyncMock(  # noqa: SLF001 — test seam
        return_value=_payload(
            _answers(
                sort_by=_choice("salary_desc"),
                pleasantry_kind=_choice("greeting"),
                recent_vacancy=_noul(0.9),
            )
        )
    )
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.intent == "faq_detail"
    assert decisions.intent_confidence == 0.97
    assert decisions.sort_by == "salary_desc"
    assert decisions.pleasantry is False
    assert decisions.pleasantry_kind == "greeting"
    assert decisions.recent_vacancy is True
    assert decisions.degraded is False
    assert decisions.model == _MODEL
    assert decisions.input_tokens == 650


async def test_client_unusable_intent_degrades() -> None:
    client = _client()
    client._system_one = AsyncMock(return_value=_payload(_answers(intent=_choice("junk", 0.5))))
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.degraded is True
    assert decisions.intent == "general"


async def test_client_without_key_degrades_without_http() -> None:
    client = JevDecisionClient(api_key="", model=_MODEL)
    client._system_one = AsyncMock(side_effect=AssertionError("must not call Jev"))
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.degraded is True


async def test_client_http_error_degrades() -> None:
    client = _client()
    client._system_one = AsyncMock(side_effect=RuntimeError("jev http status=529"))
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.degraded is True


async def test_template_for_kinds() -> None:
    for kind in ("greeting", "thanks", "goodbye", "help"):
        hit = template_for(kind)
        assert hit is not None
        assert hit.reply
        assert "anh/chị" in hit.reply  # persona: neutral address on first contact
    assert template_for("none") is None
    assert template_for("junk") is None


async def test_jev_runtime_config_usable_requires_enable_and_key() -> None:
    assert JevRuntimeConfig(api_key="k", model="jev-latest", enabled=True).usable is True
    assert JevRuntimeConfig(api_key="k", model="jev-latest", enabled=False).usable is False
    assert JevRuntimeConfig(api_key="", model="jev-latest", enabled=True).usable is False


async def test_resolve_jev_env_key_stays_disabled_by_default() -> None:
    """Env fallback supplies the key; the operator toggle still gates usage."""
    from app.services.integration_settings import IntegrationSettingsService

    async def _passthrough(loader):
        return await loader()

    service = IntegrationSettingsService(db=object())
    with patch("app.services.integration_settings.cached_jev_config", _passthrough), patch(
        "os.environ", {"JEV_API_KEY": "env-key"}
    ):
        config = await service.resolve_jev()
    assert config.api_key == "env-key"
    assert config.enabled is False
    assert config.usable is False
