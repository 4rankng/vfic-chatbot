"""Tests for graph factories and GraphDeps wiring."""

import asyncio
from types import SimpleNamespace

import pytest

from app.graph.clients import MiniMaxAgent, OpenRouterEmbedder
from app.graph.factories import (
    _asks_to_explore,
    _build_fast_llm,
    build_deps,
    make_minimax_llm_json,
    reset_client_cache,
)
from app.graph.types import GraphDeps


@pytest.mark.parametrize(
    "message",
    ["cho toi xem du an khac", "con viec khac khong", "quay lai tim viec"],
)
def test_explicit_exploration_request_releases_project_focus(message):
    assert _asks_to_explore(message) is True


def test_normal_project_followup_keeps_focus():
    assert _asks_to_explore("luong bao nhieu") is False


class _Settings:
    minimax_enable = True
    llm_default_provider = "minimax"
    minimax_api_key = "sk-mm-fake"
    minimax_base_url = "https://api.minimax.io/v1"
    minimax_agent_model = "MiniMax-M2.7-highspeed"
    minimax_safety_model = "MiniMax-M2.5-highspeed"
    minimax_digest_model = ""
    minimax_request_timeout = 60
    minimax_digest_timeout = 180
    openrouter_enable = False
    embedding_provider = "openrouter"
    embedding_dim = 3072
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_api_key = ""
    openrouter_agent_model = "deepseek/deepseek-v4-flash"
    openrouter_safety_model = "deepseek/deepseek-v4-flash"
    openrouter_digest_model = "deepseek/deepseek-v4-flash"
    openrouter_embedding_model = "openai/text-embedding-3-large"
    openrouter_embedding_timeout = 60
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180
    max_llm_calls_per_turn = 5
    # IntegrationSettingsCipher reads one of these to decrypt stored secrets.
    integration_settings_encryption_key = "test-integration-key"
    jwt_secret = "test-jwt-secret"
    # ZaloRuntimeConfig fallback fields (env defaults when nothing is stored).
    zalo_bot_token = ""
    zalo_bot_webhook_secret = ""
    zalo_oa_app_id = ""
    zalo_oa_secret_key = ""
    zalo_oa_access_token = ""
    zalo_oa_refresh_token = ""


class _SettingsWithBothProviders(_Settings):
    """Both generation providers are enabled; one is selected per client."""

    minimax_api_key = "sk-mm-fake"
    openrouter_enable = True
    openrouter_api_key = "sk-or-fake"
    openrouter_base_url = "https://openrouter.ai/api/v1"
    openrouter_agent_model = "deepseek/deepseek-v3.2"
    openrouter_safety_model = "deepseek/deepseek-v3.2"
    openrouter_digest_model = "deepseek/deepseek-v3.2"
    openrouter_request_timeout = 60
    openrouter_digest_timeout = 180


@pytest.mark.asyncio
async def test_build_deps_wires_graphdeps(monkeypatch):
    class _FakeLLM:
        pass

    monkeypatch.setattr("app.graph.factories._chat_for_role", lambda *a, **k: _FakeLLM())

    deps = await build_deps(object())
    assert isinstance(deps, GraphDeps)
    assert isinstance(deps.agent, MiniMaxAgent)
    # safety client is no longer constructed (LLM judge removed); field is None.
    assert deps.safety is None
    assert isinstance(deps.embedder, OpenRouterEmbedder)
    assert deps.zalo is not None


def test_minimax_json_missing_key_names_minimax(monkeypatch):
    class _NoKeySettings(_Settings):
        minimax_api_key = ""

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _NoKeySettings())
    with pytest.raises(RuntimeError, match="MINIMAX_API_KEY"):
        make_minimax_llm_json()


def test_active_provider_no_xor_when_both_enabled(monkeypatch):
    """_active_llm_provider returns the configured default when both are enabled."""
    from app.graph.clients import _active_llm_provider

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithBothProviders())
    assert _active_llm_provider() == "minimax"


def test_active_provider_openrouter_default_when_both_enabled(monkeypatch):
    """_active_llm_provider can use OpenRouter as primary when both are enabled."""
    from app.graph.clients import _active_llm_provider

    class _OpenRouterDefault(_SettingsWithBothProviders):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    assert _active_llm_provider() == "openrouter"


def test_active_provider_openrouter_only(monkeypatch):
    """_active_llm_provider returns 'openrouter' when only OpenRouter is enabled."""
    from app.graph.clients import _active_llm_provider

    s = _SettingsWithBothProviders()
    s.minimax_enable = False
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: s)
    assert _active_llm_provider() == "openrouter"


def test_chat_for_role_returns_plain_client_default_minimax(monkeypatch):
    """_chat_for_role returns a plain ChatOpenAI for the default provider (no wrapper)."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _SettingsWithBothProviders())
    llm = _chat_for_role("agent", temperature=0.3)
    # A plain ChatOpenAI is used for the selected provider.
    assert isinstance(llm, ChatOpenAI)


def test_chat_for_role_returns_openrouter_client_when_default(monkeypatch):
    """_chat_for_role honors LLM_DEFAULT_PROVIDER=openrouter at the client level."""
    from langchain_openai import ChatOpenAI

    from app.graph.clients import _chat_for_role

    class _OpenRouterDefault(_SettingsWithBothProviders):
        llm_default_provider = "openrouter"

    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _OpenRouterDefault())
    llm = _chat_for_role("agent", temperature=0.3)
    assert isinstance(llm, ChatOpenAI)
    # The model name reflects the openrouter config, proving provider selection.
    assert "deepseek" in llm.model_name


def test_openrouter_fast_tier_requests_returned_reasoning(monkeypatch):
    captured: dict = {}
    fast_client = object()

    def fake_openrouter_chat(model, **kwargs):
        captured.update({"model": model, **kwargs})
        return fast_client

    monkeypatch.setattr(
        "app.graph.factories.get_settings",
        lambda: SimpleNamespace(
            minimax_fast_model="",
            openrouter_fast_model="deepseek/deepseek-v4-flash",
            openrouter_request_timeout=60,
        ),
    )
    monkeypatch.setattr("app.graph.factories._openrouter_chat", fake_openrouter_chat)

    result = _build_fast_llm(
        minimax_config=SimpleNamespace(enabled=False, api_key="", default_provider="openrouter"),
        openrouter_config=SimpleNamespace(enabled=True, api_key="test-key"),
    )

    assert result is fast_client
    assert captured["capture_reasoning"] is True


# ── US-001: LLM client cache ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_deps_caches_llm_clients_across_turns(monkeypatch):
    """Two build_deps calls with the same settings version build clients ONCE.

    This is the core latency fix: the expensive ChatOpenAI construction (and
    the langchain_openai import it triggers on a cold process) happens once per
    worker process, not once per turn. We count constructions by counting
    _chat_for_role invocations.
    """
    reset_client_cache()

    class _FakeLLM:
        pass

    call_count = {"n": 0}

    def _counting_chat_for_role(*args, **kwargs):
        call_count["n"] += 1
        return _FakeLLM()

    monkeypatch.setattr("app.graph.factories._chat_for_role", _counting_chat_for_role)
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    await build_deps(object())
    first_count = call_count["n"]
    assert first_count == 1  # agent only (safety client removed)

    deps2 = await build_deps(object())
    # No additional _chat_for_role calls — clients came from the cache.
    assert call_count["n"] == first_count
    assert isinstance(deps2.agent, MiniMaxAgent)

    reset_client_cache()


@pytest.mark.asyncio
async def test_build_deps_cache_invalidates_on_version_change(monkeypatch):
    """A bumped minimax/openrouter cache version rebuilds the LLM clients.

    The fake cache_version namespaces its responses, so this catches a
    regression where the cache key omits a namespace. The LLM client cache key
    covers only minimax + openrouter — the two providers whose settings drive
    agent_llm / embedder / fast_llm construction.
    """
    from app.graph import factories

    reset_client_cache()

    class _FakeLLM:
        pass

    monkeypatch.setattr("app.graph.factories._chat_for_role", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    versions = {
        "integration_minimax": "1",
        "integration_openrouter": "1",
        "integration_zalo": "1",
    }

    async def _fake_cache_version(namespace):
        return versions[namespace]

    monkeypatch.setattr("app.core.cache.cache_version", _fake_cache_version)

    await factories.build_deps(object())
    assert len(factories._client_cache) == 1
    assert "mm:1|or:1" in factories._client_cache

    # A minimax bump (admin edited the agent model / key) invalidates.
    versions["integration_minimax"] = "2"
    await factories.build_deps(object())
    assert "mm:2|or:1" in factories._client_cache

    reset_client_cache()


@pytest.mark.asyncio
async def test_build_deps_cache_survives_zalo_version_change(monkeypatch):
    """A zalo-only version bump (OA token refresh) must NOT rebuild LLM clients.

    Regression guard: the cache key previously included the zalo namespace, so
    every OA token refresh invalidated the expensive LLM client cache (5-7s
    rebuild of agent_llm + embedder + fast_llm) even though none of those
    clients depend on Zalo config. ZaloConfig feeds only the per-turn
    ZaloChannelSender, which is resolved fresh in build_deps — so a rotated
    token still takes effect on the next turn without touching this cache.
    """
    from app.graph import factories

    reset_client_cache()

    builds = {"n": 0}

    class _FakeLLM:
        pass

    def _counting_chat_for_role(*args, **kwargs):
        builds["n"] += 1
        return _FakeLLM()

    monkeypatch.setattr("app.graph.factories._chat_for_role", _counting_chat_for_role)
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    versions = {
        "integration_minimax": "1",
        "integration_openrouter": "1",
        "integration_zalo": "1",
    }

    async def _fake_cache_version(namespace):
        return versions[namespace]

    monkeypatch.setattr("app.core.cache.cache_version", _fake_cache_version)

    await factories.build_deps(object())
    assert "mm:1|or:1" in factories._client_cache
    assert builds["n"] == 1  # agent built once

    # Only the zalo namespace bumps (OA token refresh). The cache MUST NOT rebuild.
    versions["integration_zalo"] = "2"
    await factories.build_deps(object())
    assert "mm:1|or:1" in factories._client_cache  # same key, still cached
    assert builds["n"] == 1  # no additional LLM client construction

    reset_client_cache()


# ── US-002: sequential resolve_* calls (session safety) ─────────────────────


@pytest.mark.asyncio
async def test_build_deps_resolves_settings_without_concurrent_session_access(monkeypatch):
    """resolve_minimax / resolve_openrouter run sequentially, never overlapping.

    Both resolves share the same ``db`` AsyncSession. SQLAlchemy async sessions
    do NOT permit concurrent operations on one connection — running them in
    asyncio.gather causes ``InvalidRequestError: This session is provisioning a
    new connection; concurrent operations are not permitted`` (a 100% crash on
    cold cache, observed in production). This test is the regression guard: it
    wraps both resolves to track peak in-flight count, and asserts peak never
    exceeds 1 (no overlap).

    The cost is ~3ms extra on the cold path (once per process restart); warm
    turns are Redis-only and unaffected.
    """
    from app.services.integration_settings import IntegrationSettingsService

    in_flight = {"n": 0, "peak": 0}

    def _make_tracker(orig):
        async def _tracked(self):  # noqa: ANN001
            in_flight["n"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["n"])
            await asyncio.sleep(0)  # yield — if siblings were concurrent they'd overlap here
            try:
                return await orig(self)
            finally:
                in_flight["n"] -= 1

        return _tracked

    monkeypatch.setattr(
        IntegrationSettingsService,
        "resolve_minimax",
        _make_tracker(IntegrationSettingsService.resolve_minimax),
    )
    monkeypatch.setattr(
        IntegrationSettingsService,
        "resolve_openrouter",
        _make_tracker(IntegrationSettingsService.resolve_openrouter),
    )
    monkeypatch.setattr("app.graph.factories.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.graph.clients.get_settings", lambda: _Settings())

    reset_client_cache()
    await build_deps(object())

    assert in_flight["peak"] == 1, (
        f"resolve_* calls overlapped (peak={in_flight['peak']}); "
        "expected sequential — concurrent session access crashes SQLAlchemy"
    )
    assert in_flight["n"] == 0  # both fully completed
    reset_client_cache()
