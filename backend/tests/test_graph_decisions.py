"""Unit pins for the Jev-backed turn decision layer.

Covers the question taxonomy contract, the route-mapping policy, client
parsing (including degraded fallbacks), and the Jev integration settings
contract. No network access: the client's ``_system_one`` is stubbed,
mirroring how the graph tests fake the ports.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.graph.decisions as decisions_module
from app.graph.decisions import (
    _GENDER_CRITERIA,
    _INTENT_CRITERIA,
    JEV_RETRY_BACKOFF_S,
    JevDecisionClient,
    _retry_after_seconds,
    build_turn_questions,
    build_turn_state,
)
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
        "recent_vacancy",
        "contact_info",
        "gender",
        "gender_stated",
    }
    assert set(build_turn_questions(include_gender=False)) == {
        "intent",
        "vacancy_listing",
        "sort_by",
        "pleasantry",
        "recent_vacancy",
        "contact_info",
    }
    assert set(_GENDER_CRITERIA) == {"male", "female", "unknown"}
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
    assert route.strategy == "agent"
    assert route.reason == "small_talk_terms"


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
                recent_vacancy=_noul(0.9),
            )
        )
    )
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.intent == "faq_detail"
    assert decisions.intent_confidence == 0.97
    assert decisions.sort_by == "salary_desc"
    assert decisions.pleasantry is False
    assert decisions.recent_vacancy is True
    assert decisions.degraded is False
    assert decisions.model == _MODEL
    assert decisions.input_tokens == 650


async def test_client_parses_gender_answer() -> None:
    client = _client()
    client._system_one = AsyncMock(  # noqa: SLF001 — test seam
        return_value=_payload(_answers(gender=_choice("female", 0.9), gender_stated=_noul(0.9)))
    )
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.gender == "female"
    assert decisions.gender_confidence == 0.9
    assert decisions.gender_stated is True
    assert decisions.degraded is False


async def test_client_non_canonical_gender_reads_unknown() -> None:
    client = _client()
    client._system_one = AsyncMock(  # noqa: SLF001 — test seam
        return_value=_payload(_answers(gender=_choice("nam", 0.9)))
    )
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.gender == "unknown"


async def test_client_missing_gender_answer_is_unknown_not_degraded() -> None:
    client = _client()
    client._system_one = AsyncMock(return_value=_payload(_answers()))  # noqa: SLF001
    decisions = await client.decide_turn(user_text="x", recent_messages=[])
    assert decisions.gender == "unknown"
    assert decisions.gender_confidence == 0.0
    assert decisions.degraded is False


async def test_client_skips_gender_question_when_disabled() -> None:
    client = _client()
    sent: dict = {}

    async def _capture(state, questions):
        sent["questions"] = questions
        return _payload(_answers())

    client._system_one = _capture  # noqa: SLF001 — test seam
    await client.decide_turn(user_text="x", recent_messages=[], include_gender=False)
    assert "gender" not in sent["questions"]


def test_turn_state_carries_and_caps_profile_name() -> None:
    state = build_turn_state("x", [], profile_name="Nguyễn Thị Hoa")
    assert state["profile_name"] == "Nguyễn Thị Hoa"
    assert build_turn_state("x", [], profile_name="a" * 200)["profile_name"] == "a" * 120
    assert build_turn_state("x", [])["profile_name"] == ""


def test_turn_state_recent_excludes_bot_and_recruiter_messages() -> None:
    from types import SimpleNamespace

    history = [
        SimpleNamespace(sender="WORKER", body="em tên Hoa"),
        SimpleNamespace(sender="BOT", body="Dạ em chào anh/chị"),
        SimpleNamespace(sender="RECRUITER", body="Chị cho em xin số điện thoại"),
        SimpleNamespace(sender="WORKER", body="chị muốn hỏi lương"),
    ]
    state = build_turn_state("x", history)
    assert state["recent"] == ["em tên Hoa", "chị muốn hỏi lương"]


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
    with patch(
        "app.services.integration_settings.providers.llm.cached_jev_config", _passthrough
    ), patch(
        "os.environ", {"JEV_API_KEY": "env-key"}
    ):
        config = await service.resolve_jev()
    assert config.api_key == "env-key"
    assert config.enabled is False
    assert config.usable is False


# ---------------------------------------------------------------------------
# HTTP client behavior: shared deadline, Retry-After, SDK-parity retry set
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, *, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


def _http_stub(responses):
    client = SimpleNamespace(post=AsyncMock(side_effect=responses))
    return client


def _install_http(monkeypatch, client):
    monkeypatch.setattr(decisions_module, "get_http_client", AsyncMock(return_value=client))
    sleeps: list[float] = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(decisions_module.asyncio, "sleep", _sleep)
    return sleeps


def test_retry_after_seconds_parsing() -> None:
    assert _retry_after_seconds({"retry-after-ms": "1500"}) == 1.5
    assert _retry_after_seconds({"retry-after": "2"}) == 2.0
    # retry-after-ms wins when both are present.
    assert _retry_after_seconds({"retry-after-ms": "x", "retry-after": "3"}) == 3.0
    # HTTP-date form is not parsed; caller falls back to the fixed backoff.
    assert _retry_after_seconds({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None
    assert _retry_after_seconds({}) is None


async def test_system_one_honors_retry_after_and_bounds_timeout(monkeypatch) -> None:
    client = _http_stub(
        [
            _FakeResponse(429, headers={"retry-after-ms": "1200"}),
            _FakeResponse(200, payload={"model": "m", "answers": {}, "usage": {}}),
        ]
    )
    sleeps = _install_http(monkeypatch, client)

    out = await _client()._system_one({"a": 1}, {"q": {"type": "noul", "instructions": "x"}})

    assert out["model"] == "m"
    assert sleeps == [1.2]
    # The per-request timeout is passed to the httpx method (not client construction).
    assert client.post.await_args.kwargs["timeout"] > 0


async def test_system_one_retries_transient_5xx(monkeypatch) -> None:
    client = _http_stub(
        [
            _FakeResponse(503),
            _FakeResponse(200, payload={"model": "m", "answers": {}, "usage": {}}),
        ]
    )
    sleeps = _install_http(monkeypatch, client)

    out = await _client()._system_one({}, {"q": {"type": "noul", "instructions": "x"}})

    assert out["model"] == "m"
    assert sleeps == [JEV_RETRY_BACKOFF_S]


async def test_system_one_does_not_retry_non_retryable_status(monkeypatch) -> None:
    client = _http_stub([_FakeResponse(400)])
    _install_http(monkeypatch, client)

    with pytest.raises(RuntimeError, match="status=400"):
        await _client()._system_one({}, {"q": {"type": "noul", "instructions": "x"}})
    assert client.post.await_count == 1


async def test_system_one_skips_retry_when_wait_exceeds_budget(monkeypatch) -> None:
    client = _http_stub([_FakeResponse(429, headers={"retry-after": "9999"})])
    _install_http(monkeypatch, client)

    with pytest.raises(RuntimeError, match="status=429"):
        await _client()._system_one({}, {"q": {"type": "noul", "instructions": "x"}})
    assert client.post.await_count == 1
