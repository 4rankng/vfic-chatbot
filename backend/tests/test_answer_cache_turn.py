"""End-to-end answer-cache behaviour through ``lanes._agent_turn``.

Drives the real lane with duck-typed fakes (no DB, no LLM, no live Redis) and an
in-memory Redis double, so the full path is covered: eligibility → scope →
lookup → agent → write → next-turn hit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.core.cache as cache_mod
import app.core.redis as redis_mod
from app.core.cache import bump_kb_caches
from app.graph import answer_cache, lanes
from app.graph.direct_context import ProjectTurnContext
from app.graph.ports import TurnDecisions
from app.graph.router import TurnRoute
from app.graph.types import BotRunState, GraphDeps
from tests.helpers.redis_fake import FakeHashRedis

CONV_ID = "00000000-0000-0000-0000-000000000001"
QUESTION = "Lương công nhân LG Display bao nhiêu?"
REPLY = "Lương công nhân LG Display khoảng 8 triệu đồng/tháng ạ."


class _ExplodingEmbedder:
    """The paraphrase tier is off in these tests, so nothing may embed."""

    async def __call__(self, query: str) -> list[float]:
        raise AssertionError("the exact tier must not embed the query")


class _CountingAgent:
    def __init__(self, reply: str = REPLY) -> None:
        self.reply = reply
        self.calls = 0
        self.allowed_tools_seen: list[tuple[str, ...] | None] = []

    async def agent(self, user_text, **kwargs):  # noqa: ARG002
        self.calls += 1
        self.allowed_tools_seen.append(kwargs.get("allowed_tools"))
        return self.reply


class _FakeLead:
    def __init__(self, profile: str = "", question: str = "") -> None:
        self.profile = profile
        self.question = question

    async def context(self, *args, **kwargs):  # noqa: ARG002
        return self.profile, self.question

    def instruction(self, question):  # noqa: ARG002
        return "Hãy hỏi số điện thoại của ứng viên."


class _FakeRetrieval:
    """Only the scope readers the answer cache consults."""

    def __init__(self, slugs: dict[str, str]) -> None:
        self.slugs = slugs

    async def project_id_by_slug(self, slug, *, active_only=False):  # noqa: ARG002
        return self.slugs.get(slug)

    async def active_project_ids(self):
        return list(self.slugs.values())


def _project_context(slug: str = "lg-display") -> ProjectTurnContext:
    return ProjectTurnContext(
        state="FOCUSED",
        project_id=f"id-{slug}",
        project_slug=slug,
        project_name="LG Display",
        knowledge_mode="RAG",
    )


def _deps(*, agent, lead, slugs: dict[str, str]) -> GraphDeps:
    return GraphDeps(
        db=None,  # type: ignore[arg-type] — untouched on the agent lane
        agent=agent,  # type: ignore[arg-type]
        embedder=_ExplodingEmbedder(),  # type: ignore[arg-type]
        zalo=None,
        conversation=None,  # type: ignore[arg-type]
        retrieval=_FakeRetrieval(slugs),  # type: ignore[arg-type]
        lead=lead,  # type: ignore[arg-type]
    )


def _state() -> BotRunState:
    return BotRunState(conversation_id=CONV_ID, version_at_start=1, user_text=QUESTION)


@pytest.fixture
def cache_env(monkeypatch) -> FakeHashRedis:
    """Static answer-cache settings + an in-memory Redis, and no prompt/DB reads."""
    fake = FakeHashRedis()
    settings = SimpleNamespace(
        answer_cache_enabled=True,
        answer_cache_semantic_enabled=False,
        answer_cache_threshold=0.95,
        answer_cache_capacity=100,
        answer_cache_ttl_seconds=21600,
        rag_cache_enabled=False,
    )
    monkeypatch.setattr(answer_cache, "get_settings", lambda: settings)
    monkeypatch.setattr(cache_mod, "get_redis", lambda: fake)

    async def _get_redis():
        return fake

    monkeypatch.setattr(redis_mod, "get_redis", _get_redis)

    async def _fake_system_prompt(retrieval, *, provider=None):  # noqa: ARG001
        return "fake system prompt", True

    monkeypatch.setattr("app.graph.context.build_system_prompt", _fake_system_prompt)
    monkeypatch.setattr(lanes, "build_agent_user_text", lambda **kw: kw["current_user_text"])
    return fake


_DEFAULT_PROJECT = object()


async def _turn(
    deps: GraphDeps,
    *,
    project_context=_DEFAULT_PROJECT,
    lead_row: dict | None = None,
    timings: dict | None = None,
    route: TurnRoute | None = None,
    recent_messages: list | None = None,
):
    if project_context is _DEFAULT_PROJECT:
        project_context = _project_context()
    timings = {} if timings is None else timings
    if route is not None:
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(lanes, "route_from_decisions", lambda *a, **kw: route)
    try:
        reply = await lanes._agent_turn(
            _state(),
            deps,
            QUESTION,
            provider="zalo_bot",
            chat_id="z1",
            recent_messages=recent_messages or [],
            timings=timings,
            decisions=TurnDecisions(intent="faq_detail", intent_confidence=0.9),
            project_context=project_context,
            lead_row=lead_row,
        )
    finally:
        if route is not None:
            monkeypatch.undo()
    return reply, timings


def _answer_keys(fake: FakeHashRedis) -> list[str]:
    return [key for key in fake._strings if key.startswith("answer:")]


# --- the round trip -----------------------------------------------------------


@pytest.mark.asyncio
async def test_second_identical_question_is_answered_from_the_cache(cache_env):
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})

    first_reply, first_timings = await _turn(deps, timings={"prefetch_hit": True})
    second_reply, second_timings = await _turn(deps, timings={"prefetch_hit": True})

    assert first_reply == REPLY and second_reply == REPLY
    assert agent.calls == 1, "the second turn must not run the agent"
    assert agent.allowed_tools_seen == [("search_knowledge",)]
    assert first_timings["answer_cache"] == {"hit": False, "stored": True}
    assert second_timings["answer_cache"] == {
        "hit": True,
        "tier": "exact",
        "similarity": 1.0,
    }
    assert second_timings["answer_cache_lookup_ms"] >= 0
    assert len(_answer_keys(cache_env)) == 1


@pytest.mark.asyncio
async def test_a_kb_write_makes_the_cached_answer_unreachable(cache_env):
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})

    await _turn(deps, timings={"prefetch_hit": True})
    await _turn(deps, timings={"prefetch_hit": True})
    assert agent.calls == 1

    await bump_kb_caches()

    _reply, timings = await _turn(deps, timings={"prefetch_hit": True})
    assert agent.calls == 2, "a bumped knowledge version must force a fresh answer"
    assert timings["answer_cache"] == {"hit": False, "stored": True}


@pytest.mark.asyncio
async def test_a_different_project_scope_is_a_miss(cache_env):
    agent = _CountingAgent()
    slugs = {"lg-display": "id-lg", "hyundai": "id-hd"}
    deps = _deps(agent=agent, lead=_FakeLead(), slugs=slugs)

    await _turn(
        deps, project_context=_project_context("lg-display"), timings={"prefetch_hit": True}
    )
    _reply, timings = await _turn(
        deps, project_context=_project_context("hyundai"), timings={"prefetch_hit": True}
    )

    assert agent.calls == 2
    assert timings["answer_cache"] == {"hit": False, "stored": True}
    assert len(_answer_keys(cache_env)) == 2


# --- the write gate -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_turn_without_tool_evidence_stores_nothing(cache_env):
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})

    await _turn(deps, timings={"prefetch_hit": False})
    await _turn(deps, timings={})  # no signal at all
    await _turn(deps, timings={"tool_calls": 0})  # tool bound but never called

    assert agent.calls == 3
    assert _answer_keys(cache_env) == []


@pytest.mark.asyncio
async def test_a_no_evidence_reply_is_never_stored(cache_env):
    no_evidence = "Không tìm thấy thông tin phù hợp trong cơ sở dữ liệu."
    agent = _CountingAgent(reply=no_evidence)
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})

    await _turn(deps, timings={"prefetch_hit": True})
    await _turn(deps, timings={"prefetch_hit": True})

    assert agent.calls == 2
    assert _answer_keys(cache_env) == []


@pytest.mark.asyncio
async def test_a_reply_that_names_the_lead_is_not_stored(cache_env):
    lead_row = {"name": "Nguyễn Văn An", "gender": "male"}
    agent = _CountingAgent(reply="Chào anh Nguyễn Văn An, lương khoảng 8 triệu ạ.")
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})

    await _turn(deps, lead_row=lead_row, timings={"prefetch_hit": True})
    await _turn(deps, lead_row=lead_row, timings={"prefetch_hit": True})

    assert agent.calls == 2, "a personalized reply must never be re-served"
    assert _answer_keys(cache_env) == []


@pytest.mark.asyncio
async def test_a_profile_ask_turn_is_cached(cache_env):
    """A generic profile ask must not disable the cache for new candidates."""
    agent = _CountingAgent()
    lead = _FakeLead(question="Số điện thoại của anh là gì?")
    deps = _deps(agent=agent, lead=lead, slugs={"lg-display": "id-lg"})

    await _turn(deps, timings={"prefetch_hit": True})
    _reply, timings = await _turn(deps, timings={"prefetch_hit": True})

    assert agent.calls == 1, "the second turn must be served from the cache"
    assert timings["answer_cache"] == {"hit": True, "tier": "exact", "similarity": 1.0}


@pytest.mark.asyncio
async def test_a_candidate_dependent_tool_allowlist_is_never_cached(cache_env):
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})
    # A route whose tools include the memory read: the reply may depend on what
    # was remembered about this candidate.
    route = TurnRoute(
        "faq_detail",
        "knowledge_lookup",
        tools=("search_user_memory", "search_knowledge"),
        reason="job_detail_terms",
        confidence=0.9,
    )
    await _turn(deps, project_context=None, timings={"prefetch_hit": True}, route=route)
    await _turn(deps, project_context=None, timings={"prefetch_hit": True}, route=route)

    assert agent.calls == 2
    assert agent.allowed_tools_seen == [("search_user_memory", "search_knowledge")] * 2
    assert _answer_keys(cache_env) == []


@pytest.mark.asyncio
async def test_a_catalog_turn_with_history_is_never_cached(cache_env):
    """A catalog query can absorb a preference stated in an earlier turn."""
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})
    route = TurnRoute(
        "recommend",
        "structured_lookup",
        tools=("list_active_projects",),
        reason="recommendation_terms",
        confidence=0.9,
    )

    await _turn(deps, project_context=None, timings={"tool_calls": 1}, route=route)
    _reply, timings = await _turn(
        deps,
        project_context=None,
        timings={"tool_calls": 1},
        route=route,
        recent_messages=[{"role": "user", "content": "anh ở Hải Phòng"}],
    )

    assert agent.calls == 2, "the history-bearing turn must re-run the agent"
    assert "answer_cache" not in timings, "the history-bearing turn is not even looked up"
    # Only the history-free turn stored an entry.
    assert len(_answer_keys(cache_env)) == 1


@pytest.mark.asyncio
async def test_a_catalog_turn_without_history_is_cached(cache_env):
    agent = _CountingAgent()
    deps = _deps(agent=agent, lead=_FakeLead(), slugs={"lg-display": "id-lg"})
    route = TurnRoute(
        "recommend",
        "structured_lookup",
        tools=("list_active_projects",),
        reason="recommendation_terms",
        confidence=0.9,
    )

    # No routed prefetch exists for the catalog lane: the model calls the tool
    # itself, so the evidence signal is ``tool_calls``.
    await _turn(deps, project_context=None, timings={"tool_calls": 1}, route=route)
    _reply, timings = await _turn(deps, project_context=None, timings={"tool_calls": 1}, route=route)

    assert agent.calls == 1
    assert timings["answer_cache"] == {"hit": True, "tier": "exact", "similarity": 1.0}
