"""Unit tests for the answer cache policy + storage tiers (no DB, no live Redis).

The eligibility predicates are the load-bearing guards: they decide which turns
may be served from a stored reply, so they get a full truth table. The storage
tests then cover both tiers against an in-memory Redis double.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.core.cache as cache_mod
import app.core.redis as redis_mod
from app.graph import answer_cache
from app.graph.answer_cache import (
    answer_cache_get,
    answer_cache_put,
    answer_scope,
    is_answer_cacheable,
    is_shareable_reply,
    is_standalone_kb_question,
)
from tests.helpers.redis_fake import FakeHashRedis


class _ExplodingEmbedder:
    """An embedder that fails the test if anything embeds (the exact tier must not)."""

    async def __call__(self, query: str) -> list[float]:
        raise AssertionError("the exact tier must not embed the query")


class _MappingEmbedder:
    """Returns the vector registered for a query; raises on an unregistered one."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[str] = []

    async def __call__(self, query: str) -> list[float]:
        self.calls.append(query)
        return self.vectors[query]


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        answer_cache_enabled=True,
        answer_cache_semantic_enabled=False,
        answer_cache_threshold=0.95,
        answer_cache_capacity=100,
        answer_cache_ttl_seconds=21600,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


async def _install(monkeypatch, **overrides) -> FakeHashRedis:
    """Wire the answer cache to a fresh in-memory Redis and static settings.

    ``app.core.cache`` calls ``get_redis()`` synchronously and awaits the
    command; ``app.graph.semantic_cache`` awaits the client itself — each module
    is patched in the shape it uses.
    """
    fake = FakeHashRedis()
    monkeypatch.setattr(answer_cache, "get_settings", lambda: _settings(**overrides))
    monkeypatch.setattr(cache_mod, "get_redis", lambda: fake)

    async def _get_redis():
        return fake

    monkeypatch.setattr(redis_mod, "get_redis", _get_redis)
    return fake


# --- is_standalone_kb_question ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Lương công nhân LG Display bao nhiêu?",
        "Điều kiện đăng ký là gì?",
        "  CÔNG TY  có xe đưa đón không  ",
    ],
)
def test_standalone_questions_are_accepted(text):
    assert is_standalone_kb_question(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Luong?",
        "Ngắn",
        "Thế nào?",
        "Như thế nào ạ?",
        "Còn gì nữa không?",
        "Dự án đó thế nào?",
        "Chỗ đó ở đâu?",
        "Cái đó là gì?",
        "Nó là gì?",
        "Thêm không?",
        "Rồi sao?",
        "Thế còn?",
    ],
)
def test_fragments_and_continuations_are_rejected(text):
    assert is_standalone_kb_question(text) is False


def test_diacritics_do_not_change_the_verdict():
    """The marker check runs on the accent-insensitive form, so 'đ'/'d' agree."""
    assert is_standalone_kb_question("Chỗ đó ở đâu?") is False
    assert is_standalone_kb_question("Cho do o dau?") is False


# --- is_answer_cacheable ------------------------------------------------------


def _cacheable(**overrides) -> bool:
    kwargs = dict(
        allowed_tools=("search_knowledge",),
        tingting_reset_allowed=False,
        tingting_support_account=False,
        has_conversation_history=False,
        user_text="Lương công nhân LG Display bao nhiêu?",
    )
    kwargs.update(overrides)
    return is_answer_cacheable(**kwargs)


@pytest.mark.parametrize(
    "allowed_tools",
    [
        ("search_knowledge",),
        ("get_product_features", "search_knowledge"),
        ("list_active_projects",),
        ("list_active_jobs",),
        ("search_bus_timetable",),
        ("compare_income",),
    ],
)
def test_project_data_tools_are_cacheable(allowed_tools):
    """Every tool that serves stateless Project information qualifies."""
    assert _cacheable(allowed_tools=allowed_tools) is True


@pytest.mark.parametrize(
    "allowed_tools",
    [
        None,  # low-confidence route: any tool may be called
        (),
        ("search_user_memory",),
        ("search_user_memory", "search_knowledge"),
        ("recommend_projects", "search_knowledge"),
        ("recommend_jobs",),
        ("verify_tingting_identity", "search_knowledge"),
        ("some_future_tool",),  # unclassified tools fail closed
    ],
)
def test_candidate_dependent_or_unknown_tools_are_not_cacheable(allowed_tools):
    assert _cacheable(allowed_tools=allowed_tools) is False


@pytest.mark.parametrize(
    "allowed_tools", [("list_active_projects",), ("list_active_jobs",)]
)
def test_context_composed_catalog_tools_need_a_history_free_turn(allowed_tools):
    """Their filters can be folded in from an earlier turn."""
    assert _cacheable(allowed_tools=allowed_tools, has_conversation_history=False) is True
    assert _cacheable(allowed_tools=allowed_tools, has_conversation_history=True) is False


def test_knowledge_tools_ignore_conversation_history():
    """Their query comes from the current turn, so history cannot change it."""
    assert _cacheable(has_conversation_history=True) is True


def test_tingting_turns_are_not_cacheable():
    assert _cacheable(tingting_reset_allowed=True) is False
    assert _cacheable(tingting_support_account=True) is False


def test_a_profile_ask_does_not_disqualify_a_generic_reply():
    """The ask is generic; refusing it would disable the cache for new candidates."""
    assert _cacheable(user_text="Kho Samsung SDS Đình Vũ có ký túc xá không?") is True


def test_a_fragment_is_not_cacheable_even_on_a_project_data_lane():
    assert _cacheable(user_text="Thế nào?") is False


# --- is_shareable_reply -------------------------------------------------------


def test_shareable_reply_rejects_empty_and_no_evidence_text():
    assert is_shareable_reply("", lead_row=None) is False
    assert is_shareable_reply("   ", lead_row=None) is False
    assert is_shareable_reply("Không tìm thấy thông tin phù hợp.", lead_row=None) is False
    assert is_shareable_reply("Lỗi khi gọi tool search_knowledge", lead_row=None) is False
    assert is_shareable_reply("unknown tool: search_knowledge", lead_row=None) is False


def test_shareable_reply_accepts_a_generic_answer():
    generic = "Lương khoảng 8 triệu đồng/tháng ạ."
    assert is_shareable_reply(generic, lead_row=None) is True
    assert is_shareable_reply(generic, lead_row={}) is True


@pytest.mark.parametrize(
    "lead_row,reply",
    [
        ({"name": "Nguyễn Văn An"}, "Chào anh Nguyễn Văn An, lương khoảng 8 triệu."),
        ({"name": "Nguyen Van An"}, "Chào anh nguyễn văn an, lương khoảng 8 triệu."),
        ({"phone": "0901234567"}, "Anh gọi 0901234567 để biết thêm nhé."),
        ({"email": "an@example.com"}, "Anh gửi mail tới an@example.com nhé."),
    ],
)
def test_shareable_reply_rejects_replies_naming_the_lead(lead_row, reply):
    assert is_shareable_reply(reply, lead_row=lead_row) is False


def test_shareable_reply_ignores_too_short_lead_identifiers():
    """A two-character name is not evidence of personalization."""
    reply = "Lương khoảng 8 triệu ạ."
    assert is_shareable_reply(reply, lead_row={"name": "An"}) is True
    assert is_shareable_reply(reply, lead_row={"name": None}) is True


# --- answer_scope -------------------------------------------------------------


_BASE_SCOPE_KWARGS = dict(project_scope="scope-a", address="anh")


async def _scope_with(monkeypatch, versions: dict[str, str], **overrides) -> str:
    async def _version(namespace: str) -> str:
        return versions.get(namespace, "0")

    monkeypatch.setattr(answer_cache, "cache_version", _version)
    kwargs = dict(_BASE_SCOPE_KWARGS)
    kwargs.update(overrides)
    return await answer_scope(**kwargs)


_VERSION_NAMESPACES = ("knowledge", "preamble", "jobs")


@pytest.mark.parametrize("namespace", _VERSION_NAMESPACES)
async def test_answer_scope_changes_with_every_version_counter(monkeypatch, namespace):
    baseline = await _scope_with(monkeypatch, {})
    bumped = await _scope_with(monkeypatch, {namespace: "2"})
    assert bumped != baseline


@pytest.mark.parametrize(
    "override",
    [
        {"tenant_id": "other"},
        {"language": "en"},
        {"project_scope": "scope-b"},
        {"address": "chị"},
    ],
)
async def test_answer_scope_changes_with_every_non_version_dimension(monkeypatch, override):
    baseline = await _scope_with(monkeypatch, {})
    other = await _scope_with(monkeypatch, {}, **override)
    assert other != baseline


async def test_answer_scope_is_stable_for_identical_inputs(monkeypatch):
    first = await _scope_with(monkeypatch, {"knowledge": "7"})
    second = await _scope_with(monkeypatch, {"knowledge": "7"})
    assert first == second
    assert len(first) == 32


# --- exact tier ---------------------------------------------------------------


async def test_exact_tier_round_trip_without_embedding(monkeypatch):
    fake = await _install(monkeypatch)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "Lương công nhân bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope="s1"
    )
    hit = await answer_cache_get("Lương công nhân bao nhiêu?", embedder=embedder, scope="s1")

    assert hit is not None
    assert hit.result == "Khoảng 8 triệu ạ."
    assert hit.tier == "exact"
    assert hit.similarity == 1.0
    assert fake._strings, "the exact tier must write a plain Redis string"


async def test_exact_tier_is_case_and_whitespace_insensitive(monkeypatch):
    await _install(monkeypatch)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "  LƯƠNG công nhân  bao nhiêu ",
        "Khoảng 8 triệu ạ.",
        embedder=embedder,
        scope="s1",
    )
    hit = await answer_cache_get("lương công nhân bao nhiêu", embedder=embedder, scope="s1")

    assert hit is not None and hit.result == "Khoảng 8 triệu ạ."


async def test_exact_tier_is_scope_separated(monkeypatch):
    await _install(monkeypatch)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "Lương bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope="s1"
    )

    assert await answer_cache_get("Lương bao nhiêu?", embedder=embedder, scope="s2") is None


async def test_empty_scope_is_never_read_or_written(monkeypatch):
    fake = await _install(monkeypatch)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "Lương bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope=""
    )

    assert fake._strings == {}
    assert await answer_cache_get("Lương bao nhiêu?", embedder=embedder, scope="") is None


async def test_disabled_cache_stores_and_returns_nothing(monkeypatch):
    fake = await _install(monkeypatch, answer_cache_enabled=False)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "Lương bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope="s1"
    )

    assert fake._strings == {}
    assert await answer_cache_get("Lương bao nhiêu?", embedder=embedder, scope="s1") is None


# --- semantic tier ------------------------------------------------------------


async def test_semantic_tier_needs_an_opt_in(monkeypatch):
    """With the paraphrase tier off, a non-identical question never embeds."""
    await _install(monkeypatch, answer_cache_semantic_enabled=False)
    embedder = _ExplodingEmbedder()

    await answer_cache_put(
        "Lương bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope="s1"
    )

    hit = await answer_cache_get("Mức lương thế nào?", embedder=embedder, scope="s1")
    assert hit is None


async def test_semantic_tier_hits_a_near_identical_paraphrase(monkeypatch):
    await _install(monkeypatch, answer_cache_semantic_enabled=True)
    embedder = _MappingEmbedder(
        {
            "Lương bao nhiêu?": [1.0, 0.0, 0.0],
            "Mức lương thế nào?": [0.995, 0.0999, 0.0],
            "Xe đưa đón thế nào?": [0.0, 0.0, 1.0],
        }
    )

    await answer_cache_put(
        "Lương bao nhiêu?", "Khoảng 8 triệu ạ.", embedder=embedder, scope="s1"
    )

    hit = await answer_cache_get("Mức lương thế nào?", embedder=embedder, scope="s1")
    assert hit is not None
    assert hit.result == "Khoảng 8 triệu ạ."
    assert hit.tier == "semantic"
    assert hit.similarity >= 0.95

    other = await answer_cache_get("Xe đưa đón thế nào?", embedder=embedder, scope="s1")
    assert other is None
